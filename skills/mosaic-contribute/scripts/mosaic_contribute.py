"""Turn a folder of datasets into MOSAIC catalogue records (standard v0.2) and send them.

    python mosaic_contribute.py scan FOLDER [--per-folder] [--no-series] [--docs]
    python mosaic_contribute.py set KEY=VALUE ... [accept[=all|d01,d02]]
    python mosaic_contribute.py status
    python mosaic_contribute.py build
    python mosaic_contribute.py submit --github [--dry-run] | --bundle

Work folder: --work DIR (default ./mosaic-contribution). It holds scan.json (what the files say),
answers.json (what the person said; editable by hand), records/ (the built records) and .cache/.

Rules: values read from inside the files go into the records and are listed in ``derived``; values
guessed from names or found in metadata sidecars are SUGGESTIONS, used only after ``accept``; the
rest comes from the person. Output is kept short on purpose: it is read by an AI assistant.
Needs only Python 3.8+. Optional: jsonschema (structure check), the mosaic-standard tool (full check).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import readers

CATALOG_REPO = "MOSAIC-mfl/catalog"
PAGES = "https://mosaic-mfl.github.io/catalog"
CONTACT_PAGE = "https://mosaic-mfl.github.io/website/about#contribute"
STANDARD_VERSION = "0.2.0"
LIST_FIELDS = {"themes", "keywords", "landscapes", "geography"}
FIELDS = LIST_FIELDS | {"title", "description", "license", "license_text", "license_url", "access", "access_note",
                        "url", "access_method", "contact", "citation", "doi", "temporal", "update_frequency",
                        "resolution", "resource_type", "version", "skip"}  # fmt: skip
ACCESS = ("public", "restricted", "non-public")
ROLES = ("producer", "licensor", "host", "processor", "point-of-contact", "maintainer", "funder")
DEFAULT_ROLES = ["producer", "licensor", "point-of-contact"]
FALLBACK_THEMES = ["boundaries-admin-units", "land-cover-land-use", "ecosystem-condition", "degradation-land-health",
                   "water-hydrology", "biodiversity-ecosystems", "pressures-drivers", "ecosystem-services",
                   "hotspots-leverage-points", "scenarios-future-risks", "decision-support-outputs",
                   "agrobiodiversity-crops", "socio-economic-livelihoods", "climate", "climate-adaptation",
                   "climate-mitigation"]  # fmt: skip
FALLBACK_LANDSCAPES = {
    "COL-CUM": (["COL"], [-78.0702, 0.8386, -77.7535, 1.0784]), "PER-PCL": (["PER"], [-75.9479, -9.4181, -74.3225, -7.9501]),
    "SEN-FK": (["SEN"], [-16.7921, 13.9284, -16.1055, 14.6084]), "CIV-NZ": (["CIV"], [-5.3792, 5.95, -3.8583, 9.4333]),
    "TUN-NW": (["TUN"], [8.9235, 35.7384, 9.4464, 36.4324]), "ETH-OG": (["ETH"], [34.9533, 4.431, 38.4128, 9.3685]),
    "KEN-LVB": (["KEN"], [33.948, -0.6615, 35.675, 0.5631]), "KEN-LEI": (["KEN"], [35.9962, -3.1869, 38.5194, -0.7526]),
    "ZWE-MB": (["ZWE"], [28.8445, -17.4339, 32.0584, -15.6073]), "IND-CH": (["IND"], [78.2942, 22.2022, 81.1975, 25.9555]),
    "MEK-3S": (["KHM", "LAO", "VNM"], [105.95, 11.8519, 108.7757, 16.3852]),
}  # fmt: skip
THEME_HINTS = [
    ("boundaries-admin-units", r"admin|\badm[0-4]|boundar|border|limit|district|county|province|municip|watershed|basin|catchment|delineat"),
    ("land-cover-land-use", r"lulc|land.?cover|land.?use|worldcover|cobertura|uso.?suelo|cropland|forest.?cover|deforest|classif"),
    ("ecosystem-condition", r"ndvi|\bevi\b|\blai\b|fapar|\bnpp\b|\bgpp\b|vegetation|biomass|canopy"),
    ("degradation-land-health", r"soil|suelo|erosion|degrad|organic.?carbon|\bsoc\b|texture|\bclay\b|\bsand\b|\bsilt\b|salin"),
    ("water-hydrology", r"river|stream|\blake|water|hydro|rain|precip|chirps|runoff|flood|wetland|irrigat|discharge|evapo"),
    ("biodiversity-ecosystems", r"species|biodiv|habitat|protected|wdpa|\bkba\b|occurrence|gbif|ecoregion|conserv"),
    ("pressures-drivers", r"road|population|pop.?dens|night.?light|\bfire|burn|mining|urban|settlement|travel.?time|pressure"),
    ("ecosystem-services", r"ecosystem.?service|pollinat|carbon.?stock|sequest|water.?yield"),
    ("agrobiodiversity-crops", r"\bcrop|maize|wheat|rice|cassava|coffee|cocoa|yield|agri|farm|variet|\bseed"),
    ("socio-economic-livelihoods", r"household|survey|income|poverty|livelihood|census|market|gender|socio|econom"),
    ("climate", r"temperat|\btmax|\btmin|tmean|climat|chirts|era5|worldclim|cmip|drought|\bspei?\b"),
    ("scenarios-future-risks", r"scenario|\bssp\d|\brcp\d|projection|future"),
    ("hotspots-leverage-points", r"hotspot|priorit|leverage"),
    ("decision-support-outputs", r"suitab|optimi|decision|zoning"),
]  # fmt: skip
SIDE_EXT = {".shx", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".fix", ".aih", ".ain", ".atx", ".xml", ".qmd", ".qml",
            ".sld", ".lyr", ".lyrx", ".ovr", ".aux", ".rrd", ".tfw", ".tifw", ".tiffw", ".wld", ".jgw", ".pgw", ".msk",
            ".lock", ".ini", ".db", ".hdr", ".mxd", ".aprx", ".qgz", ".qgs", ".py", ".r", ".ipynb", ".log"}  # fmt: skip
DATA_EXT = set(readers.READERS) | readers.RASTER_ONLY_EXT
DIR_DATASETS = (".gdb", ".zarr", ".safe")
DOWNLOAD_EXT = (".zip", ".tif", ".tiff", ".csv", ".gpkg", ".geojson", ".json", ".nc", ".xlsx", ".parquet", ".kmz",
                ".kml", ".shp", ".7z", ".gz", ".tar", ".asc", ".pdf")  # fmt: skip


# -- small helpers -----------------------------------------------------------------------------------
def say(*lines: str) -> None:
    print("\n".join(lines))


def load_json(p: Path, default: Any = None) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def fetch_json(url: str, cache: Path, max_age_days: int = 3) -> Optional[Any]:
    """A published JSON file, cached in the work folder; None when offline and not cached."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    fresh = (
        cache.exists()
        and (date.today().toordinal() - date.fromtimestamp(cache.stat().st_mtime).toordinal()) < max_age_days
    )
    if not fresh:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mosaic-contribute/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                cache.write_bytes(r.read())
        except Exception:  # e.g. a Python without CA certificates: curl uses the system's
            if shutil.which("curl"):
                subprocess.run(["curl", "-fsSL", "--max-time", "20", "-o", str(cache), url], capture_output=True)
    try:
        return load_json(cache)
    except ValueError:
        return None


