# get_fitfiles.py
import argparse
import subprocess
import os
from os.path import basename
import io
import gzip
import boto3
import dropbox
import json, requests
from dropbox.files import SharedLink, FileMetadata, FolderMetadata
import process_fit_sessions


import logging
logging.getLogger().setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# CrewOptic app / DB tenant plumbing
from run import app                    # Flask app (has TENANTS loaded)
from db import tenant_context, get_db_connection
from flask import current_app

# -------------- Dropbox + S3 helpers (constructed per tenant) ---------------

def make_dropbox_client(cfg: dict) -> dropbox.Dropbox:
    """
    Prefer to keep tenant secrets in tenants.yaml, e.g.:
      dropbox:
        app_key: ...
        app_secret: ...
        refresh_token: ...
    Fallback to legacy constants if not present.
    """
    d = (cfg.get("dropbox") or {})
    app_key = d.get("app_key",  "fju7nouhxe4itm6")
    app_sec = d.get("app_secret","gam0klqoamz6eha")
    refresh = d.get("refresh_token", "cKzc4xGTNOEAAAAAAAAAAQAcb5uxXhI4NlZnb_hvUIPNN6AFGkqeUx6NraDpgBsB")
    return dropbox.Dropbox(
        oauth2_refresh_token=refresh,
        app_key=app_key,
        app_secret=app_sec,
    )

def make_s3_client(_cfg: dict):
    # If you need per-tenant role/creds, pull from cfg here
    return boto3.client('s3')

# ------------------------------- core logic ---------------------------------

def upload_to_s3(s3, bucket: str, buf: io.BytesIO, key: str) -> None:
    buf.seek(0)
    s3.upload_fileobj(buf, bucket, key)
    print(f"      ↳ s3://{bucket}/{key}")

def link_root_path(dbx: dropbox.Dropbox, link_url: str) -> str:
    meta = dbx.sharing_get_shared_link_metadata(link_url)
    if not isinstance(meta, dropbox.sharing.FolderLinkMetadata):
        raise ValueError("Link is not a folder")
    return meta.path_lower.lstrip("/") if meta.path_lower else ""

def walk_folder(dbx: dropbox.Dropbox, link_url: str, rel_path: str | None = None):
    if rel_path is None:
        rel_path = link_root_path(dbx, link_url)

    shared = SharedLink(url=link_url)
    res    = dbx.files_list_folder(path=rel_path, shared_link=shared)

    logger.debug("walk_folder → %s entries at path '%s'", len(res.entries), rel_path or "<root>")

    for entry in res.entries:
        if isinstance(entry, FileMetadata):
            logger.debug("   · found file %s", entry.name)
            yield entry, rel_path
        elif isinstance(entry, FolderMetadata):
            sub = f"{rel_path}/{entry.name}" if rel_path else entry.name
            yield from walk_folder(dbx, link_url, sub)

    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        for entry in res.entries:
            if isinstance(entry, FileMetadata):
                logger.debug("   · found file %s", entry.name)
                yield entry, rel_path

def already_in_s3(aid, filename, s3_keys):
    want = basename(filename).strip().lower()
    return any(basename(key).strip().lower() == want for key in s3_keys)

def process_athlete(dbx, s3, bucket: str, s3_prefix: str, aid: str, link: str, tenant_key: str) -> None:
    print(f"\n• Athlete {aid}")
    # NOTE: process_fit_sessions.iter_fit_keys_for_athlete must read from the correct S3 location.
    # If it’s tenant-aware, pass `tenant_key` into it. Otherwise keep as-is.

    process_fit_sessions.configure_storage(bucket=bucket, prefix=s3_prefix, client=s3)

    s3_keys = list(process_fit_sessions.iter_fit_keys_for_athlete(aid))
    new_files = []

    try:
        for entry, rel in walk_folder(dbx, link):
            name_low = entry.name.lower()
            is_gz  = name_low.endswith(".fit.gz") or name_low.endswith(".gz")
            is_fit = name_low.endswith(".fit")
            is_tcx = name_low.endswith(".tcx")
            if not (is_gz or is_fit or is_tcx):
                continue

            final_name = entry.name[:-3] if is_gz else entry.name  # strip .gz

            if already_in_s3(aid, final_name, s3_keys):
                print(f"   – skipping {final_name} (already in S3)")
                continue

            path = f"/{rel}/{entry.name}" if rel else f"/{entry.name}"
            print(f"   – downloading {path.lstrip('/')}")

            _, resp = dbx.sharing_get_shared_link_file(url=link, path=path)
            file_bytes = gzip.GzipFile(fileobj=io.BytesIO(resp.content)).read() if is_gz else resp.content

            # Upload to S3 (namespace by tenant → s3_prefix already includes it)
            s3_key = f"{s3_prefix}/{aid}/{final_name}"
            print(f"   – uploading {final_name} to S3 path: {s3_key}")
            upload_to_s3(s3, bucket, io.BytesIO(file_bytes), s3_key)

            new_files.append(s3_key)

    except Exception as exc:
        print("   ! error:", exc)
        return

    # Process new files (pass tenant to subprocesses so they use the same DB)
    for s3_key in new_files:
        print(f"   → processing {s3_key}")
        subprocess.run(["python3", "process_fit_sessions.py",
                        "--tenant", tenant_key, "--aid", str(aid), "--file", s3_key],
                       check=False)

        print(f"   → processing results: {s3_key}")
        subprocess.run(["python3", "process_results.py",
                        "--tenant", tenant_key, "--aid", str(aid), "--file", s3_key],
                       check=False)

def get_fitfiles_for_tenant(tenant_key: str):
    """
    Run the job for a single tenant. Assumes we're already inside:
      with app.app_context():
          with tenant_context(app, tenant_key):
              get_fitfiles_for_tenant(tenant_key)
    """
    cfg = current_app.config["TENANTS"][tenant_key]

    # Per-tenant storage settings (adjust your tenants.yaml accordingly)
    bucket    = cfg.get("s3_bucket", "eubctrackingdata")
    base_pref = cfg.get("s3_prefix", "fitfiles")
    s3_prefix = f"{base_pref}/{tenant_key}"  # namespacing by tenant

    dbx = make_dropbox_client(cfg)
    s3  = make_s3_client(cfg)

    # Pull athletes from the tenant DB
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT Athlete_ID, DropBox
                FROM Athletes
                WHERE DropBox IS NOT NULL
            """)
            rows = cur.fetchall()
    finally:
        conn.close()

    for row in rows:
        aid  = str(row["Athlete_ID"])
        link = row["DropBox"]
        print(f"Athlete {aid} → {link}")
        process_athlete(dbx, s3, bucket, s3_prefix, aid, link, tenant_key)

# ----------------------------------- CLI ------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch and process FIT files per tenant")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--tenant", help="Tenant key, e.g. 'eubc' or 'sabc'")
    grp.add_argument("--all", action="store_true", help="Process all tenants")
    args = parser.parse_args()

    with app.app_context():
        tenants = list(app.config.get("TENANTS", {}).keys())
        keys = tenants if args.all else [args.tenant]

        # Basic validation
        for k in keys:
            if k not in tenants:
                raise SystemExit(f"Unknown tenant '{k}'. Available: {tenants}")

        for k in keys:
            print(f"\n================= TENANT: {k} =================")
            with tenant_context(app, k):
                get_fitfiles_for_tenant(k)

if __name__ == "__main__":
    main()
