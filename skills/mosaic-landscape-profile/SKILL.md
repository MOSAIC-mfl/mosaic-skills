---
name: mosaic-landscape-profile
description: Create or change a MOSAIC landscape profile (the page of a landscape on the MOSAIC website, with its map explorer, story and study cards) and open the pull requests, to the catalogue and, only when the profile needs something new, to the website. Use when someone wants a new landscape page, a page like an existing one (KEN-LVB, PER-PCL), to add or remove map layers, to move a profile's data, a new element in a landscape page or its map (a kind of layer, a click, a button, a pop-up), or to turn their own explorer into a MOSAIC profile. No programming needed from the person.
---

# MOSAIC landscape profile

You help a person who may not program to write a landscape profile for the MOSAIC website and to
send it as a pull request to the catalogue (`MOSAIC-mfl/catalog`, folder `landscapes/<CODE>/`).
When the profile needs something the website cannot draw or do yet (a new kind of layer, a click,
a chart, a button, a pop-up) or a change to an existing module, you also make that website change
and send it as a pull request to `MOSAIC-mfl/website`. You do the technical work; the person
decides what the page says and shows.

## Rules

1. **Language.** Talk with the person in their language. Everything written into the repositories
   (YAML texts, comments, commit messages, the pull request) is in **English**.
2. **Never invent content, and never fill a field just to fill it.** Titles, summaries, story
   text, study findings, numbers, sources, licences, citations and data locations come from the
   person or from documents they give you. When something is missing, leave the `TODO: …`
   placeholder and ask. Do not "improve" a finding or a number. Do not copy values from another
   profile unless the person asks for that value from that profile (then say what you copied). Never
   copy story chapters or study cards from another landscape: they are about that landscape. A
   field filled by guesswork is worse than a TODO, because nobody will look for it later.
3. **Never push to `main`** and never merge, in any repository. Work on a branch
   `landscape/<code>-<short-topic>` and open a pull request; the MOSAIC team reviews it.
4. **The data stays where it is served.** Profiles only say where each file lives. Never commit
   tiles, GeoTIFFs or other data files to the catalogue.
5. **Configuration first, website code only when needed.** Almost everything is configuration of
   existing modules (`references/modules.md`). Change the website only when the profile needs
   something no module does, or the person asks to change how a module behaves
   (`references/web-modules.md`, step 5b). Never change the website when configuration is enough.
6. In the catalogue, change only `landscapes/<CODE>/` (not other landscapes, not the records). In
   the website, change only what the new or edited module needs, keeping the MOSAIC look and every
   other profile working as before.
7. Run every script below; do not reimplement what a script does. Show the person the results in
   plain words (not raw YAML unless they ask).

## Where things are

The skill lives in the `mosaic-skills` repository, `skills/mosaic-landscape-profile/` (linked into
`~/.claude/skills/` as its README says). Call that folder `SKILL_DIR`: the folder of
this SKILL.md, with `scripts/`, `templates/` and `references/` next to it.

`setup.py` uses or clones what the work happens in (mosaic-standard and the catalogue; with `--web`
also the website and mosaic-api) next to the mosaic-skills checkout. Never write profile files or
work files inside mosaic-skills: they go to the catalogue (`landscapes/<CODE>/`) and to
`<workspace>/work/<CODE>/`.

**Where the commands run.** The scripts, the preview servers and `localhost` must be on the
person's own computer. If your shell is not that computer (for example a cloud or virtual machine
that only sees their folder: paths like `/sessions/…` or `~/mnt/…`), a server you start there is not
reachable at their `localhost`, `npm ci` may fail on the shared folder, and what `setup.py` installs
stays on your side. Then do the file work (create, edit, validate) where you are, and give the person
the commands to run in their own terminal for `setup.py --web` and `web_preview.py --serve`, in
PowerShell form on Windows. The scripts find the checkouts next to mosaic-skills, so they work on the
person's computer even when `setup.py` was run elsewhere.

Needs: git, Python 3.10+, and the GitHub CLI (`gh`, logged in with `gh auth login`) for the pull
request; Node.js 22 only for a website change. On Windows use `python`; elsewhere `python3` may be
the name.

## Block by block (how to work with the person)

Filling in a profile is an interview, not a form you complete on your own:

1. After step 2, tell the person the plan: which blocks their profile needs, out of these, and how
   many: **the page** (summary, explorer name, credits) · **where the data is served** · **the base
   map** · **the layers** (one at a time: name and group, file, legend, click, source) · **the story**
   (chapter by chapter) · **the study cards** (one at a time) · then **check and preview** and **the
   pull request**. Only the blocks of the pieces they chose (`references/pieces.md`).