def vocab(work: Path) -> Dict[str, Any]:
    themes = fetch_json(f"{PAGES}/vocab/themes.json", work / ".cache/themes.json")
    lands = fetch_json(f"{PAGES}/vocab/landscapes.json", work / ".cache/landscapes.json")
    out: Dict[str, Any] = {"themes": FALLBACK_THEMES, "landscapes": FALLBACK_LANDSCAPES}
    if themes and themes.get("concepts"):
        out["themes"] = [c["id"] for c in themes["concepts"]]
    if lands and lands.get("concepts"):
        out["landscapes"] = {c["id"]: (c.get("countries", []), c.get("bbox")) for c in lands["concepts"]}
    return out


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000  # type: ignore[assignment]
    return f"{n} B"


def date_tokens(name: str) -> List[str]:
    """Dates written in a file name, at the precision written (YYYY, YYYY-MM or YYYY-MM-DD)."""
    out = []
    for m in re.finditer(
        r"(?<!\d)((?:19|20)\d{2})(?:[-_.]?(0[1-9]|1[0-2])(?:[-_.]?(0[1-9]|[12]\d|3[01]))?)?(?!\d)", name
    ):
        y, mo, d = m.groups()
        out.append("-".join(x for x in (y, mo, d) if x))
    return out


def short_names(stems: List[str]) -> List[str]:
    """File stems without the prefix they all share (MFL-2026-066__BD_0_20cm -> BD_0_20cm)."""
    pre = stems[0] if stems else ""
    for st in stems[1:]:
        while not st.startswith(pre):
            pre = pre[:-1]
    pre = pre[: len(pre) - len(re.sub(r"^.*?([A-Za-z0-9]*)$", r"\1", pre))] if pre else pre
    out = [s[len(pre) :] or s for s in stems]
    return out if len(set(out)) == len(out) and min(len(o) for o in out) >= 2 else stems


def humanize(stem: str) -> str:
    s = re.sub(r"[_\-.]+", " ", stem).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:1].upper() + s[1:] if s else stem


SPDX = [
    (r"cc[ -_]?0|cc ?zero|public domain dedication", "CC0-1.0"),
    (r"cc[ -_]?by[ -_]?nc[ -_]?sa[ -_]?4", "CC-BY-NC-SA-4.0"), (r"cc[ -_]?by[ -_]?nc[ -_]?4", "CC-BY-NC-4.0"),
    (r"cc[ -_]?by[ -_]?sa[ -_]?4", "CC-BY-SA-4.0"), (r"cc[ -_]?by[ -_]?4|attribution 4\.0", "CC-BY-4.0"),
    (r"cc[ -_]?by[ -_]?3|attribution 3\.0", "CC-BY-3.0"), (r"odbl|open database licen", "ODbL-1.0"),
    (r"\bmit licen", "MIT"), (r"apache.{0,10}2", "Apache-2.0"),
]  # fmt: skip


def spdx_from_text(text: str) -> Optional[str]:
    t = (text or "").lower()
    for pat, code in SPDX:
        if re.search(pat, t):
            return code
    return None


# -- scan ----------------------------------------------------------------------------------------------
def discover(root: Path, work: Path, per_folder: bool, series: bool, docs_as_data: bool) -> Tuple[list, list, list]:
    groups: Dict[Any, List[Path]] = {}
    docs: List[str] = []
    ignored: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        keep = []
        for name in sorted(dirnames):
            p = d / name
            if (
                name.startswith((".", "__MACOSX"))
                or p.resolve() == work.resolve()
                or name in ("node_modules", "__pycache__")
            ):
                continue
            if name.lower().endswith(DIR_DATASETS):
                groups[("dir", p)] = [p]
            else:
                keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            p = d / name
            low = name.lower()
            ext = p.suffix.lower()
            if (
                name.startswith((".", "~$", "._"))
                or low in ("thumbs.db", "desktop.ini")
                or low.endswith((".aux.xml", ".vat.dbf"))
            ):
                continue
            if ext == ".dbf" and (p.with_suffix(".shp").exists() or p.with_suffix(".SHP").exists()):
                continue
            if ext in SIDE_EXT:
                continue
            if ext in readers.DOC_EXT and not docs_as_data:
                docs.append(str(p.relative_to(root)))
                continue
            if ext not in DATA_EXT and ext not in readers.DOC_EXT:
                ignored.append(ext or name)
                continue
            rel = p.relative_to(root)
            if per_folder and len(rel.parts) > 1:
                key: Any = ("folder", root / rel.parts[0])
            elif series:
                key = ("series", d, ext, re.sub(r"\d+", "#", p.stem))
            else:
                key = ("file", p)
            groups.setdefault(key, []).append(p)
    out = []
    for key, files in groups.items():
        if key[0] == "series" and len(files) == 1:
            key = ("file", files[0])
        out.append((key, sorted(files)))
    out.sort(key=lambda kf: str(kf[1][0]))
    return out, docs, ignored


def size_of(p: Path) -> int:
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    total = p.stat().st_size
    if p.suffix.lower() == ".shp":
        total += sum(
            p.with_suffix(e).stat().st_size for e in (".shx", ".dbf", ".prj", ".cpg") if p.with_suffix(e).exists()
        )
    return total


