---
name: mosaic-contribute
description: Turn a folder of datasets in any format (GeoTIFF, Shapefile, GeoPackage, GeoJSON, NetCDF, CSV, Excel, KML, ZIP...) into MOSAIC catalogue records and send them as one pull request to MOSAIC-mfl/catalog, or as a zip for the MOSAIC team, with no Excel and no GitHub form. A script reads the files; you only ask the person what files cannot say. Use when someone wants to add, register, contribute, catalogue or share datasets with MOSAIC or the CGIAR Multifunctional Landscapes catalogue ("registrar mis datos en MOSAIC", "contribuir datasets", "ajouter mes données").
---

# Contribute a folder of datasets to MOSAIC

A script reads the files and writes the records (MOSAIC standard v0.2); you collect only what the
files cannot say. Talk in the person's language; everything written to the records is in English.

`C` below means `python3 <this skill's folder>/scripts/mosaic_contribute.py` (Windows: `py` or
`python`). Python 3.8+ and nothing else. Its state lives in `./mosaic-contribution/` (`--work DIR`
before the command changes it). If you cannot run commands, give the person each command and ask
them to paste the output back.

## Rules (they keep this cheap and correct)

1. Do not open the data files, `scan.json`, `answers.json` or the records: the command output is
   all you need. Read a README or MANIFEST listed under "Docs" only to write a description, and
   only if it is short.
2. Nothing invented. Values read inside the files are filled in automatically (each record lists
   them in `derived`). `sug:` values are guesses from file names or metadata: show them, and record
   them only after the person agrees (`accept`).
3. One message with all the questions, one `set` command with all the answers. Ask again only for
   what `build` still lists.
4. MOSAIC links to data; it never hosts it. Public data needs a URL where it already lives (DOI,
   Zenodo, Dataverse, CGSpace, an institutional site, Earth Engine...). No URL: `access=restricted`
   (or `non-public`) with `access_note` saying how to obtain it. A staging share (SharePoint,
   Google Drive) is not a record URL.
5. Nothing is sent without the person's explicit yes to the final list.

## Steps

1. `C scan "<folder>"` prints one line per dataset (what the files say), then what is missing and
   the suggestions. Files of one dataset spread over subfolders (tiles, one folder per dataset)?
   Run again with `--per-folder`. Numbered files (2001...2020) are grouped as one dataset already;
   `--no-series` splits them.
2. Ask the person, in ONE message, only what the output says is missing:
   - for all datasets: who produced the data and who holds the rights (organization, name,
     email); the licence (CC-BY-4.0, CC0-1.0..., or their own terms as text or a link); whether
     the data is public, on request or internal, and the link to download or request it;
   - per dataset: one or two sentences on what it is and how it was made, a better title if the
     suggested one is poor, the themes;
   - the suggestions (title, themes, period, landscapes, licence...): confirm or correct.
3. Record everything in one command (quote values that have spaces):
   `C set "shared.contact=Org | Name | email" shared.license=CC-BY-4.0 shared.access=public shared.url=https://doi.org/... accept=all "d01.description=..." d02.themes=water-hydrology,climate`
4. `C build` writes and checks the records. If it lists missing values, `set` them and build again.
5. Show the person the build list (titles and what each record holds) and ask how to send it:
   - `C submit --github`: pull request to MOSAIC-mfl/catalog with the next free MFL ids. Needs git
     and the GitHub CLI logged in (the person runs `gh auth login` once). `--dry-run` shows the plan.
   - `C submit --bundle`: a zip in the work folder, which the person sends to the MOSAIC contact
     listed at https://mosaic-mfl.github.io/website/about#contribute.
   A MOSAIC maintainer reviews and merges; the data files never leave the person's computer.

## `set` reference

- Targets: `shared.F` (every dataset), `dNN.F` (one dataset; wins over shared), `all.F` (the same
  value written into each dataset), `F` alone means shared.
- Fields: title, description, themes, keywords, landscapes, geography (ISO3 such as PER, KEN; filled
  from the landscapes when empty), license, license_text, license_url, access
  (public|restricted|non-public), access_note, url, access_method
  (download|landing_page|service|request; guessed from the url), contact, citation, doi, temporal
  (`2020`, `2001..2020`, `2015..` for ongoing), update_frequency, resolution (`30 m`, or text such as
  `district level`), resource_type, version, skip (`d03.skip=yes` leaves a dataset out).
- Lists are comma-separated; `+=` adds to a list; an empty value clears the field.
- Contact: `Org | Name | email | roles`; several contacts separated by `;;`. Roles default to
  producer,licensor,point-of-contact (others: host, processor, maintainer, funder). At least one
  contact must be the licensor (who grants the licence).
- A licence without an SPDX id: `license=LicenseRef-source-terms` plus `license_text=...` or
  `license_url=...`.
- Suggestions: `accept=all`, `accept=d01,d03`, `d01.accept=title,themes`. A contact found in the
  files' metadata is never taken by `accept=all`; `d01.accept=contact` adds it as producer.
- `C status` shows what is still missing. `scan` and `status` print the theme and landscape codes.

## When something does not work

- A format shown with `!` was only partly read: the dataset still counts. More detail needs optional
  packages (`pip install rasterio pyogrio pyproj netCDF4 pyarrow`), never required.
- No git, no GitHub CLI or no GitHub account: `submit --bundle`.
- `build` reports a problem from the MOSAIC validator: fix that field with `set` and build again.
