"""Write the title and description of the pull request for a landscape profile (in English).

    python prepare_pr.py --code SEN-FK              # writes <work>/SEN-FK/pr.md and prints it
    python prepare_pr.py --code SEN-FK --draft      # TODOs left on purpose: a draft pull request

The description lists what the profile contains, where its data is served, the licences and the
layers that are not catalogue records yet (for the reviewers), the result of the data check and of
the validator. SKILL.md then commits, pushes a branch and opens the pull request with it.

It gives no push commands while the validator finds errors, or while TODO placeholders are left
(exit code 3): a pull request must not put "TODO" texts on the website. With --draft, TODOs are
allowed and the pull request is opened as a draft, for the team to see work in progress.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    PROFILE_FILES,
    add_workspace_args,
    load_profile,
    load_yaml,
    md_table,
    standard_cmd,
    todos,
    tool_env,
    workspace,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", required=True)
    ap.add_argument("--change", default="", help="one line on what changed, for an edited profile")
    ap.add_argument("--depends", action="append", default=[], help="URL of a website or standard PR this one needs")
    ap.add_argument("--draft", action="store_true", help="TODO placeholders left on purpose: open a draft pull request")
    add_workspace_args(ap)
    args = ap.parse_args(argv)
    ws = workspace(args)
    code = args.code.upper()
    folder = ws.landscape_dir(code)
    if not (folder / "profile.yaml").exists():
        print(f"{code} has no profile.")
        return 2
    docs = load_profile(folder)
    prof, ex = docs["profile"], docs.get("explorer") or {}
    is_new = (
        subprocess.run(
            ["git", "-C", str(ws.catalog), "cat-file", "-e", f"HEAD:landscapes/{code}/profile.yaml"],
            capture_output=True,
        ).returncode
        != 0
    )
    title = f"{'Add' if is_new else 'Update'} the {code} landscape profile" + (
        f": {args.change}" if args.change else ""
    )
    lines = [f"## {prof.get('title')} ({code})", "", prof.get("summary", ""), ""]
    if args.change:
        lines += [f"**Change:** {args.change}", ""]
    origin = prof.get("origin") or {}
    if not is_new and origin.get("repository"):
        names = ", ".join(c.get("name", "") for c in prof.get("credits") or [] if c.get("name"))
        lines += [
            f"**Based on:** {origin['repository']}"
            + (f" ({names})" if names else "")
            + ". This change alters a page converted from that explorer; its author should know.",
            "",
        ]
    if args.depends:
        lines += [
            "**Depends on:** " + ", ".join(args.depends) + " (merge those first; until the website change is"
            " deployed the page skips what it cannot draw)",
            "",
        ]
    lines += [
        "**Sections:** "
        + ", ".join(f"{s.get('title') or s.get('id')} (`{s.get('kind')}`)" for s in prof.get("sections") or []),
        "",
    ]
    if ex:
        rows = [
            [
                o.get("title", ""),
                o.get("group", ""),
                f"`{o.get('kind')}`",
                f"`{(o.get('inspect') or {}).get('kind', '—')}`",
            ]
            for o in ex.get("overlays") or []
        ]
        lines += ["### Map explorer layers", "", md_table(rows, ["layer", "group", "kind", "click"]), ""]
        lines += [
            "**Data served from:** "
            + ", ".join(f"`{v}`" for v in dict.fromkeys((ex.get("data") or {}).get("roots", {}).values())),
            "",
        ]
        if docs.get("story"):
            lines.append(f"**Story:** {len(docs['story'].get('chapters') or [])} chapters")
        if docs.get("studies"):
            lines.append(f"**Study cards:** {len(docs['studies'].get('cards') or [])}")
        lines.append("")
    sources = (docs.get("sources") or {}).get("layers") or []
    if sources:
        rows = [[s.get("title", ""), s.get("licence", "—"), s.get("record") or "not registered"] for s in sources]
        lines += [
            "### Licences and catalogue records (for review)",
            "",
            md_table(rows, ["layer", "licence as stated by the source", "record"]),
            "",
        ]
    check = ws.work_dir(code) / "data-check.json"
    if check.exists():
        files = json.loads(check.read_text(encoding="utf-8"))["files"]
        bad = [f for f in files if not f.get("ok") and not f.get("unreachable")]
        unchecked = [f for f in files if f.get("unreachable")]
        checked = len(files) - len(unchecked)
        lines += [
            f"**Data check:** {checked - len(bad)} of {checked} files readable by the website "
            "(HTTPS, CORS, byte ranges)."
            + (
                f" {len(unchecked)} could not be checked from the author's computer (its network did not reach"
                " the host); the reviewers' check or the preview covers them."
                if unchecked
                else ""
            )
        ]
        lines += [f"- `{f['path']}`: {f.get('problem')}" for f in bad[:15]]
        lines.append("")
    res = subprocess.run(
        standard_cmd(ws, "validate-landscapes", code, "-v"), capture_output=True, text=True, env=tool_env(ws)
    )
    verdict = next(
        (ln.strip() for ln in res.stdout.splitlines() if f" {code} " in ln and ln.startswith(("OK", "ERR"))), "not run"
    )
    left = sum(len(todos(load_yaml(folder / n))) for n in PROFILE_FILES if (folder / n).exists())
    lines += [f"**Validator:** `{verdict}` · TODO left: {left}", ""]
    lines += [
        "### Checklist for the reviewer",
        "",
        "- [ ] Texts are the data authors' (nothing invented); numbers cite their source",
        "- [ ] Licences allow showing each layer on the MOSAIC website",
        "- [ ] Data files are served over HTTPS with CORS and byte ranges",
        "- [ ] The page reads well (preview attached or described)",
        "",
        "Prepared with the mosaic-landscape-profile skill (mosaic-standard).",
    ]
    body = "\n".join(lines) + "\n"
    out = ws.work_dir(code) / "pr.md"
    out.write_text(f"{title}\n\n{body}", encoding="utf-8")
    (ws.work_dir(code) / "pr-title.txt").write_text(title + "\n", encoding="utf-8")
    (ws.work_dir(code) / "pr-body.md").write_text(body, encoding="utf-8")
    print(f"Title: {title}\n\n{body}\nSaved: {out}")
    if verdict.startswith("ERR") or verdict == "not run":
        print("\nNo pull request yet: the validator does not pass. Run validate.py and fix what it says.")
        return 3
    if left and not args.draft:
        print(
            f"\nNo pull request yet: {left} TODO placeholders are left, and the website would show them."
            " Fill them in (validate.py lists them), or, if the team should see work in progress, run this"
            " again with --draft."
        )
        return 3
    # one branch name per change, so two edits in a row do not collide
    topic = re.sub(r"[^a-z0-9]+", "-", (args.change or ("profile" if is_new else "update")).lower()).strip("-")
    branch = f"landscape/{code.lower()}-{'-'.join(topic.split('-')[:5]) or 'update'}"
    draft = " --draft" if args.draft else ""
    commands = [
        f'cd "{ws.catalog}"',
        f"git switch -c {branch}",
        f"git add landscapes/{code}",
        f'git commit -m "{title}"',
        "git push -u origin HEAD",
        f'gh pr create{draft} --base {ws.base} --title "{title}" --body-file "{ws.work_dir(code) / "pr-body.md"}"',
    ]
    print(
        ("\nA draft pull request: the TODOs stay until the person fills them in.\n" if args.draft else "")
        + "\nCommands (after the person agrees):\n"
        + "\n".join(commands)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
