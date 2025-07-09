import io
import gzip
import boto3
import dropbox
import json, requests
from db import get_db_connection
from dropbox.files import SharedLink, FileMetadata, FolderMetadata

import logging

logging.getLogger().setLevel(logging.WARNING)
logger = logging.getLogger(__name__)



# AWS S3 config
S3_BUCKET = "eubctrackingdata"
S3_PREFIX = "fitfiles"  # base folder in S3
DROPBOX_APP_KEY = "fju7nouhxe4itm6"
DROPBOX_SECRET = "gam0klqoamz6eha"
REFRESH = "cKzc4xGTNOEAAAAAAAAAAQAcb5uxXhI4NlZnb_hvUIPNN6AFGkqeUx6NraDpgBsB"

# Dropbox client (unauthenticated works for public shared links)

dbx = dropbox.Dropbox(
    oauth2_refresh_token = REFRESH,
    app_key              = DROPBOX_APP_KEY,
    app_secret           = DROPBOX_SECRET,
)

# S3 client
s3 = boto3.client('s3')

# ---------- helpers ----------------------------------------------------------
def upload_to_s3(buf: io.BytesIO, key: str) -> None:
    
    buf.seek(0)
    s3.upload_fileobj(buf, S3_BUCKET, key)
    print(f"      ↳ s3://{S3_BUCKET}/{key}")


def link_root_path(link_url: str) -> str:
    """Return '' if the link points at the folder root, else the sub-path."""
    meta = dbx.sharing_get_shared_link_metadata(link_url)
    if not isinstance(meta, dropbox.sharing.FolderLinkMetadata):
        raise ValueError("Link is not a folder")
    return meta.path_lower.lstrip("/") if meta.path_lower else ""


def walk_folder(link_url: str, rel_path: str | None = None):
    """Yield (FileMetadata, path_inside_link) recursively."""
    if rel_path is None:
        rel_path = link_root_path(link_url)

    shared = SharedLink(url=link_url)
    res    = dbx.files_list_folder(path=rel_path, shared_link=shared)

    # ▶ DEBUG: how many items at this level?
    logger.debug("walk_folder → %s entries at path '%s'",
                 len(res.entries), rel_path or "<root>")

    for entry in res.entries:
        if isinstance(entry, FileMetadata):
            # ▶ DEBUG: every file discovered
            logger.debug("   · found file %s", entry.name)
            yield entry, rel_path
        elif isinstance(entry, FolderMetadata):
            sub = f"{rel_path}/{entry.name}" if rel_path else entry.name
            yield from walk_folder(link_url, sub)

    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        for entry in res.entries:
            if isinstance(entry, FileMetadata):
                logger.debug("   · found file %s", entry.name)
                yield entry, rel_path

# -----------------------------------------------------------------------------

def process_athlete(aid: str, link: str) -> None:
    """
    Walk the athlete’s shared-folder link, download every   *.fit   OR   *.fit.gz
    file, decompress if required, and upload the final  *.fit  to S3.

    S3 key pattern:  fitfiles/<Athlete_ID>/<filename>.fit
    """
    print(f"\n• Athlete {aid}")

    try:
        for entry, rel in walk_folder(link):
            name_low = entry.name.lower()
            is_gz  = name_low.endswith(".fit.gz") or name_low.endswith(".gz")
            is_fit = name_low.endswith(".fit")

            # skip anything that isn't fit-related
            if not (is_gz or is_fit):
                continue

            # Build the path inside the shared link (Dropbox needs the leading /)
            path = f"/{rel}/{entry.name}" if rel else f"/{entry.name}"
            print(f"   – downloading {path.lstrip('/')}")

            # -- download from Dropbox ----------------------------------------
            _, resp = dbx.sharing_get_shared_link_file(url=link, path=path)

            # -- decompress if it's a .gz -------------------------------------
            if is_gz:
                with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as gz:
                    file_bytes = gz.read()
                final_name = entry.name[:-3]        # strip ".gz"  →  *.fit
            else:
                file_bytes = resp.content
                final_name = entry.name             # already *.fit

            # -- upload to S3 --------------------------------------------------
            s3_key = f"{S3_PREFIX}/{aid}/{final_name}"
            print(f"   – uploading {final_name} to S3 path: {s3_key}")
            upload_to_s3(io.BytesIO(file_bytes), s3_key)

    except Exception as exc:
        print("   ! error:", exc)

def get_fitfiles():
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT Athlete_ID, DropBox
        FROM Athletes
        WHERE DropBox IS NOT NULL
    """)
    rows = cur.fetchall()
    conn.close()

    for row in rows:                       # rows likely dicts
        aid  = str(row["Athlete_ID"])
        link = row["DropBox"]
        print(f"Athlete {aid} → {link}")
        process_athlete(aid, link)


if __name__ == "__main__":
    get_fitfiles()