def suggest_for(facts: Dict[str, Any], files: List[Path], stem_label: str, lands: Dict[str, Any],
                ignore_dates: set) -> Dict[str, Any]:  # fmt: skip
    meta = facts.get("meta") or {}
    sug: Dict[str, Any] = {}
    title = meta.get("title") or stem_label
    sug["title"] = humanize(title) if "_" in title or " " not in title.strip() else title
    if meta.get("abstract"):
        sug["description"] = meta["abstract"]
    words = " ".join([stem_label, meta.get("title", ""), " ".join(meta.get("keywords", []))]
                     + [f.stem for f in files[:50]]
                     + [v.get("name", "") + " " + v.get("description", "") for v in facts.get("variables", [])[:30]]).lower()  # fmt: skip
    words = re.sub(r"[_\-.]", " ", words)
    hits = [(len(re.findall(pat, words)), t) for t, pat in THEME_HINTS]
    themes = [t for n, t in sorted(hits, key=lambda x: -x[0]) if n][:2]
    if themes:
        sug["themes"] = themes
    if meta.get("keywords"):
        sug["keywords"] = meta["keywords"][:10]
    dates = sorted({d for f in files for d in date_tokens(f.stem)} - ignore_dates)
    if not facts.get("time") and dates:
        sug["temporal"] = dates[0] if len(dates) == 1 else f"{dates[0]}..{dates[-1]}"
    b = facts.get("bbox")
    if b:
        hit = []
        for code, (_, lb) in lands.items():
            if lb and not (b[2] < lb[0] or b[0] > lb[2] or b[3] < lb[1] or b[1] > lb[3]):
                hit.append(code)
        area = (b[2] - b[0]) * (b[3] - b[1])
        biggest = max(((lands[c][1][2] - lands[c][1][0]) * (lands[c][1][3] - lands[c][1][1]) for c in hit), default=0)
        if hit and len(hit) <= 3 and area <= 50 * max(biggest, 1e-6):
            sug["landscapes"] = hit
    lic = meta.get("license")
    if lic:
        code = spdx_from_text(lic)
        sug["license"] = code or "LicenseRef-source-terms"
        if not code:
            sug["license_text"] = lic[:500]
    if meta.get("organization"):
        sug["contact"] = [{k: v for k, v in (("organization", meta["organization"]), ("name", meta.get("name")),
                                             ("email", meta.get("email"))) if v}]  # fmt: skip
    if meta.get("citation"):
        sug["citation"] = meta["citation"]
    return sug


def cmd_scan(args: argparse.Namespace, work: Path) -> int:
    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        say(f"not a folder: {root}")
        return 2
    voc = vocab(work)
    groups, docs, ignored = discover(root, work, args.per_folder, not args.no_series, args.docs)
    found = []
    for key, files in groups:
        sample = files if len(files) <= 200 else files[:100] + files[-100:]
        facts_list = [readers.read_file(f) for f in sample]
        facts = (
            facts_list[0]
            if len(facts_list) == 1
            else readers.merge_facts(facts_list, short_names([f.stem for f in sample]))
        )
        if facts.get("kind") == "other":
            ignored.append(files[0].suffix.lower() or files[0].name)
            continue
        if len(files) == 1:
            label, stem = files[0].name, files[0].stem
        elif key[0] == "folder":
            label, stem = f"{key[1].name}/", key[1].name
        else:
            label, stem = f"{files[0].name} … {files[-1].name}", re.sub(r"\d+", " ", files[0].stem)
        found.append((files, facts, label, stem))
    # a date written in (nearly) every dataset's names is a project or delivery year, not the data's period
    counts: Dict[str, int] = {}
    for files, *_ in found:
        for tok in {t for f in files for t in date_tokens(f.stem)}:
            counts[tok] = counts.get(tok, 0) + 1
    common = {t for t, n in counts.items() if len(found) >= 3 and n >= 0.8 * len(found)}
    datasets = []
    for files, facts, label, stem in found:
        datasets.append({
            "key": f"d{len(datasets) + 1:02d}", "label": label, "files": [str(f.relative_to(root)) for f in files],
            "size": sum(size_of(f) for f in files), "facts": facts,
            "suggest": suggest_for(facts, files, stem, voc["landscapes"], common),
        })  # fmt: skip
    scan = {"folder": root.name, "scanned": date.today().isoformat(), "datasets": datasets, "docs": docs[:30],
            "ignored": sorted(set(ignored))}  # fmt: skip
    work.mkdir(parents=True, exist_ok=True)
    # answers follow their dataset (by its first file) when the folder is scanned again
    prev = load_json(work / "scan.json", {}) or {}
    key_of_file = {d["files"][0]: d["key"] for d in prev.get("datasets", [])}
    answers = load_answers(work)
    kept = {d["key"]: answers["datasets"].get(key_of_file.get(d["files"][0], ""), {}) for d in datasets}
    dropped = sum(
        1 for k, v in answers["datasets"].items() if v and k not in {key_of_file.get(d["files"][0]) for d in datasets}
    )
    answers["datasets"] = kept
    (work / "scan.json").write_text(json.dumps(scan, indent=1, ensure_ascii=False), encoding="utf-8")
    save_answers(work, answers)
    say(f"Scanned {root.name}: {len(datasets)} dataset(s). Work folder: {work}")
    if dropped:
        say(f"({dropped} answered dataset(s) no longer found: their answers were dropped)")
    for d in datasets:
        say(scan_line(d))
    if docs:
        say(
            f"Docs (not catalogued; may help to write descriptions): {', '.join(docs[:8])}{' …' if len(docs) > 8 else ''}"
        )
    if scan["ignored"]:
        say(f"Ignored file types: {' '.join(scan['ignored'][:15])}")
    if len(datasets) > 15 and not args.per_folder:
        say("Many datasets: if each subfolder is one dataset, re-run with --per-folder.")
    print_status(work, scan, answers, voc, header=False)
    return 0


def scan_line(d: Dict[str, Any]) -> str:
    f = d["facts"]
    n = len(d["files"])
    bits = [d["key"], f.get("kind", "?"), d["label"] + (f" ({n} files)" if n > 1 else ""), f.get("format", "")]
    if f.get("crs") or f.get("crs_name"):
        bits.append(f.get("crs") or f"crs '{f['crs_name']}'")
    if f.get("resolution"):
        bits.append(f"{f['resolution']['value']} {f['resolution']['unit']}")
    if f.get("geometry_type"):
        bits.append(f["geometry_type"])
    if f.get("feature_count") is not None:
        bits.append(f"{f['feature_count']} {'rows' if f.get('kind') == 'tabular' else 'features'}")
    if f.get("bbox"):
        bits.append("bbox " + ",".join(f"{v:.2f}" for v in f["bbox"]))
    if f.get("time"):
        bits.append(f"time {f['time']['start']}..{f['time']['end']}")
    vs = [v["name"] for v in f.get("variables", [])]
    if vs:
        bits.append(f"{len(vs)} vars: " + ",".join(vs[:5]) + ("…" if len(vs) > 5 else ""))
    if f.get("layers"):
        bits.append(f"{len(f['layers'])} layers")
    bits.append(human_size(d["size"]))
    if f.get("meta", {}).get("source"):
        bits.append("+metadata")
    line = " | ".join(str(b) for b in bits if b)
    if f.get("problems"):
        line += "\n    ! " + "; ".join(f["problems"][:3])
    return line


