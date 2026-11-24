# What a profile can have, and what each piece needs from the person

Use this to offer the person a menu ("which of these do you want?") and to ask, one question at a
time, only for what the pieces they chose need. KEN-LVB and PER-PCL have all of them; a profile can
have any subset. Details and examples of each field: `modules.md`.

| Piece | What the visitor sees | What you need from the person | Where it goes |
|---|---|---|---|
| Page | Title, summary and sections of the landscape page | A summary (one or two sentences), who to credit and for what | `profile.yaml` |
| Map layers (overlays) | Layers chosen one at a time, with a legend | Per layer: the data file online (PMTiles for display, a GeoTIFF if a click reads values), name, group, legend classes and colours as the source gives them, credit | `explorer.yaml` `overlays` |
| A click on a layer (`inspect`) | What a click on the map shows for that layer | What the click should show (a value, a class, a series, the attributes of a polygon) and the file it reads (GeoTIFF, JSON series, vectors) | `overlays[].inspect` |
| Base map | Imagery, terrain, place names under the layers | PMTiles of the area for each (see `modules.md`, base map), with their credits | `explorer.yaml` `map` |
| Switches (`toggles`) | Base layers that can be turned on and off: rivers, boundaries, labels | One file per switch (usually GeoJSON or vector PMTiles), its name and credit | `toggles` + `map.layers` |
| Side panels (`panels`) | A panel with figures and a chart of a series (KEN-LVB: lake level) | A JSON series (dates and values), the unit, which figures to show | `panels` |
| A click anywhere (`click`) | The place or administrative unit clicked, with no layer chosen | Administrative boundaries of the area and the names of their levels | `click` |
| Story | Chapters that move the map as the reader goes | Each chapter's text (the author's, with citations), which layer and moment it shows, and every number with where it comes from (a study and its page, or the method of an analysis) | `story.yaml` |
| Study cards | Findings of published studies, or open questions | Per card: the question, the finding as the paper states it, the citation and DOI, the pages each claim is on; or `explore` for a question without results | `studies.yaml` |
| Sources | The sources list of the explorer | Per layer: source, period, units, licence, citation, limitations; the catalogue record if there is one | `sources.yaml` |

Never fill these with invented content. With no real data yet, see recipe C2 (`recipes.md`). The
same layer as another profile (the same file and source) is fine when the person says so.
