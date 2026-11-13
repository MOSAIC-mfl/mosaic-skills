"""Run the website's own checks after changing it: types, lint, tests and the production build.

    python web_check.py              # all four
    python web_check.py --quick      # types and tests only

Needs setup.py --web. These are the checks the website's pull requests run (lint-frontend.yml and
the Pages build), so a change that passes here passes there. Exit code 1 when one fails.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import add_workspace_args, workspace

STEPS = [("types", "typecheck"), ("tests", "test"), ("lint", "lint"), ("build", "build")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="only types and tests")
    add_workspace_args(ap)
    args = ap.parse_args(argv)
    ws = workspace(args)
    if not ws.website:
        print("The website is not set up: run setup.py --web first.")
        return 2
    npm = shutil.which("npm")
    if not npm:
        print("npm not found: install Node.js 22.23.4+ (https://nodejs.org/).")
        return 2
    front = ws.website / "frontend"
    failed = []
    for label, script in STEPS[:2] if args.quick else STEPS:
        res = subprocess.run([npm, "run", script], cwd=front, capture_output=True, text=True)
        print(f"{'OK  ' if res.returncode == 0 else 'FAIL'} {label}")
        if res.returncode != 0:
            failed.append(label)
            print((res.stdout + res.stderr)[-3000:])
    print("\nResult: " + ("all checks pass" if not failed else f"failing: {', '.join(failed)}"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
