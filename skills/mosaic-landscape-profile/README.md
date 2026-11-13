# mosaic-landscape-profile (Claude Code skill)

Lets anyone, with no programming, create or change a MOSAIC landscape profile with Claude Code and
open the pull request to the catalogue; when the profile needs something the website cannot draw
yet (a kind of layer, a click, a chart, a button, a pop-up), Claude also makes that website change
and opens its pull request. The person talks with Claude in any language; everything written to the
repositories is in English.

## Use it

It lives in the `mosaic-skills` repository, `skills/mosaic-landscape-profile/`. Clone it next to the
other MOSAIC repositories and link it once as a personal skill of Claude Code, from that checkout:

```sh
ln -s "$PWD/skills/mosaic-landscape-profile" ~/.claude/skills/         # macOS / Linux
# Windows (PowerShell, from mosaic-skills):
#   New-Item -ItemType Junction -Path $HOME\.claude\skills\mosaic-landscape-profile -Target skills\mosaic-landscape-profile
```

Then open Claude Code anywhere and ask, for example *"I want a landscape page for Fatick, Senegal,
like the Ucayali one"* or *"Quita la capa de incendios del perfil de Lake Victoria"*. Claude runs
`scripts/setup.py` first: it uses or clones mosaic-standard and the catalogue (plus the website and
mosaic-api when needed) next to the mosaic-skills checkout.

Requirements: git, Python 3.10+, the GitHub CLI (`gh auth login`); Node.js 22 only for website changes.

## Contents

```
SKILL.md                 the workflow Claude follows
scripts/
  setup.py               workspace: standard + catalogue (--web: website + API), validator installed
  new_profile.py         a new profile from a template or like an existing one (TODO placeholders + checklist)
  inventory.py           reads an explorer repository (read only) and suggests modules
  check_data.py          HTTPS, CORS and byte ranges of every data file
  edit_profile.py        list, remove-overlay (with every reference), set-root
  validate.py            the standard's validator, each problem explained
  preview.py             one-page HTML review of the profile
  web_check.py           the website's checks (types, tests, lint, build) after a website change
  web_preview.py         the real page locally: catalogue build -> API export -> website dev server
  prepare_pr.py          pull request title, body and commands
templates/               the files new_profile.py starts from
references/              modules, web-modules, data hosting, recipes, errors, glossary
tests/                   pytest suite of the scripts
```

Tests (need a mosaic-standard checkout; the catalogue is optional):

```sh
MOSAIC_STANDARD=~/mosaic/mosaic-standard MOSAIC_CATALOG=~/mosaic/catalog python -m pytest -q tests
```
