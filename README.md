# mosaic-skills

Claude Code skills for working on MOSAIC (the CGIAR Multifunctional Landscapes metadata network).

| Skill | What it does |
|---|---|
| [`mosaic-landscape-profile`](skills/mosaic-landscape-profile/) | Create or change a landscape profile (the map, story and studies a living landscape shows under "Map visualization") without programming, check it, preview it and open the pull request to MOSAIC-mfl/catalog; when the profile needs something the website cannot draw yet, also the website change |

## Install

Clone this repository next to the other MOSAIC repositories (for example `D:\Code\Mosaic\mosaic-skills`,
beside `mosaic-standard`, `catalog`, `website`, `mosaic-api`) and link each skill once into Claude
Code's personal skills:

```sh
ln -s "$PWD/skills/mosaic-landscape-profile" ~/.claude/skills/        # macOS / Linux
```
```powershell
New-Item -ItemType Junction -Path $HOME\.claude\skills\mosaic-landscape-profile -Target skills\mosaic-landscape-profile   # Windows
```

How the pieces of MOSAIC fit together, and a demo of the skill: MOSAIC-mfl/mosaic-standard,
`development/`.

## Develop

```sh
pip install pyyaml pytest ruff
ruff check skills && ruff format --check skills
pytest -q skills/mosaic-landscape-profile/tests     # needs ../mosaic-standard (or MOSAIC_STANDARD); MOSAIC_CATALOG for the catalogue tests
```

Everything written to MOSAIC repositories is in English; the person using a skill can talk to Claude
in any language.