2. Work on one block at a time, and say where you are ("block 3 of 6: the layers"). Ask only that
   block's questions, a few at a time, and wait for the answers. Do not write the next block while
   waiting.
3. Write only what the person answered. What they skip or do not know stays `TODO`; say so.
4. After each block: run `validate.py --code <CODE> --allow-todo`, then tell the person in plain
   words what was written, what is still open (validate lists the TODOs by block) and what the next
   block is. Ask before moving on.
5. If the person asks for practice or made-up values, confirm it once, use them only for the fields
   they named, and list them at the end so they can be replaced.

## Workflow

### 1. Set up (once per computer, then at the start of each session)

```sh
python SKILL_DIR/scripts/setup.py                 # clones/updates next to the mosaic-skills folder
# or, with existing checkouts:
python SKILL_DIR/scripts/setup.py --standard <path to mosaic-standard> --catalog <path to catalog>
```

It installs the validator, puts the catalogue on the branch that holds `landscapes/`, and saves the
paths, so the other scripts need no paths. Fix what it reports (for example `gh auth login`) before
going on. The files made for the person (checklist, preview, PR text) go to `<workspace>/work/<CODE>/`.

### 2. Understand what the person wants

Ask only what you need, one question at a time. Decide which case it is
(`references/recipes.md` has each one step by step):

| Case | The person says | Start with |
|---|---|---|
| A | "the same as KEN-LVB / PER-PCL, for my landscape" | `new_profile.py --like` |
| B | "like that one, but only these layers / with changes" | `new_profile.py --like … --only …`, then edits |
| C | "a new page" (with or without a map) | `new_profile.py --template default` or `--template explorer` |
| C2 | "a page for my landscape", but its data is not online yet | `new_profile.py --template default` (recipes, C2) |
| D | "change the existing profile" (add/remove a layer, move data, fix texts) | `edit_profile.py`, direct edits |
| E | the landscape code does not exist yet | a request to mosaic-standard first (see recipes) |
| F | something the page or the map cannot do yet (a kind of layer, a click, a button, a pop-up) | step 5b: a website change, then the profile |

When the person wants a page "like KEN-LVB / PER-PCL" or asks what a profile can have, show them
the menu in `references/pieces.md` (layers, clicks, base map, switches, panels, story, study cards,
sources) and ask which pieces they want; then ask, one at a time, only for what those pieces need.

Also find out: the landscape code (`vocab/landscapes.json` in the standard lists the 11 codes), where
the data files are or will be served, whether there is an existing explorer repository to convert,
and who should be credited.

If the person has their own explorer (a repository with `data/meta/layers.json`, like the Lake
Victoria and Ucayali explorers), run the inventory first; it reads the repository without changing it:

```sh
python SKILL_DIR/scripts/inventory.py --source <path to their explorer> --code <CODE>
```

It writes `inventory.md` with each layer, its files and the suggested module and click. Go through
it with the person.

### 3. Create the profile

```sh
python SKILL_DIR/scripts/new_profile.py --code SEN-FK --like PER-PCL                  # case A
python SKILL_DIR/scripts/new_profile.py --code SEN-FK --like PER-PCL --only landcover,precip,spi3  # case B
python SKILL_DIR/scripts/new_profile.py --code TUN-NW --template default              # case C, no map
python SKILL_DIR/scripts/new_profile.py --code COL-CUM --template explorer --with-story --with-studies
```

The map camera and limits come from the landscape's bounding box. The website draws the landscape's
MOSAIC boundary on every explorer by itself: never add it as a layer (it would be drawn twice). Every value the person must
provide is a `TODO: …` placeholder (with the old value as "was: …" when copied), listed in
`work/<CODE>/checklist.md`. Exit code 3: the code is not a landscape (case E). Exit code 4: the
folder exists (case D, or `--force` to start again, only if the person agrees).

### 4. Data hosting

Every file must be readable by the website: HTTPS, CORS for `https://mosaic-mfl.github.io`, and byte
ranges for `.pmtiles`, `.tif` and `.bin` files. Help the person choose where to serve the files and
how to convert them (`references/data-hosting.md`). Then set the data roots and check:

```sh
python SKILL_DIR/scripts/edit_profile.py set-root --code SEN-FK --root site --url https://…/data/
python SKILL_DIR/scripts/check_data.py --code SEN-FK
```

Explain each failure with `references/data-hosting.md`. A file whose licence is not cleared goes
under `data.withheld` (never requested), with `withheld_reason`.

### 5. Map each layer to a module and fill in the files

Open `references/modules.md`. For each layer the person wants: pick the overlay `kind` from the kind
of data, the `inspect` (click) from what a click should show, write the legend from the source's
own classes and colours, and its `sources.yaml` entry (source, period, licence, citation, caveats,
`record` if the dataset is in the catalogue). Edit the YAML files in `landscapes/<CODE>/`
directly. Fill in the TODOs with what the person gives you, asking for anything missing.

