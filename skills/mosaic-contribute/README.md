# mosaic-contribute

Add a folder of datasets to the MOSAIC catalogue without filling in an Excel sheet or a GitHub form.
You point your AI assistant at the folder; a script reads the files (format, coordinate system,
extent, resolution, period, attributes, bands, embedded metadata), the assistant asks you only what
the files cannot say (who made the data, the licence, where people can get it, a short
description), and the records are sent as one pull request to
[MOSAIC-mfl/catalog](https://github.com/MOSAIC-mfl/catalog) or as a zip for the MOSAIC team.

- **Any dataset**: GeoTIFF (and TIFF + world file), ESRI ASCII grid, VRT, NetCDF, Shapefile, GeoJSON,
  GeoPackage, KML/KMZ, CSV/TSV (coordinates found by column name), Excel, ZIP of any of these, plus
  ISO, ESRI, FGDC and QGIS metadata files beside them. Other formats are read when `rasterio`,
  `pyogrio`, `netCDF4` or `pyarrow` happen to be installed; extents in any coordinate system with
  `pyproj` (UTM and Web Mercator work without it).
- **Any AI**: the skill is a plain `SKILL.md` plus a command-line script, so it works with any
  assistant that can run commands, and by hand.
- **Few tokens**: the assistant never opens the data or the records. It reads one short line per
  dataset, asks all its questions in one message and records all the answers in one command.
  Measured on a real folder of 20 datasets (2.5 GB of Shapefiles, GeoTIFFs, ZIPs and an Excel
  workbook): the scan prints 7.5 KB (about 2,000 tokens), `set` one line, `build` 2 KB; with
  `SKILL.md` (6 KB) the assistant reads about 4,500 tokens of instructions and tool output in all.
- **Nothing invented**: what is read inside the files is listed in each record's `derived`; guesses
  from file names or metadata are only suggestions, used after you confirm them.
- **Nothing to install**: Python 3.8 or newer, standard library only. The data never leaves your
  computer: MOSAIC catalogues where data lives, it does not host it.

## Install

**Claude (desktop app or claude.ai).** Make a ZIP of this folder with the folder at the top
(`cd skills && zip -r ../mosaic-contribute.zip mosaic-contribute`), then Settings → Capabilities →
Skills → Upload skill. Code execution must be on.

**Claude Code.** From your clone of mosaic-skills:
```sh
ln -s "$PWD/skills/mosaic-contribute" ~/.claude/skills/        # macOS / Linux
```
```powershell
New-Item -ItemType Junction -Path $HOME\.claude\skills\mosaic-contribute -Target "$PWD\skills\mosaic-contribute"   # Windows
```

**Other assistants that read Agent Skills (`SKILL.md`)**: copy or link this folder into the skills
folder your assistant reads (see its documentation).

**Any other AI chat**: give it `SKILL.md` as instructions and the `scripts/` folder (upload a ZIP if
it can run code; otherwise it gives you the commands to run and you paste the output back).

## Use it

Say, in any language: *"Add the datasets in D:\Data\Ucayali to MOSAIC"*, *"Registra en MOSAIC los
datos de esta carpeta"*. The assistant scans, asks one round of questions, builds and checks the
records, shows you the list, and sends it only when you say so.

Without an assistant, the same steps by hand:

```sh
python3 scripts/mosaic_contribute.py scan "path/to/folder"
python3 scripts/mosaic_contribute.py set "shared.contact=My Centre | My Name | me@example.org" shared.license=CC-BY-4.0 shared.access=public shared.url=https://doi.org/10.5281/zenodo.XXXX accept=all "d01.description=What it is and how it was made."
python3 scripts/mosaic_contribute.py build
python3 scripts/mosaic_contribute.py submit --bundle      # or --github (needs the GitHub CLI: gh auth login)
```

You can also edit `mosaic-contribution/answers.json` directly and run `build` again.

## Contents

```
SKILL.md                      what the assistant follows
scripts/mosaic_contribute.py  scan, set, status, build, submit
scripts/readers.py            what each file format says about itself (standard library only)
tests/                        synthetic files of every format; the whole flow; the MOSAIC validator
```

`build` checks the records against the published schema when `jsonschema` is installed, and with the
catalogue's own validator when the `mosaic-standard` tool is installed; the catalogue runs the same
validator on every pull request.
