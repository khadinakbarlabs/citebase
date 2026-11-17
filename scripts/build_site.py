"""Build the Citebase website: landing page at the root, dashboard at /app/. Plain files for any static host.

  python3 scripts/build_site.py --site https://citebase.example [--out site-build] [--client-id ID]

The dashboard signs the visitor in with Apify (OAuth with PKCE) and reads the projects Citebase saved in the
visitor's own Apify account, by calling Citebase's `/run` endpoint (`get_history`) with the visitor's token.
There is no server and no database of our own. `oauth-client.json` is the page's public sign-in identity: Apify
reads it from the site (a client-ID metadata document). Pass --client-id only for a client registered by hand,
for example one with a localhost redirect for testing.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site"
API = "https://khadinakbar--citebase.apify.actor"
AUTHORIZE = "https://console.apify.com/authorize/oauth"
TOKEN = "https://console-backend.apify.com/oauth/apps/token"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src {api} https://console-backend.apify.com https://api.apify.com; base-uri 'none'; form-action 'none'")
HEADERS = {"trailingSlash": True, "headers": [{"source": "/(.*)", "headers": [
    {"key": "X-Content-Type-Options", "value": "nosniff"}, {"key": "Referrer-Policy", "value": "no-referrer"},
    {"key": "X-Frame-Options", "value": "DENY"},
    {"key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()"}]}]}


def build(site: str, out: Path, client_id: str | None = None, api: str = API) -> list[str]:
    site = site.rstrip("/")
    if not site.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise SystemExit("--site must be an https address (or http://localhost for a local test)")
    redirect = site + "/app/"
    client = {
        "client_id": f"{site}/oauth-client.json",
        "client_name": "Citebase dashboard",
        "client_uri": site,
        "logo_uri": f"{site}/favicon.svg",
        "redirect_uris": [redirect],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "full_api_access",
    }
    config = {"api": api, "oauth": {"authorize": AUTHORIZE, "token": TOKEN, "clientId": client_id or client["client_id"],
                                    "redirectUri": redirect, "scope": "full_api_access"}}
    (out / "app").mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def write(rel: str, text: str) -> None:
        (out / rel).write_text(text)
        written.append(rel)

    def copy(rel: str) -> None:
        shutil.copyfile(SRC / rel, out / rel)
        written.append(rel)

    write("index.html", (SRC / "landing.html").read_text().replace("__SITE__", site))
    copy("landing.css")
    copy("favicon.svg")
    page = (SRC / "app" / "index.html").read_text()
    if "<!--CSP-->" not in page:
        raise SystemExit("site/app/index.html lost its <!--CSP--> marker")
    write("app/index.html", page.replace("<!--CSP-->", f'<meta http-equiv="Content-Security-Policy" content="{CSP.format(api=api)}">'))
    for asset in sorted((SRC / "app").iterdir()):
        if asset.suffix in (".css", ".js"):
            copy(f"app/{asset.name}")
    write("app/config.js", "window.__CB=" + json.dumps(config, indent=1) + ";\n")
    write("oauth-client.json", json.dumps(client, indent=1) + "\n")
    write("vercel.json", json.dumps(HEADERS, indent=1) + "\n")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the Citebase landing page and dashboard.")
    ap.add_argument("--site", required=True, help="public address of the site, e.g. https://citebase.example")
    ap.add_argument("--out", default="site-build")
    ap.add_argument("--client-id", default=None)
    ap.add_argument("--api", default=API)
    a = ap.parse_args()
    made = build(a.site, Path(a.out), a.client_id, a.api)
    print("wrote", ", ".join(made), "to", a.out)