Other common changes:

```sh
python SKILL_DIR/scripts/edit_profile.py list --code KEN-LVB             # what the profile has
python SKILL_DIR/scripts/edit_profile.py remove-overlay --code KEN-LVB --id fire   # and every reference to it
```

### 5b. Only when the profile needs something new on the website

If step 5 shows that no module does what the person wants (a new kind of layer, a click, a chart, a
panel, a section, a small interface element such as a button or a pop-up), or they ask to change how
an existing module behaves, follow `references/web-modules.md`:

```sh
python SKILL_DIR/scripts/setup.py --web             # once: the website and the API
python SKILL_DIR/scripts/web_check.py               # after the change: types, tests, lint, build
python SKILL_DIR/scripts/web_preview.py --code SEN-FK --serve   # the real page, locally
```

Explain first, in plain words, what will be added and why configuration is not enough; agree it
with the person. Then write the module (core unless only this profile can use it), its test, its
documentation, the profile option that switches it on, and any mosaic-standard change it needs
(new core kind, new top-level key). Check it in the local page with the person, including that
KEN-LVB or PER-PCL still work.

### 6. Validate

```sh
python SKILL_DIR/scripts/validate.py --code SEN-FK          # --allow-todo for an early draft
```

It runs the same check as the catalogue's pull requests and explains each error (means / fix;
more in `references/errors.md`), and lists every TODO left. Repeat until it says **ready for a pull
request**. With `--allow-todo` it says **draft** instead: valid, but not ready to publish.

### 7. Preview

```sh
python SKILL_DIR/scripts/preview.py --code SEN-FK                   # a summary page, no map
python SKILL_DIR/scripts/web_preview.py --code SEN-FK --serve       # the real page with its map (needs setup.py --web once)
```

`preview.py` writes `work/<CODE>/preview.html`: sections, layers with their legend colours, clicks,
files and their check, story, studies, sources and licences, what is left to fill in. For a profile
with a map explorer, also run `web_preview.py --serve` and look at the map with the person: it is the
page as the website will show it. Ask the person to confirm the page reads as they want.

Explain it in plain words: two things start in that one window, the data (the API, port 8001) and
the page (the website, port 4321) that reads it; the person opens the address it prints and keeps the
window open. The data is built once: after any edit, run `web_preview.py --code <CODE>` (without
`--serve`) in another window and reload the page.

### 8. Pull request

Only when the person agrees.

```sh
python SKILL_DIR/scripts/prepare_pr.py --code SEN-FK [--change "one line, for an edited profile"] [--depends <website PR URL>]
```

It writes the title and body (`work/<CODE>/pr-title.txt`, `pr-body.md`) and prints the exact
commands: a new branch `landscape/<code>-<topic>`, a commit of `landscapes/<CODE>/` only, push, and
`gh pr create` against the base branch `setup.py` found (`main`). Show the person the commit message and run them.

It prints no commands (exit code 3) while the validator fails or TODO placeholders are left: the
website would show "TODO". Fill them in, or, if the team should see work in progress, run it with
`--draft` (a draft pull request). Files whose host did not answer from this computer are reported
apart, as not checked, not as problems.

- If the push is refused (no write access to `MOSAIC-mfl/catalog`), run
  `gh repo fork --remote=true` (the fork becomes `origin`, MOSAIC becomes `upstream`), push again,
  and add `--repo MOSAIC-mfl/catalog` to `gh pr create`.
- Without `gh`, push the branch and give the person the "compare & pull request" link GitHub prints;
  they paste `pr-body.md` as the description.

With a website change (step 5b) there are two or three pull requests: the website one first (on a
branch of the website checkout, base `website_base` from setup.py), then mosaic-standard if it
changed, then the catalogue one with `--depends <their URLs>` (`references/web-modules.md`, §6).

Give the person the pull request links and tell them each repository's checks run on them.

## References

- `references/modules.md`: every section, overlay, click, panel, story and study option, with real
  examples from KEN-LVB and PER-PCL.
- `references/data-hosting.md`: where to serve the files, CORS, byte ranges, conversions.
- `references/recipes.md`: cases A–E step by step.
- `references/errors.md`: validator messages, what they mean and how to fix them.
- `references/web-modules.md`: when and how to change the website for a profile, and its PR.
- `references/glossary.md`: the words used here, for explaining to the person.
- `references/pieces.md`: what a profile can have and what each piece needs from the person.
- The standard's `docs/landscape-profiles.md` and `schema/landscape/*.schema.json`, and the
  website's `frontend/docs/landscape-profiles.md`, are the source of truth when in doubt.
