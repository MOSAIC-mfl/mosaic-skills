"""Prepare the workspace: the MOSAIC standard and the catalogue, ready to write a landscape profile.

    python setup.py                          # mosaic-standard and the catalogue next to mosaic-skills
                                             # (skill uploaded to Claude: in the current folder)
    python setup.py --workspace D:/Code/Mosaic
    python setup.py --standard D:/Code/Mosaic/mosaic-standard --catalog D:/Code/Mosaic/_publish/catalog
    python setup.py --web                    # also the website and the API, for a profile that needs a new module

What it does:
1. uses (or clones) MOSAIC-mfl/mosaic-standard and MOSAIC-mfl/catalog next to the mosaic-skills
   checkout (or the checkouts you name); when they have no local changes, brings them up to date;
2. puts the catalogue on main (the branch that holds the landscape profiles), unless you are on
   your own branch that has them;
3. installs the standard's tool for this Python (pip install -e), so the validator runs;
4. writes the paths to ~/.mosaic/workspace.json for the other scripts;
5. checks git and the GitHub CLI (gh) for the pull request at the end.

With --web (only when a profile needs something the website cannot draw yet): also clones
MOSAIC-mfl/website and MOSAIC-mfl/mosaic-api, puts the website on the branch with the map explorer
(main), installs the API (pip) and, when node_modules is
missing, the website (npm ci), so web_preview.py and web_check.py can run.

It never changes a file you edited and never pushes anything.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CONFIG, default_workspace

STANDARD_REPO = "https://github.com/MOSAIC-mfl/mosaic-standard.git"
CATALOG_REPO = "https://github.com/MOSAIC-mfl/catalog.git"
WEBSITE_REPO = "https://github.com/MOSAIC-mfl/website.git"
API_REPO = "https://github.com/MOSAIC-mfl/mosaic-api.git"
EXPLORER = "frontend/src/features/explorer"


def git(repo: Path, *args: str, check: bool = True) -> str:
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} in {repo}: {res.stderr.strip()}")
    return res.stdout.strip()


def ensure_clone(path: Path, url: str) -> str:
    if (path / ".git").exists():
        return "found"
    path.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(["git", "clone", "--quiet", url, str(path)], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"git clone {url}: {res.stderr.strip()}")
    return "cloned"


def update(path: Path) -> str:
    if git(path, "status", "--porcelain"):
        return "has local changes: not updated"
    git(path, "fetch", "--quiet", "origin", check=False)
    branch = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    if not git(path, "ls-remote", "--heads", "origin", branch, check=False):
        return f"on {branch} (not on GitHub yet)"
    res = subprocess.run(
        ["git", "-C", str(path), "merge", "--ff-only", "--quiet", f"origin/{branch}"], capture_output=True, text=True
    )
    return (
        f"up to date on {branch}"
        if res.returncode == 0
        else f"on {branch}: could not fast-forward ({res.stderr.strip()[:80]})"
    )


def base_branch(path: Path) -> str:
    """The catalogue branch pull requests go to."""
    return "main"


def catalog_branch(path: Path, base: str) -> str:
    """Stay on a branch that has the profiles (the base or your own landscape/... branch); else switch to the base."""
    if (path / "landscapes").is_dir() and not (path / "mosaic.config.yaml").exists():
        return git(path, "rev-parse", "--abbrev-ref", "HEAD")
    if git(path, "status", "--porcelain"):
        raise RuntimeError(f"{path} has local changes and is not on the branch with landscapes/")
    git(path, "fetch", "--quiet", "origin", base, check=False)
    git(path, "checkout", "--quiet", base)
    return base


def website_base(path: Path) -> str:
    """The website branch pull requests go to."""
    return "main"


def website_branch(path: Path, base: str) -> str:
    if (path / EXPLORER).is_dir():
        return git(path, "rev-parse", "--abbrev-ref", "HEAD")
    if git(path, "status", "--porcelain"):
        raise RuntimeError(f"{path} has local changes and is not on the branch with the map explorer")
    git(path, "fetch", "--quiet", "origin", base, check=False)
    git(path, "checkout", "--quiet", base)
    return base


def node_check(website: Path) -> str:
    """The website names its Node.js version in .nvmrc; another major version may build differently."""
    want = (website / ".nvmrc").read_text(encoding="utf-8").strip() if (website / ".nvmrc").exists() else ""
    node = shutil.which("node")
    if not node:
        return f"Node.js not found: install {want or '22'} (https://nodejs.org/) to preview the website"
    have = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    if want and have.split(".")[0] != want.split(".")[0]:
        return (
            f"Node.js {have} found; the website uses {want}. It may work, but if npm ci or the preview fails,"
            f" install Node {want.split('.')[0]} (nvm-windows / nvm, or nodejs.org)"
        )
    return f"Node.js {have} (the website uses {want or 'Node 22'})"


def setup_web(ws: Path, args: argparse.Namespace, report: list[str]) -> dict[str, str]:
    website = (args.website or ws / "website").expanduser().resolve()
    api = (args.api or ws / "mosaic-api").expanduser().resolve()
    report.append(f"website: {website} ({ensure_clone(website, WEBSITE_REPO)}, {update(website)})")
    report.append(f"API: {api} ({ensure_clone(api, API_REPO)}, {update(api)})")
    base = website_base(website)
    report.append(f"website: working on branch {website_branch(website, base)}; pull requests go to {base}")
    if not args.no_install:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-e", str(api)], capture_output=True, text=True
        )
        report.append("API installed" if res.returncode == 0 else f"API install failed: {res.stderr.strip()[-300:]}")
        npm = shutil.which("npm")
        report.append(node_check(website))
        if (website / "frontend" / "node_modules").is_dir():
            report.append("website dependencies already installed (node_modules kept)")
        elif not npm:
            report.append(
                "npm not found: install Node.js 22.23.4+ (https://nodejs.org/) to preview and test the website"
            )
        else:
            res = subprocess.run(
                [npm, "ci", "--no-audit", "--no-fund"], cwd=website / "frontend", capture_output=True, text=True
            )
            report.append(
                "website dependencies installed (npm ci)"
                if res.returncode == 0
                else f"npm ci failed: {res.stderr.strip()[-300:]}"
            )
    return {"website": str(website), "api": str(api), "website_base": base}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--workspace",
        type=Path,
        default=default_workspace(),
        help="where to clone (default: next to mosaic-skills; for a skill uploaded to Claude, the current folder)",
    )
    ap.add_argument("--standard", type=Path, help="an existing checkout of mosaic-standard")
    ap.add_argument("--catalog", type=Path, help="an existing checkout of the catalogue")
    ap.add_argument("--no-install", action="store_true", help="do not install anything (pip, npm)")
    ap.add_argument(
        "--web", action="store_true", help="also the website and the API (a profile that needs a new module)"
    )
    ap.add_argument("--website", type=Path, help="an existing checkout of the website (with --web)")
    ap.add_argument("--api", type=Path, help="an existing checkout of mosaic-api (with --web)")
    args = ap.parse_args(argv)

    if not shutil.which("git"):
        print("git is not installed: install it from https://git-scm.com/ and run this again.")
        return 2
    ws = args.workspace.expanduser().resolve()
    standard = (args.standard or ws / "mosaic-standard").expanduser().resolve()
    catalog = (args.catalog or ws / "catalog").expanduser().resolve()
    report: list[str] = []
    try:
        report.append(f"standard: {standard} ({ensure_clone(standard, STANDARD_REPO)}, {update(standard)})")
        report.append(f"catalogue: {catalog} ({ensure_clone(catalog, CATALOG_REPO)}, {update(catalog)})")
        base = base_branch(catalog)
        branch = catalog_branch(catalog, base)
        report.append(f"catalogue: working on branch {branch}; pull requests go to {base}")
        web = setup_web(ws, args, report) if args.web else {}
    except RuntimeError as err:
        print(f"Setup stopped: {err}")
        return 1

    if not args.no_install:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-e", str(standard)], capture_output=True, text=True
        )
        if res.returncode != 0:
            print(f"pip install failed:\n{res.stderr[-1500:]}")
            return 1
        report.append(f"validator installed for {sys.executable}")

    work = catalog.parent / "work"
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    saved = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    saved.update(
        {"standard": str(standard), "catalog": str(catalog), "work": str(work), "base": base, "python": sys.executable},
        **web,
    )
    CONFIG.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    report.append(f"workspace saved in {CONFIG}; files made for you go to {work}")

    gh = shutil.which("gh")
    if not gh:
        report.append("GitHub CLI (gh) not found: the pull request will have to be opened on github.com (see SKILL.md)")
    else:
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        report.append("gh: signed in" if auth.returncode == 0 else "gh: not signed in (run: gh auth login)")
    landscapes = (
        sorted(p.name for p in (catalog / "landscapes").iterdir() if p.is_dir())
        if (catalog / "landscapes").is_dir()
        else []
    )
    report.append(f"curated profiles in the catalogue: {', '.join(landscapes) or 'none'}")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
