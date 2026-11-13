"""Run the website locally with the profile as it is now (and any website change you are making).

    python web_preview.py --code SEN-FK                  # build, then print the commands to start it
    python web_preview.py --code SEN-FK --serve          # build and start it (Ctrl+C to stop)
    python web_preview.py --code SEN-FK --serve --data D:/data/profiles   # explorer data from a local folder

Needs setup.py --web. Steps (the same chain as the published site, all local):

1. builds the catalogue (records + landscape profiles, your uncommitted changes included) with the
   standard's tool into <work>/_web/dist;
2. harvests it with mosaic-api (only the MOSAIC source) and exports the static API to <work>/_web/site;
3. serves that API on http://127.0.0.1:8001 and runs the website (npm run dev) against it:
   the pages are http://localhost:4321/website/landscapes#<CODE>/map (the explorer's Map
   visualization) and http://localhost:4321/website/landscapes/<code>/map/ (full screen).

With --data, the explorer reads its files from <folder>/<CODE>/ (served on :8002) instead of the
profile's data roots: useful before the data is online. Files marked withheld are never requested.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import add_workspace_args, workspace

API_PORT = 8001
DATA_PORT = 8002

API_CONFIG = """# Written by web_preview.py: the MOSAIC catalogue built locally, nothing else.
standard: {dist}
state: {state}
export_dir: {site}
allowed_hosts: [mosaic-mfl.github.io]
max_download_mb: 50
sources:
  - id: mosaic
    name: MOSAIC
    type: mosaic_catalog
    translator: mosaic
    format: mosaic-v0.2
    location: {dist}
    homepage: https://mosaic-mfl.github.io/website/
    record_url_template: https://mosaic-mfl.github.io/website/catalogue/{{id}}/
http:
  cors_origins: [http://localhost:4321, http://127.0.0.1:4321]
  max_page_size: 100
  expose_emails: true
"""


def run(cmd: list[str], what: str, **kw: object) -> bool:
    res = subprocess.run(cmd, capture_output=True, text=True, **kw)  # type: ignore[call-overload]
    if res.returncode != 0:
        print(f"{what} failed:\n{(res.stderr or res.stdout)[-2000:]}")
        return False
    print(f"{what}: done")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", required=True)
    ap.add_argument("--serve", action="store_true", help="start the API and the website (blocks; Ctrl+C stops)")
    ap.add_argument("--data", type=Path, help="local folder with one sub-folder per landscape code (explorer data)")
    add_workspace_args(ap)
    args = ap.parse_args(argv)
    ws = workspace(args)
    if not ws.website or not ws.api:
        print("The website is not set up: run setup.py --web first.")
        return 2
    code = args.code.upper()
    out = ws.work / "_web"
    dist, site, state = out / "dist", out / "site", out / "state" / "snapshot.json"
    shutil.rmtree(site, ignore_errors=True)
    state.parent.mkdir(parents=True, exist_ok=True)
    cfg = out / "mosaic-api.yaml"
    cfg.write_text(
        API_CONFIG.format(dist=dist.as_posix(), state=state.as_posix(), site=site.as_posix()), encoding="utf-8"
    )
    py = sys.executable
    if not run(
        [py, "-m", "mosaic_catalog", "--catalog", str(ws.catalog), "build", "--out", str(dist)], "catalogue build"
    ):
        return 1
    env = {**os.environ, "MOSAIC_API_CONFIG": str(cfg)}
    if not run([py, "-m", "mosaic_api", "harvest"], "API harvest", env=env, cwd=ws.api):
        return 1
    if not run([py, "-m", "mosaic_api", "export"], "API export", env=env, cwd=ws.api):
        return 1
    if not (site / "v1" / "landscapes" / f"{code}.json").exists():
        print(f"Note: the export has no v1/landscapes/{code}.json (is the profile in {ws.catalog}/landscapes/{code}?).")
    front = ws.website / "frontend"
    serve = front / "scripts" / "serve-static-api.mjs"
    web_env = {"PUBLIC_MOSAIC_API_MODE": "static", "PUBLIC_MOSAIC_API_URL": f"http://127.0.0.1:{API_PORT}"}
    if args.data:
        web_env["PUBLIC_MOSAIC_PROFILE_DATA"] = f"http://127.0.0.1:{DATA_PORT}"
    page = (
        f"http://localhost:4321/website/landscapes#{code}/map"
        f" (full screen: http://localhost:4321/website/landscapes/{code.lower()}/map/)"
    )
    if not args.serve:
        print("\nTo start it (two terminals, or run them in the background):")
        print(f'  PORT={API_PORT} node "{serve}" "{site}"')
        if args.data:
            print(f'  PORT={DATA_PORT} node "{serve}" "{args.data}"')
        print(f'  cd "{front}" && ' + " ".join(f"{k}={v}" for k, v in web_env.items()) + " npm run dev")
        print(f"Then open {page}")
        return 0
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        print("Node.js is not installed (https://nodejs.org/).")
        return 2
    procs = [subprocess.Popen([node, str(serve), str(site)], env={**os.environ, "PORT": str(API_PORT)})]
    if args.data:
        procs.append(subprocess.Popen([node, str(serve), str(args.data)], env={**os.environ, "PORT": str(DATA_PORT)}))
    procs.append(subprocess.Popen([npm, "run", "dev"], cwd=front, env={**os.environ, **web_env}))
    print(f"\nOpen {page}  (Ctrl+C stops everything)")
    try:
        procs[-1].wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
