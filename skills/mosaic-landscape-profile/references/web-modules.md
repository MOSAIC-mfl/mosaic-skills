# Changing the website for a profile

Most profiles need **no website change**: the website draws any profile that uses the existing
modules (`modules.md`). Change the website only when the profile needs something it cannot draw
or do yet, or when the person asks to change how an existing module behaves. Then the change is
part of the work, in its own pull request to `MOSAIC-mfl/website`.

## 1. Is a website change needed?

| The person wants | Website change? |
|---|---|
| New texts, colours, legends, layers of an existing kind, story chapters, study cards | No: configuration |
| A layer of an existing kind with options it already has (`modules.md`) | No |
| A new kind of layer (a format or a way of drawing no renderer has) | Yes: a renderer |
| A click that shows data in a way no inspector does (another file format, a computation) | Yes: an inspector |
| A story chart no builder draws | Yes: a chart builder |
| A side panel of a new kind | Yes: a panel |
| A new section of the Landscapes page (next to Overview and Map visualization) | Yes: a section of the explorer (`components/landscapes/`) |
| A small new piece of interface: a button, a pop-up window, a control, a link in the explorer | Yes: a UI component, switched on by configuration |
| A module that behaves wrongly, or an option an existing module lacks | Yes: an edit of that module |

Before writing code, check `modules.md` and the website's `frontend/docs/landscape-profiles.md`
once more: the option may exist. Tell the person, in plain words, what will be added and that it
goes to the website team for review.

## 2. Core module or profile plugin?

- **Core** (registered for every profile) when other landscapes could use it: a new kind of layer,
  a generic click, a chart, a button. Default choice.
