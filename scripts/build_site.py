"""Build the Citebase website, dashboard and same-origin Vercel sign-in function.

  python3 scripts/build_site.py --site https://citebase.example [--out site-build] [--client-id ID]

The dashboard signs the visitor in with Apify (OAuth with PKCE) and reads the projects Citebase saved in the
visitor's own Apify account, by calling Citebase's `/run` endpoint (`get_history`) with the visitor's token.
The sign-in function seals credentials in an HttpOnly cookie using CITEBASE_SESSION_KEY at runtime.
Apify reads oauth-client.json from the site. Pass --client-id for a client registered by hand.
For a loopback static server without Vercel functions, --local-static keeps sign-in in the current tab.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site"
API = "https://khadinakbar--citebase.apify.actor"
AUTHORIZE = "https://console.apify.com/authorize/oauth"
TOKEN = "https://console-backend.apify.com/oauth/apps/token"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
       "connect-src 'self' {api} {token_source}https://api.apify.com; base-uri 'none'; form-action 'none'")
HEADERS = {"trailingSlash": True, "headers": [{"source": "/(.*)", "headers": [
    {"key": "X-Content-Type-Options", "value": "nosniff"}, {"key": "Referrer-Policy", "value": "no-referrer"},
    {"key": "X-Frame-Options", "value": "DENY"},
    {"key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()"}]}]}


def build(site: str, out: Path, client_id: str | None = None, api: str = API, *, history_only: bool = False,
          local_static: bool = False) -> list[str]:
    site = site.rstrip("/")
    address = urlsplit(site)
    loopback = address.hostname in ("127.0.0.1", "localhost", "::1")
    if (not address.hostname or address.username is not None or address.password is not None
            or address.path or address.query or address.fragment
            or (address.scheme != "https" and not (loopback and address.scheme == "http"))):
        raise SystemExit("--site must be an https origin (or a loopback http origin for local tests)")
    if local_static and not loopback:
        raise SystemExit("--local-static is limited to loopback development sites")
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
    public_id = client_id or client["client_id"]
    config = {"api": api, "oauth": {"authorize": AUTHORIZE, "token": TOKEN, "clientId": public_id,
                                    "redirectUri": redirect, "scope": "full_api_access", "session": not local_static}}
    if history_only:
        config["projectWork"] = False
    (out / "app").mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def write(rel: str, text: str) -> None:
        (out / rel).write_text(text)
        written.append(rel)

    def copy(rel: str) -> None:
        shutil.copyfile(SRC / rel, out / rel)
        written.append(rel)

    auth_start = "app/?signin=1" if local_static else "/api/session/?start"
    write("index.html", (SRC / "landing.html").read_text().replace("__SITE__", site).replace("__AUTH_START__", auth_start))
    copy("landing.css")
    copy("landing.js")
    copy("favicon.svg")
    copy("appearance.css")
    copy("appearance.js")
    (out / "assets").mkdir(exist_ok=True)
    for name in ("geist-latin.woff2", "manrope-latin.woff2", "icons.svg",
                 "geist-license.txt", "manrope-license.txt", "lucide-license.txt"):
        copy(f"assets/{name}")
    page = (SRC / "app" / "index.html").read_text()
    if "<!--CSP-->" not in page:
        raise SystemExit("site/app/index.html lost its <!--CSP--> marker")
    policy = CSP.format(api=api, token_source="https://console-backend.apify.com " if local_static else "")
    write("app/index.html", page.replace("<!--CSP-->", f'<meta http-equiv="Content-Security-Policy" content="{policy}">'))
    for asset in sorted((SRC / "app").iterdir()):
        if asset.suffix in (".css", ".js"):
            copy(f"app/{asset.name}")
    write("app/config.js", "window.__CB=" + json.dumps(config, indent=1) + ";\n")
    function = SRC / "api" / "session.js"
    if not local_static:
        (out / "api").mkdir(exist_ok=True)
        public_settings = {"origin": site, "clientId": public_id, "redirectUri": redirect}
        write("api/session.js", function.read_text().replace("/* CITEBASE_OAUTH */ null", json.dumps(public_settings)))
    elif (out / "api/session.js").exists():
        (out / "api/session.js").unlink()
    hosting = dict(HEADERS)
    hosting["redirects"] = [{"source": "/landing.html", "destination": "/", "permanent": True}]
    if not local_static and not history_only:
        (out / "api" / "_lib").mkdir(parents=True, exist_ok=True)
        for name in ("api/_lib/balance.js", "api/_lib/google-reporting.js", "api/_lib/google-mail.js", "api/actor.js", "api/google.js"):
            copy(name)
        hosting["functions"] = {name: {"maxDuration": 300} for name in ("api/actor.js", "api/google.js")}
    else:
        for name in ("api/actor.js", "api/google.js", "api/_lib/balance.js", "api/_lib/google-reporting.js", "api/_lib/google-mail.js"):
            (out / name).unlink(missing_ok=True)
    write("oauth-client.json", json.dumps(client, indent=1) + "\n")
    write("vercel.json", json.dumps(hosting, indent=1) + "\n")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the Citebase landing page and dashboard.")
    ap.add_argument("--site", required=True, help="public address of the site, e.g. https://citebase.example")
    ap.add_argument("--out", default="site-build")
    ap.add_argument("--client-id", default=None)
    ap.add_argument("--api", default=API)
    ap.add_argument("--local-static", action="store_true", help="Use tab-only OAuth on a loopback static file server.")
    ap.add_argument("--history-only", action="store_true", help="Use the published project history API for signed-in accounts until the Actor supports project_work.")
    a = ap.parse_args()
    made = build(a.site, Path(a.out), a.client_id, a.api, history_only=a.history_only, local_static=a.local_static)
    print("wrote", ", ".join(made), "to", a.out)
