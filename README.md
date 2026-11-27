# mosaic-skills

Skills for Claude to work on MOSAIC (the CGIAR Multifunctional Landscapes metadata network). They
work in the Claude app (desktop or claude.ai) and in Claude Code.

| Skill | What it does |
|---|---|
| [`mosaic-contribute`](skills/mosaic-contribute/) | Add a folder of datasets in any format to the catalogue with no Excel and no GitHub form: a script reads the files, Claude asks only what the files cannot say (who made the data, the licence, where to get it, a short description), checks the records and sends them as one pull request to MOSAIC-mfl/catalog, or as a zip for the MOSAIC team. Python 3.8+ only; also works with other AI assistants and by hand (see its README) |
| [`mosaic-landscape-profile`](skills/mosaic-landscape-profile/) | Create or change a landscape profile (the map, story and studies a living landscape shows under "Map visualization") without programming, check it, preview it and open the pull request to MOSAIC-mfl/catalog; when the profile needs something the website cannot draw yet, also the website change |

## Use it in the Claude app (desktop or claude.ai)

Most people use this way. You talk to Claude; it asks what the page should say and show, block by
block, writes the files, checks them and prepares the pull request.

### Install (once)

1. Download this repository: **Code → Download ZIP** on GitHub, or `git clone` it.
2. Make a ZIP of the skill folder only, with the folder itself at the top of the ZIP:
   ```powershell
   # Windows, in the mosaic-skills folder
   Compress-Archive -Path skills\mosaic-landscape-profile -DestinationPath mosaic-landscape-profile.zip
   ```
   ```sh
   # macOS / Linux
   cd skills && zip -r ../mosaic-landscape-profile.zip mosaic-landscape-profile
   ```
3. In Claude: **Settings → Capabilities → Skills → Upload skill**, and choose the ZIP. Code
   execution must be on (same page). If you do not see Skills, your organisation's admin has to
   turn them on.
4. When this repository changes, make the ZIP again and upload it to replace the old one.

### Work with it

- **Desktop app, with a folder (recommended).** Start a task and connect the folder where you keep
  the MOSAIC work (for example `D:\Code\Mosaic`). Say which folder to use as the workspace in your
  first message; Claude clones `mosaic-standard` and `catalog` there (with `--web`, also `website`
  and `mosaic-api`) and works on a branch.
- **claude.ai in the browser.** It works when code execution can reach github.com: the files stay
  in Claude's own environment, and you download them or open the pull request on github.com.

Good to know in the app:

- Claude may run the commands in an environment of its own that only sees your folder. Creating,
  editing and checking the profile work there. **The map preview runs on your computer**: Claude
  gives you two or three commands for your terminal (PowerShell on Windows). You need Python 3.10+
  and Node.js 22 for that.
- For the pull request Claude prepares the text and the commands; you run the push (or paste the
  text on github.com) if Claude cannot. Nothing is pushed to `main`.

## Use it in Claude Code

Clone this repository next to the other MOSAIC repositories (for example `D:\Code\Mosaic\mosaic-skills`,
beside `mosaic-standard`, `catalog`, `website`, `mosaic-api`) and link the skill once into Claude
Code's personal skills:

```sh
ln -s "$PWD/skills/mosaic-landscape-profile" ~/.claude/skills/        # macOS / Linux
```
```powershell
New-Item -ItemType Junction -Path $HOME\.claude\skills\mosaic-landscape-profile -Target "$PWD\skills\mosaic-landscape-profile"   # Windows
```

Then start `claude` in that folder and ask, as in the examples below. In Claude Code the commands
run on your computer, so the map preview opens at `http://localhost:4321` directly.

## Examples of what to ask

Write in your own words and language; Claude asks for whatever is missing, one block at a time.

- *"I want a page for Fatick, Senegal, like the Ucayali one, with land cover, rainfall and drought.
  The data is not online yet."* → it starts the page, explains where the files will go
  (MOSAIC-CGIAR on Hugging Face, `landscape-data` on GitHub) and what to send when they are ready.
- *"In the Ucayali map, the protected areas legend should say 'Protected areas (ANP & ACR)'. I want
  to see it on the map before sending it."* → one change, the check, the local preview, the pull
  request text.
- *"Remove the active fires layer from Lake Victoria."* → removes it with everything that used it
  (story chapters, study cards, sources) and tells you what changed.
- *"Andrés moved the small files to https://mosaic-mfl.github.io/landscape-data/PER-PCL/. Update the
  profile and check the files load."* → changes where the data is read from and checks every file.
- *"What can a landscape page have, and what do you need from me for each part?"* → the menu of
  pieces (layers, clicks, base map, switches, panels, story, study cards, sources).
- *"Add a story to the Central India page: four chapters on land cover change. Ask me for each
  chapter."* → chapter by chapter: text, layer, chart, and where each number comes from.
- *"I have my own explorer in a GitHub repository; turn it into a MOSAIC profile."* → reads it
  without changing it and suggests how each layer maps to the website.
- *"Add the datasets in D:\Data\Ucayali to MOSAIC."* (`mosaic-contribute`) → lists what each file
  holds, asks one round of questions, and sends the records once you agree.

## Remove it

- Claude app: **Settings → Capabilities → Skills**, delete the skill.
- Claude Code: delete the link `~/.claude/skills/mosaic-landscape-profile` (only the link; the
  repository stays).

How the pieces of MOSAIC fit together, and a demo of the skill: MOSAIC-mfl/mosaic-standard,
`development/`.

## Develop

```sh
pip install pyyaml pytest ruff
ruff check skills && ruff format --check skills
pytest -q skills/mosaic-landscape-profile/tests     # needs ../mosaic-standard (or MOSAIC_STANDARD); MOSAIC_CATALOG for the catalogue tests
pytest -q skills/mosaic-contribute/tests            # standalone; with mosaic-standard installed it also runs the MOSAIC validator
```

Everything written to MOSAIC repositories is in English; the person using a skill can talk to Claude
in any language.