- **Profile plugin** (`src/profiles/<code>/`, loaded only with that landscape's map profile) when it reads a
  data format or follows rules only that profile has. Example: KEN-LVB's `flood-query` click reads
  its own query raster's codes.

## 3. Set up and work

```sh
python SKILL_DIR/scripts/setup.py --web          # clones the website and the API, installs them
```

The website code is in `<website>/frontend/` (Astro 7 + React 18 + TypeScript 6, Node 22.23.4+;
MapLibre for the map). Work on a branch of the website checkout, made from `main`:

```sh
cd <website> && git switch -c landscape/<code>-<topic>
```

Where things are (read the file headers; they explain each part):

| Part | Path (under `frontend/src/`) | Registered in |
|---|---|---|
| Overlay renderers (kinds of layer) | `features/explorer/renderers/*.ts`, interface `OverlayRenderer` in `renderers/types.ts` | `coreRegistry()` in `renderers/registry.ts` |
| Click inspectors | `features/explorer/inspectors/core.ts`, `attributes.ts`; `InspectorFactory` in `renderers/types.ts` | `CORE_INSPECTORS` / `ATTRIBUTE_INSPECTORS` |
| Side panels | `features/explorer/panels/core.ts` (`PanelFactory`) | `CORE_PANELS` |
| Story chart builders | `features/explorer/application/chart-builders.ts` (`ChartBuilder`) | `CORE_CHART_BUILDERS` |
| Profile plugins | `profiles/<code>/index.ts` exporting a `ProfilePlugin` | `PLUGINS` in `features/explorer/plugins.ts` |
| The map profile (map, story, studies) | `features/landscape/ProfileMap.tsx` → `MapExplorer.tsx` → `features/explorer/ui/ExplorerApp.tsx`; shown in the explorer's panel by `ProfileMapPanel.tsx` and full screen by `pages/landscapes/[code]/map.astro` | — |
| Sections of the Landscapes page (Overview, Map visualization, Knowledge hub, Other resources) | `components/landscapes/LandscapeExplorer.astro` (`sectionList`, markup, styles) and `components/landscapes/explorer/controller.ts`; catalogue figures through `lib/ui/landscape-explorer-data.ts` | `sectionList` |
| Explorer interface (rail, legend, time bar, pop-overs, panels, story, top bar) | `features/explorer/ui/*.tsx` | — |
| Configuration types and parsing | `features/explorer/domain/config.ts`; typed option reads `domain/options.ts` | — |
| What panels and pop-overs show | `features/explorer/domain/blocks.ts` (`Block`: kpis, chart, rows, note…) | drawn by `ui/Blocks.tsx` |
| Explorer styles | `styles/explorer.css` (scoped under `.lvx`, MOSAIC tokens from `styles/variables.css`) | — |

### Rules that keep the website consistent (from its docs)

- Components never import MapLibre or geotiff; they talk to the controller
  (`application/explorer.ts`), which talks to the ports (`ports/map-engine.ts`, `ports/data.ts`).
- Modules return models (legend, time bar, `Inspection` with `Block`s); nothing writes HTML strings,
  no `innerHTML`, no `window.*` hooks. One state, in the controller's store; one floating panel open
  at a time.
- What changes per profile is configuration. A new UI element is **off unless the profile asks for
  it** (an optional key), so the other profiles look exactly as before.
- Keep the MOSAIC look: reuse existing classes and tokens in `explorer.css`; no new colours outside
  the tokens, no new npm packages (ask the developers if one seems necessary).
- Accessible controls: `<button type="button">` with a visible label or `aria-label`, keyboard
  reachable, `Esc` closes pop-ups like the existing ones.
- English texts; texts that come from the profile are configuration, not hard-coded.

### Skeletons

An inspector (what a click shows), options read from the profile's `inspect:` block:

```ts
// features/explorer/inspectors/<file>.ts
import type { Inspector, InspectorFactory } from '../renderers/types'
import type { Options } from '../domain/options'

/** my-click: `series` (JSON), `path`, `title`, `unit` (describe every option here). */
export const myClick: InspectorFactory = (o: Options): Inspector => ({
  async inspect(ctx, lngLat, vars) {
    const doc = await ctx.data.json<Record<string, unknown>>(o.str('series'))
    // ... compute from doc, lngLat and vars.year
    return {
      target: 'popover',            // or 'panel'
      title: o.str('title'),
      hint: o.optStr('hint'),
      blocks: [{ type: 'rows', rows: [['Value', '42']] }],
    }
  },
})
// register: add `'my-click': myClick` to CORE_INSPECTORS (core) or registry.registerInspector in a plugin
```

A renderer implements every method of `OverlayRenderer` (`register`, `available`, `show`, `hide`,
`legend`, `timeControl`, `inspect`, …): start from the closest existing one (`raster-tiles.ts` for
one file, `year-tiles.ts` for one file per year, `style-layers.ts` for vectors) and register it in
`coreRegistry()` with its `kind`.

A small UI element (a button that opens a pop-up, for example): add an optional key where it
belongs in the profile (inside an overlay, a panel, `click` or `about` when possible), type it in
`domain/config.ts`, read it in the component, show the element only when the key is present, and
keep its open/closed state in the controller's store like the other panels.

## 4. The other repositories a website change can need

| When | Also change | Why |
|---|---|---|
| A new **core** overlay kind | mosaic-standard: `CORE_OVERLAYS` in `src/mosaic_catalog/landscapes.py`, the kind list in `schema/landscape/explorer.schema.json`, `docs/landscape-profiles.md` | otherwise the validator warns "not a core renderer" |
| A new **top-level** key of `explorer.yaml` or a new key under `map` | mosaic-standard: `schema/landscape/explorer.schema.json` | those blocks reject unknown keys (keys inside overlays, panels, `click` and `inspect` are free) |
| Any new module or option | website `frontend/docs/landscape-profiles.md` ("Adding things"), and this skill's `references/modules.md` | so the next profile finds it |

mosaic-standard changes go on a branch `landscape/<code>-<topic>` and a pull request to `main`
(with a test in `tests/test_landscapes.py` and a CHANGELOG line).

## 5. Check and preview

```sh
python SKILL_DIR/scripts/web_check.py               # types, tests, lint, build: what the website's CI runs
python SKILL_DIR/scripts/web_preview.py --code <CODE> --serve [--data <local data folder>]
```

- Add a test in `frontend/tests/` for every new module (vitest, no browser: `tests/explorer-fakes.ts`
  has a fake map and fake data; `tests/explorer-ucayali.test.ts` shows how). A profile fixture can be
  copied from `<work>/_web/site/v1/landscapes/<CODE>.json` after `web_preview.py`.
- Open the page `web_preview.py` prints and try the change with the person: the new element, and
  that another profile (KEN-LVB or PER-PCL) still looks and works as before.

## 6. Pull requests

1. **Website:** commit only `frontend/` files of the change; PR to the website base branch, titled
   "Explorer: <what> for the <CODE> profile". Body: what was added, why configuration was not enough,
   the new options with an example, tests, how it was checked, screenshots if possible.
2. **mosaic-standard** (only when section 4 applies).
3. **Catalogue:** the profile, as usual (`prepare_pr.py --depends <website PR URL> [--depends <standard PR URL>]`).

Merge order: mosaic-standard, website, catalogue. The profile can be reviewed in parallel; its page
shows the new element once the website is deployed.

Note: the website only draws a profile's `map-explorer` section (in "Map visualization"). The other
section kinds of `profile.yaml` (overview, catalogue-datasets, data-status) are still valid and served
by mosaic-api, but the Landscapes page draws its own overview from the site's data and the API's
figures.
