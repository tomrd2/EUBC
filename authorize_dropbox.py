#!/usr/bin/env python
"""
One-time helper: open Dropbox consent screen, return a
short-lived access-token **and** a long-lived refresh-token.

After you get the refresh-token, copy it into an env-var or
a secrets-manager and you never need to run this again.
"""
import webbrowser, dropbox

APP_KEY    = "fju7nouhxe4itm6"      # ← your app key
APP_SECRET = "gam0klqoamz6eha"      # ← your app secret

flow = dropbox.DropboxOAuth2FlowNoRedirect(
    consumer_key        = APP_KEY,
    consumer_secret     = APP_SECRET,
    token_access_type   = "offline",       # <— tells Dropbox we want refresh tokens
    scope               = [
        "files.metadata.read",
        "files.content.read",
        "sharing.read"
    ],
)

# 1️⃣ user authorises
auth_url = flow.start()
print("\nOpen the following URL, click **Allow**, then copy the code:\n")
print(auth_url, "\n")
webbrowser.open(auth_url)

# 2️⃣ paste the code
code = input("Paste authorization code here: ").strip()

# 3️⃣ exchange code → tokens
res = flow.finish(code)
print("\n=== COPY THESE VALUES ===")
print("ACCESS_TOKEN  :", res.access_token)
print("REFRESH_TOKEN :", res.refresh_token)
print("EXPIRES_AT    :", res.expires_at)     # datetime (UTC)