# -- answers -------------------------------------------------------------------------------------------
def load_answers(work: Path) -> Dict[str, Any]:
    data = load_json(work / "answers.json", {}) or {}
    data["shared"] = data.get("shared") or {}
    data["datasets"] = {k: (v or {}) for k, v in (data.get("datasets") or {}).items()}
    return data


def save_answers(work: Path, answers: Dict[str, Any]) -> None:
    work.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"shared": answers["shared"], "datasets": answers["datasets"]}, indent=1, ensure_ascii=False)
    (work / "answers.json").write_text(text + "\n", encoding="utf-8")


# -- YAML out (no PyYAML needed): plain scalars when safe, JSON-quoted strings otherwise -------------
YAML_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false", "null", "~"}


def _scalar(v: Any, flow: bool = False) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return repr(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ".nan" if v != v else (".inf" if v > 0 else "-.inf")
        r = repr(v)
        return r.replace("e", ".0e") if "e" in r and "." not in r else r  # YAML 1.1 floats need a dot
    s = str(v)
    plain = (
        s == s.strip()
        and s
        and "\n" not in s
        and s.lower() not in YAML_WORDS
        and not re.match(r"^[-?:,\[\]{}#&*!|>'\"%@`]", s)
        and not re.match(r"^[-+]?(\d[\d_]*\.?\d*([eE][-+]?\d+)?|\.\d+|\.inf|\.nan)$", s, re.I)
        and not re.match(r"^\d{4}-\d{2}(-\d{2})?", s)
        and ": " not in s
        and " #" not in s
        and not s.endswith(":")
        and "\t" not in s
        and not (flow and re.search(r"[\[\]{},]", s))
    )
    return s if plain else json.dumps(s, ensure_ascii=False)


def _block(s: str, pad: str) -> Optional[str]:
    """A long one-line string as a folded block (>-), when folding gives the same string back."""
    if len(s) <= 90 or "\n" in s or "  " in s or s != s.strip() or "\t" in s or not s.isprintable():
        return None
    lines, cur = [], ""
    for w in s.split(" "):
        if cur and len(cur) + 1 + len(w) > 96:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    lines.append(cur)
    return ">-\n" + "\n".join(pad + ln for ln in lines)


def to_yaml(obj: Any, indent: int = 0) -> str:
    pad = " " * indent
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            k = _scalar(str(k))
            if isinstance(v, dict) and v:
                out.append(f"{pad}{k}:\n{to_yaml(v, indent + 2)}")
            elif isinstance(v, list) and v and any(isinstance(x, (dict, list)) for x in v):
                out.append(f"{pad}{k}:\n{to_yaml(v, indent)}")
            elif isinstance(v, list):
                out.append(f"{pad}{k}: [{', '.join(_scalar(x, True) for x in v)}]")
            elif isinstance(v, str) and _block(v, pad + "  "):
                out.append(f"{pad}{k}: {_block(v, pad + '  ')}")
            else:
                out.append(f"{pad}{k}: {'{}' if isinstance(v, dict) else _scalar(v)}")
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict) and v:
                inner = to_yaml(v, indent + 2)
                out.append(f"{pad}- {inner[indent + 2 :]}")
            elif isinstance(v, list):
                out.append(f"{pad}- [{', '.join(_scalar(x, True) for x in v)}]")
            else:
                out.append(f"{pad}- {_scalar(v)}")
    return "\n".join(out)


def parse_contact(text: str) -> Dict[str, Any]:
    if text.strip().startswith("{"):
        return json.loads(text)
    parts = [p.strip() for p in text.split("|")]
    parts += [""] * (4 - len(parts))
    c: Dict[str, Any] = {"organization": parts[0]}
    if parts[1]:
        c["name"] = parts[1]
    if parts[2]:
        c["email"] = parts[2]
    c["roles"] = [r.strip() for r in parts[3].split(",") if r.strip()] or list(DEFAULT_ROLES)
    return c


def parse_value(field: str, raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return None
    if field in LIST_FIELDS:
        if raw.startswith("["):
            return json.loads(raw)
        return [x.strip() for x in raw.split(",") if x.strip()]
    if field == "contact":
        if raw.startswith("["):
            return json.loads(raw)
        return [parse_contact(c) for c in raw.split(";;")]
    if field == "skip":
        return raw.lower() in ("1", "true", "yes", "y")
    return raw


def check_value(field: str, value: Any, voc: Dict[str, Any]) -> List[str]:
    probs = []
    if field == "themes":
        bad = [t for t in value or [] if t not in voc["themes"]]
        if bad:
            probs.append(f"unknown theme(s) {bad}; use: {', '.join(voc['themes'])}")
    elif field == "landscapes":
        bad = [t for t in value or [] if t not in voc["landscapes"]]
        if bad:
            probs.append(f"unknown landscape(s) {bad}; use: {', '.join(voc['landscapes'])}")
    elif field == "access" and value not in ACCESS:
        probs.append(f"access must be one of {', '.join(ACCESS)}")
    elif field == "geography":
        bad = [g for g in value or [] if not re.match(r"^([A-Z]{3}|m49:\d{3}|global)$", g)]
        if bad:
            probs.append(f"geography uses ISO 3166 alpha-3 codes (PER, KEN), m49:<code> or global: {bad}")
    elif field == "contact":
        for c in value or []:
            if not c.get("organization"):
                probs.append("each contact needs an organization")
            bad = [r for r in c.get("roles", []) if r not in ROLES]
            if bad:
                probs.append(f"unknown role(s) {bad}; use: {', '.join(ROLES)}")
            if c.get("email") and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", c["email"]):
                probs.append(f"email looks wrong: {c['email']}")
    elif (
        field == "license"
        and value
        and not re.match(r"^(LicenseRef-[A-Za-z0-9.-]+|[A-Za-z0-9.+-]+)( (AND|OR|WITH) .+)?$", value)
    ):
        probs.append("license must be an SPDX id (CC-BY-4.0, CC0-1.0, ...) or LicenseRef-source-terms + license_text")
    elif field == "url" and value and not re.match(r"^(https?|ftp|s3|gs)://\S+$|^mailto:\S+$", value):
        probs.append("url must be a full link (https://...)")
    return probs


def cmd_set(args: argparse.Namespace, work: Path) -> int:
    scan = load_json(work / "scan.json")
    if not scan:
        say("run scan first")
        return 2
    answers = load_answers(work)
    voc = vocab(work)
    keys = [d["key"] for d in scan["datasets"]]
    sugs = {d["key"]: d["suggest"] for d in scan["datasets"]}
    problems: List[str] = []
    changed = 0
    for item in args.pairs:
        m = re.match(r"^([\w.-]+?)(\+?=)(.*)$", item, re.S)
        name, op, raw = (m.group(1), m.group(2), m.group(3)) if m else (item, "=", "")
        parts = name.split(".")
        if parts[-1] == "accept" or name == "accept":
            targets = (
                keys
                if (len(parts) == 1 and raw in ("", "all"))
                else [p for p in raw.split(",") if p]
                if len(parts) == 1
                else [parts[0]]
            )
            fields = raw.split(",") if len(parts) == 2 and raw not in ("", "all") else None
            for t in targets:
                if t not in sugs:
                    problems.append(f"no dataset {t}")
                    continue
                for fld, val in sugs[t].items():
                    if (
                        fld == "contact"
                    ):  # only on request: the producer named in the metadata, added to the shared contacts
                        if fields and "contact" in fields:
                            box = answers["datasets"][t]
                            cur = box.get("contact") or [dict(c) for c in answers["shared"].get("contact") or []]
                            for c in val:
                                c = {**c, "roles": c.get("roles") or ["producer"]}
                                if not any(x.get("organization") == c["organization"] for x in cur):
                                    cur.append(c)
                            box["contact"] = cur
                            changed += 1
                        continue
                    if (fields is None or fld in fields) and answers["datasets"][t].get(fld) in (None, [], ""):
                        if fld in answers["shared"] and fld not in ("title", "description"):
                            continue  # the person already answered it for every dataset
                        answers["datasets"][t][fld] = val
                        changed += 1
            continue
        scope, fld = (parts[0], parts[1]) if len(parts) == 2 else ("shared", parts[0])
        if fld not in FIELDS:
            problems.append(f"unknown field '{fld}'")
            continue
        targets = keys if scope == "all" else [scope]
        try:
            value = parse_value(fld, raw)
        except (ValueError, json.JSONDecodeError) as err:
            problems.append(f"{name}: {err}")
            continue
        if op == "+=" and not isinstance(value, list):
            problems.append(f"{name}: += only adds to lists (themes, keywords, landscapes, geography, contact)")
            continue
        bad = check_value(fld, value, voc)
        if bad:  # nothing invalid is stored
            problems += [f"{name}: {p}" for p in bad]
            continue
        for t in targets:
            if t != "shared" and t not in answers["datasets"]:
                problems.append(f"no dataset {t}")
                continue
            box = answers["shared"] if t == "shared" else answers["datasets"][t]
            if op == "+=" and isinstance(value, list):
                box[fld] = list(box.get(fld) or []) + [v for v in value if v not in (box.get(fld) or [])]
            elif value is None:
                box.pop(fld, None)
            else:
                box[fld] = value
            changed += 1
    save_answers(work, answers)
    say(f"ok: {changed} value(s) set")
    for p in problems:
        say(f"! {p}")
    return 1 if problems else 0


# -- merge answers + facts into records -------------------------------------------------------------
def merged(answers: Dict[str, Any], key: str) -> Dict[str, Any]:
    out = dict(answers["shared"])
    out.update({k: v for k, v in answers["datasets"].get(key, {}).items() if v not in (None, "", [])})
    return out


def parse_temporal(text: Any) -> Dict[str, Any]:
    t = str(text).strip()
    if ".." in t:
        a, b = (x.strip() for x in t.split("..", 1))
        return {"start_date": a, "end_date": b or None}
    return {"date": t}


def access_method_for(url: str) -> str:
    u = url.lower()
    if u.startswith("mailto:"):
        return "request"
    if re.search(r"(service=wms|service=wfs|/wms\b|/wfs\b|arcgis/rest|/ows\b|/tiles/|\{z\})", u):
        return "service"
    if u.split("?")[0].endswith(DOWNLOAD_EXT) or "/download" in u or "releases/download" in u:
        return "download"
    return "landing_page"


def build_record(d: Dict[str, Any], a: Dict[str, Any], rid: str, voc: Dict[str, Any]) -> Dict[str, Any]:
    f = d["facts"]
    derived: List[str] = []
    kind = f.get("kind") if f.get("kind") in ("raster", "vector", "tabular", "document", "mixed") else "other"
    rec: Dict[str, Any] = {"schema_version": STANDARD_VERSION, "id": rid}
    rec["title"] = a.get("title")
    rec["description"] = a.get("description")
    rec["resource_type"] = a.get("resource_type") or ("document" if kind == "document" else "dataset")
    rec["themes"] = a.get("themes")
    if a.get("keywords"):
        rec["keywords"] = a["keywords"]
    spatial: Dict[str, Any] = {}
    lands = a.get("landscapes") or []
    geo = a.get("geography") or sorted({c for code in lands for c in voc["landscapes"].get(code, ([], None))[0]})
    if geo:
        spatial["geography"] = geo
    if lands:
        spatial["landscapes"] = lands
    if f.get("bbox"):
        spatial["bbox"] = f["bbox"]
        derived.append("spatial.bbox")
    if f.get("crs"):
        spatial["crs"] = f["crs"]
        derived.append("spatial.crs")
    res = a.get("resolution")
    if res:
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(m|km|degree|arcsec|arcmin)s?\s*$", str(res))
        spatial["resolution"] = {"value": float(m.group(1)), "unit": m.group(2)} if m else {"text": str(res)}
    elif f.get("resolution") and f["resolution"].get("value"):
        spatial["resolution"] = f["resolution"]
        derived.append("spatial.resolution")
    if spatial:
        rec["spatial"] = spatial
    temporal: Dict[str, Any] = {}
    if a.get("temporal"):
        temporal = parse_temporal(a["temporal"])
    elif f.get("time"):
        temporal = {"start_date": f["time"]["start"], "end_date": f["time"]["end"]}
        if temporal["start_date"] == temporal["end_date"]:
            temporal = {"date": temporal["start_date"]}
        derived += [f"temporal.{k}" for k in temporal]
    if a.get("update_frequency"):
        temporal["update_frequency"] = a["update_frequency"]
    if temporal:
        rec["temporal"] = temporal
    rec["license"] = a.get("license")
    if a.get("license_text"):
        rec["license_text"] = a["license_text"]
    rec["access"] = a.get("access")
    if a.get("access") in ("restricted", "non-public"):
        rec["access_note"] = a.get("access_note")
    rec["contact"] = [{k: v for k, v in c.items() if v} for c in a.get("contact") or []] or None
    if a.get("citation"):
        rec["citation"] = {"text": a["citation"]}
    if a.get("doi"):
        rec["doi"] = re.sub(r"^https?://(dx\.)?doi\.org/", "", a["doi"])
    if a.get("version"):
        rec["version"] = str(a["version"])
    if a.get("license_url"):
        rec["additional_links"] = [{"rel": "license", "url": a["license_url"]}]
    # the data entry
    entry: Dict[str, Any] = {"name": d["label"]}
    url = a.get("url")
    method = a.get("access_method") or (access_method_for(url) if url else "request")
    if url:
        entry["locations"] = [{"url": url}]
    entry["access_method"] = method
    entry["kind"] = kind
    derived.append("data[].kind")
    fmt = f.get("format")
    if method == "download":
        if f.get("media_type") and len(d["files"]) == 1:
            entry["media_type"] = f["media_type"]
            derived.append("data[].media_type")
        entry["file_size"] = human_size(d["size"]).replace(".0 ", " ")
        derived.append("data[].file_size")
    if f.get("geometry_type") and kind in ("vector", "mixed"):
        entry["geometry_type"] = f["geometry_type"]
        derived.append("data[].geometry_type")
    if isinstance(f.get("feature_count"), int) and kind in ("vector", "tabular"):
        entry["feature_count"] = f["feature_count"]
        derived.append("data[].feature_count")
    files = d["files"]
    desc = f"{fmt}, {len(files)} file(s), {human_size(d['size'])}" if fmt else f"{len(files)} file(s)"
    if len(files) > 1:
        desc += f": {Path(files[0]).name} … {Path(files[-1]).name}"
    entry["description"] = desc
    structures = []
    layers = f.get("layers") or [
        {"name": None, "variables": f.get("variables"), "geometry_column": f.get("geometry_column")}
    ]
    for lay in layers:
        st: Dict[str, Any] = {"name": f"{d['label']}: {lay['name']}" if lay.get("name") else d["label"]}
        if lay.get("variables"):
            st["variables"] = [
                {k: v for k, v in var.items() if v not in (None, "")} for var in lay["variables"] if var.get("name")
            ]
        if not lay.get("name") and f.get("dimensions"):
            st["dimensions"] = f["dimensions"]
        if lay.get("geometry_column"):
            st["geometry_column"] = lay["geometry_column"]
        if len(st) > 1:
            structures.append(st)
    if structures:
        entry["structures"] = [s["name"] for s in structures]
        rec["structures"] = structures
        derived.append("structures")
    rec["data"] = [entry]
    rec["derived"] = sorted(set(derived))
    return {k: v for k, v in rec.items() if v not in (None, [], {}, "")}


def gaps(rec: Dict[str, Any], voc: Dict[str, Any]) -> List[str]:
    """What the MOSAIC minimum level still needs (same rules as the catalogue's validator)."""
    out = [f for f in ("title", "description", "themes", "license", "access", "contact") if not rec.get(f)]
    if rec.get("themes"):
        out += [f"theme '{t}' unknown" for t in rec["themes"] if t not in voc["themes"]]
    contacts = rec.get("contact") or []
    if contacts and not any("licensor" in (c.get("roles") or []) for c in contacts):
        out.append("contact with role licensor")
    if any(not c.get("organization") for c in contacts):
        out.append("contact organization")
    if any(not c.get("roles") for c in contacts):
        out.append("contact roles")
    if rec.get("access") == "public" and not any(e.get("locations") for e in rec.get("data", [])):
        out.append("url (public data needs a link where it can be obtained)")
    if rec.get("access") in ("restricted", "non-public") and not rec.get("access_note"):
        out.append("access_note (how to obtain it)")
    if str(rec.get("license", "")).startswith("LicenseRef-") and not (
        rec.get("license_text") or rec.get("additional_links")
    ):
        out.append("license_text or license_url")
    return out


def recommended(rec: Dict[str, Any]) -> List[str]:
    out = []
    sp = rec.get("spatial") or {}
    if not sp.get("landscapes"):
        out.append("landscapes")
    if not sp.get("bbox"):
        out.append("bbox (unknown from the files)")
    if not rec.get("temporal"):
        out.append("temporal")
    return out


def sug_text(k: str, v: Any) -> str:
    if k == "contact":
        return "contact(metadata)=" + short([c.get("organization") for c in v])
    if k == "keywords":
        return f"keywords={short(v[:3])}" + ("…" if len(v) > 3 else "")
    return f"{k}={short(v)}"


def print_status(
    work: Path, scan: Dict[str, Any], answers: Dict[str, Any], voc: Dict[str, Any], header: bool = True
) -> None:
    if header:
        say(f"{len(scan['datasets'])} dataset(s) from {scan['folder']}")
    shared_missing = [f for f in ("contact", "license", "access") if not answers["shared"].get(f)]
    rows = []
    for d in scan["datasets"]:
        a = merged(answers, d["key"])
        if a.get("skip"):
            continue
        miss = [m for m in gaps(build_record(d, a, "x", voc), voc) if m not in shared_missing]
        sug = {k: v for k, v in d["suggest"].items() if a.get(k) in (None, "", [])}
        rows.append((d["key"], miss, sug))
    common = [m for m in (rows[0][1] if rows else []) if all(m in r[1] for r in rows)] if len(rows) > 1 else []
    if shared_missing:
        extra = " + url or how to request it" if "access" in shared_missing else ""
        say("Ask once for all datasets: " + ", ".join(shared_missing) + extra)
    if common:
        say("Each dataset needs: " + ", ".join(common))
    done = []
    for key, miss, sug in rows:
        per = [m for m in miss if m not in common]
        if not per and not sug:
            done.append(key)
            continue
        bits = [key] + (["needs: " + ", ".join(per)] if per else [])
        if sug:
            bits.append("sug: " + "; ".join(sug_text(k, v) for k, v in sug.items()))
        say(" | ".join(bits))
    if done and not common and not shared_missing:
        say("Nothing missing: " + ",".join(done))
    if any("theme" in m for r in rows for m in r[1]):
        say("Themes: " + " ".join(voc["themes"]))
    if any(
        not (merged(answers, d["key"]).get("landscapes") or d["suggest"].get("landscapes")) for d in scan["datasets"]
    ):
        say("Landscapes: " + " ".join(voc["landscapes"]))


def short(v: Any) -> str:
    if isinstance(v, list):
        return "[" + ",".join(short(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(f"{k}:{short(x)}" for k, x in v.items()) + "}"
    s = str(v).replace("\n", " ")
    return f'"{s[:70]}…"' if len(s) > 70 else (f'"{s}"' if " " in s else s)


def cmd_status(args: argparse.Namespace, work: Path) -> int:
    scan = load_json(work / "scan.json")
    if not scan:
        say("run scan first")
        return 2
    print_status(work, scan, load_answers(work), vocab(work))
    return 0


def official_validator(work: Path) -> Optional[str]:
    """The catalogue's own validator, when the mosaic-standard tool is installed (summary only)."""
    try:
        import mosaic_catalog  # noqa: F401
    except ImportError:
        return None
    cmd = [sys.executable, "-m", "mosaic_catalog", "--catalog", str(work), "validate", "--format", "json"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        reports = json.loads(res.stdout)
    except ValueError:
        return (res.stderr or res.stdout).strip()[-600:] or f"exit {res.returncode}"
    states: Dict[str, int] = {}
    lines = []
    for r in reports:
        states[r["status"]] = states.get(r["status"], 0) + 1
        msgs = [i["message"] for i in r.get("issues", []) if i.get("level") in ("structure", "minimum")]
        if msgs:
            lines.append(f"{r['id']} {r['status']}: " + "; ".join(m[:120] for m in msgs[:3]))
    head = f"{len(reports)} checked: " + ", ".join(f"{n} {k}" for k, n in sorted(states.items()))
    return "\n  ".join([head, *lines[:20]])


def structure_check(work: Path, recs: Dict[str, Dict[str, Any]]) -> str:
    """The record schema with jsonschema, for whoever does not have the mosaic-standard tool."""
    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError:
        return "structure: not checked here (pip install jsonschema); the catalogue checks it on submission"
    base = f"{PAGES}/schema/v{STANDARD_VERSION}/"
    schema = fetch_json(base + "record.schema.json", work / ".cache/record.schema.json", 7)
    vocab_schema = fetch_json(base + "vocab.schema.json", work / ".cache/vocab.schema.json", 7)
    if not schema or not vocab_schema:
        return "structure: not checked (schema not reachable)"
    try:
        reg = Registry().with_resources([(base + n, Resource.from_contents(c)) for n, c in
                                          (("record.schema.json", schema), ("vocab.schema.json", vocab_schema))])  # fmt: skip
        val = jsonschema.Draft202012Validator(schema, registry=reg)
        errs = []
        for rid, rec in recs.items():
            for e in sorted(val.iter_errors(rec), key=lambda e: list(e.path))[:5]:
                errs.append(f"{rid} {'.'.join(str(p) for p in e.path)}: {e.message[:140]}")
    except Exception as err:
        return f"structure: not checked ({err.__class__.__name__})"
    return "structure: ok" if not errs else "structure problems:\n  " + "\n  ".join(errs[:15])


def cmd_build(args: argparse.Namespace, work: Path) -> int:
    scan = load_json(work / "scan.json")
    if not scan:
        say("run scan first")
        return 2
    answers = load_answers(work)
    voc = vocab(work)
    out = work / "records"
    if out.exists():
        for p in out.glob("NEW-*"):
            shutil.rmtree(p)
    out.mkdir(parents=True, exist_ok=True)
    recs: Dict[str, Dict[str, Any]] = {}
    index = []
    n = 0
    for d in scan["datasets"]:
        a = merged(answers, d["key"])
        if a.get("skip"):
            continue
        n += 1
        rid = f"NEW-{n:02d}"
        rec = build_record(d, a, rid, voc)
        recs[rid] = rec
        write_record(out / rid / "record.yaml", rec, scan["folder"])
        miss = gaps(rec, voc)
        index.append({"id": rid, "key": d["key"], "title": rec.get("title"), "kind": rec["data"][0]["kind"],
                      "landscapes": (rec.get("spatial") or {}).get("landscapes", []), "missing": miss,
                      "recommended": recommended(rec), "record": rec})  # fmt: skip
    (work / "records" / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    say(f"Built {len(recs)} record(s) in {out}")
    for r in index:
        state = "complete" if not r["missing"] else "missing: " + ", ".join(r["missing"])
        extra = f" (could add: {', '.join(r['recommended'])})" if r["recommended"] and not r["missing"] else ""
        say(f"{r['id']} {r['key']} {short(r['title'] or '(no title)')} {r['kind']} — {state}{extra}")
    say(structure_check(work, recs))
    off = official_validator(work)
    if off:
        say("MOSAIC validator:\n  " + off)
    if all(not r["missing"] for r in index):
        say("Ready. Show the person this list, then: submit --github (pull request) or submit --bundle (zip).")
    else:
        say("Fill the missing values with `set`, then build again.")
    return 0


def write_record(p: Path, rec: Dict[str, Any], folder: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    head = (f"# MOSAIC record (standard v{STANDARD_VERSION}), prepared with mosaic-contribute from the folder '{folder}'.\n"
            "# Fields listed in `derived` were read from the files; the rest was given by the contributor.\n")  # fmt: skip
    p.write_text(head + to_yaml(rec) + "\n", encoding="utf-8")


# -- submit ---------------------------------------------------------------------------------------------
def run(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> str:
    res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {(res.stderr or res.stdout).strip()[:400]}")
    return res.stdout.strip()


def next_ids(records_dir: Path, n: int) -> List[str]:
    year = date.today().year
    nums = [
        int(m.group(1)) for p in records_dir.glob(f"MFL-{year}-*") if (m := re.match(rf"MFL-{year}-(\d+)$", p.name))
    ]
    start = max(nums) + 1 if nums else 1
    return [f"MFL-{year}-{i:03d}" for i in range(start, start + n)]


def load_built(work: Path) -> Tuple[list, Dict[str, Dict[str, Any]]]:
    index = load_json(work / "records" / "index.json", [])
    recs = {r["id"]: r.pop("record") for r in index}
    return index, recs


def pr_body(index: list, ids: Dict[str, str], folder: str) -> str:
    rows = "\n".join(f"| {ids.get(r['id'], r['id'])} | {r['title']} | {r['kind']} | {', '.join(r['landscapes']) or '-'} | "
                     f"{'complete' if not r['missing'] else 'incomplete: ' + ', '.join(r['missing'])} |" for r in index)  # fmt: skip
    return (f"Adds {len(index)} dataset record(s) from the contributor's folder `{folder}`.\n\n"
            "| ID | Title | Kind | Living landscapes | Minimum level |\n|---|---|---|---|---|\n"
            f"{rows}\n\nPrepared with the `mosaic-contribute` skill (MOSAIC-mfl/mosaic-skills): the fields listed in each "
            "record's `derived` were read from the files; everything else was given by the contributor. The data files "
            "are not part of this pull request (MOSAIC links to where the data lives).\n")  # fmt: skip


def cmd_submit(args: argparse.Namespace, work: Path) -> int:
    index, recs = load_built(work)
    if not index:
        say("nothing built: run build first")
        return 2
    built = (work / "records" / "index.json").stat().st_mtime
    if any((work / n).exists() and (work / n).stat().st_mtime > built for n in ("scan.json", "answers.json")):
        say("the scan or the answers changed after the last build: run build first")
        return 1
    incomplete = [r["id"] for r in index if r["missing"]]
    if incomplete and not args.allow_incomplete:
        say(f"incomplete: {', '.join(incomplete)}. Fill them (set + build) or pass --allow-incomplete.")
        return 1
    folder = (load_json(work / "scan.json") or {}).get("folder", "folder")
    if args.bundle:
        out = work / f"mosaic-submission-{date.today().isoformat()}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for r in index:
                z.write(work / "records" / r["id"] / "record.yaml", f"records/{r['id']}/record.yaml")
            z.writestr("SUBMISSION.md", "# MOSAIC submission\n\n" + pr_body(index, {}, folder)
                       + "\nFor the MOSAIC team: give each NEW-NN record the next free MFL id, then open the pull request.\n")  # fmt: skip
        say(f"Bundle: {out}", f"Send it to the MOSAIC team (contact on {CONTACT_PAGE}). The data files stay with you.")
        return 0
    if not shutil.which("gh") or not shutil.which("git"):
        say("git and the GitHub CLI (gh) are needed for a pull request; or use --bundle.")
        return 2
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        say("GitHub CLI not logged in: run `gh auth login` (the person does it), or use --bundle.")
        return 2
    login = run(["gh", "api", "user", "--jq", ".login"])
    can_push = run(["gh", "api", f"repos/{CATALOG_REPO}", "--jq", ".permissions.push"], check=False) == "true"
    clone = work / "_catalog"
    if clone.exists():
        shutil.rmtree(clone)
    run(["gh", "repo", "clone", CATALOG_REPO, str(clone), "--", "--depth", "1", "--quiet"])
    ids = dict(zip([r["id"] for r in index], next_ids(clone / "records", len(index))))
    slug = re.sub(r"[^a-z0-9]+", "-", (index[0]["title"] or folder).lower()).strip("-")
    slug = slug if len(slug) <= 30 else slug[:30].rsplit("-", 1)[0]
    branch = f"add-datasets-{date.today().strftime('%Y%m%d')}-{slug}"
    first = index[0]["title"] or "dataset"
    title = (
        f"Add dataset: {first}" if len(index) == 1 else f"Add {len(index)} datasets: {first} and {len(index) - 1} more"
    )
    if args.dry_run:
        say(f"Would open a pull request on {CATALOG_REPO} from {login}:{branch}" + ("" if can_push else " (via a fork)"),
            f"Title: {title}", *[f"  {new} <- {old}" for old, new in ids.items()])  # fmt: skip
        return 0
    remote = "origin"
    if not can_push:
        run(["gh", "repo", "fork", "--remote", "--remote-name", "fork"], cwd=clone)
        remote = "fork"
    run(["git", "switch", "-c", branch], cwd=clone)
    for old, new in ids.items():
        rec = recs[old]
        rec["id"] = new
        write_record(clone / "records" / new / "record.yaml", rec, folder)
    name = run(["git", "config", "user.name"], cwd=clone, check=False)
    email = run(["git", "config", "user.email"], cwd=clone, check=False)
    who = [] if name and email else ["-c", f"user.name={login}", "-c", f"user.email={login}@users.noreply.github.com"]
    run(["git", "add", "records"], cwd=clone)
    run(["git", *who, "commit", "-q", "-m", title], cwd=clone)
    run(
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=!gh auth git-credential",
            "push",
            "-q",
            "-u",
            remote,
            branch,
        ],
        cwd=clone,
    )
    body = work / "_pr_body.md"
    body.write_text(pr_body(index, ids, folder), encoding="utf-8")
    url = run(["gh", "pr", "create", "--repo", CATALOG_REPO, "--base", "main", "--head", f"{login}:{branch}",
               "--title", title, "--body-file", str(body)], cwd=clone)  # fmt: skip
    say(f"Pull request: {url}", "The catalogue's Validate check runs on it; a MOSAIC maintainer reviews and merges.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="mosaic_contribute", description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", default="mosaic-contribution", help="work folder (default ./mosaic-contribution)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="read the folder and list the datasets")
    s.add_argument("folder")
    s.add_argument("--per-folder", action="store_true", help="one dataset per subfolder")
    s.add_argument("--no-series", action="store_true", help="never group numbered files into one dataset")
    s.add_argument("--docs", action="store_true", help="catalogue documents (PDF, DOCX...) as records too")
    st = sub.add_parser("set", help="record answers: KEY=VALUE, KEY+=VALUE, accept[=all|d01,..], dNN.accept[=fields]")
    st.add_argument("pairs", nargs="+")
    sub.add_parser("status", help="what is still needed")
    sub.add_parser("build", help="write the records and check them")
    sb = sub.add_parser("submit", help="send the built records")
    g = sb.add_mutually_exclusive_group(required=True)
    g.add_argument("--github", action="store_true", help="pull request to MOSAIC-mfl/catalog (needs gh)")
    g.add_argument("--bundle", action="store_true", help="zip to send to the MOSAIC team")
    sb.add_argument("--dry-run", action="store_true")
    sb.add_argument("--allow-incomplete", action="store_true")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # a Windows console must not stop on a title in another script
        sys.stdout.reconfigure(errors="replace")
    work = Path(args.work).expanduser().resolve()
    cmds = {"scan": cmd_scan, "set": cmd_set, "status": cmd_status, "build": cmd_build, "submit": cmd_submit}
    try:
        return cmds[args.cmd](args, work)
    except RuntimeError as err:
        say(f"! {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
