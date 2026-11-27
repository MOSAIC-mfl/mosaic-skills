"""Read what data files say about themselves, with the Python standard library only.

Every reader takes a path and returns a ``Facts``: values read from INSIDE the file (kind, format, CRS,
extent, resolution, geometry, row/feature counts, variables, the time axis) and, separately, the
metadata its producer wrote in it or beside it (``meta``: title, abstract, keywords, licence,
organization). Facts go into the record as derived values; ``meta`` is only ever offered to the person
as a suggestion.

Read natively: GeoTIFF (+ world files), ESRI ASCII grid, GDAL VRT, NetCDF classic, Shapefile, GeoJSON,
GeoPackage, KML/KMZ, CSV/TSV, XLSX, ZIP of any of these, ISO/ESRI/FGDC/QGIS metadata XML sidecars.
Used when installed (never required): pyproj (any CRS to WGS84), rasterio (other rasters), pyogrio or
fiona (other vectors, File Geodatabase), netCDF4 or h5py (NetCDF-4/HDF5), pyarrow (Parquet).
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import math
import re
import sqlite3
import struct
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional

Facts = Dict[str, Any]

LAT_NAMES = {"lat", "latitude", "lat_dd", "y_lat", "decimallatitude", "latitud", "lat_deg", "gps_latitude"}
LON_NAMES = {"lon", "long", "lng", "longitude", "lon_dd", "x_lon", "decimallongitude", "longitud", "gps_longitude"}
GEOM_NAMES = {"wkt", "geometry", "geom", "the_geom", "wkb_geometry", "geojson"}
MAX_PARSE = 300 * 1000 * 1000  # bytes: larger GeoJSON/KML/CSV files are only partly read
SAMPLE_ROWS = 5000


def new_facts(kind: str, fmt: str, media_type: Optional[str] = None) -> Facts:
    return {"kind": kind, "format": fmt, "media_type": media_type, "problems": [], "meta": {}}


# -- coordinate reference systems --------------------------------------------------------------------
WEB_MERCATOR = {3857, 900913, 3785, 102100, 102113}
UTM_FAMILIES = [  # (first EPSG, first zone, south)
    (32601, 1, False), (32701, 1, True), (32201, 1, False), (32301, 1, True),  # WGS 84, WGS 72
    (26901, 1, False), (26701, 1, False),  # NAD83, NAD27 (north)
    (31965, 11, False), (31977, 17, True),  # SIRGAS 2000
    (24817, 17, False), (24877, 17, True),  # PSAD56
    (21095, 35, False), (21035, 35, True),  # Arc 1960
    (20135, 35, False),  # Adindan
    (32628, 28, False),
]  # fmt: skip
UTM_FAMILY_SIZE = {32601: 60, 32701: 60, 32201: 60, 32301: 60, 26901: 23, 26701: 22, 31965: 12, 31977: 9,
                   24817: 5, 24877: 6, 21095: 3, 21035: 3, 20135: 4, 32628: 1}  # fmt: skip


def utm_from_epsg(code: int) -> Optional[tuple]:
    for first, zone0, south in UTM_FAMILIES:
        if first <= code < first + UTM_FAMILY_SIZE[first]:
            return zone0 + code - first, south
    return None


def utm_from_text(text: str) -> Optional[tuple]:
    m = re.search(r"UTM[ _]?zone[ _]?(\d{1,2})\s*([NS])?", text or "", re.I)
    if not m:
        return None
    south = (m.group(2) or "").upper() == "S" or bool(re.search(r"southern hemisphere|_south\b", text, re.I))
    return int(m.group(1)), south


def utm_to_lonlat(x: float, y: float, zone: int, south: bool) -> tuple:
    """UTM (WGS 84 ellipsoid; other datums differ by metres, enough for a discovery extent) to lon/lat."""
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    x -= 500000.0
    if south:
        y -= 10000000.0
    mu = y / k0 / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    n1 = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    t1 = math.tan(p) ** 2
    c1 = ep2 * math.cos(p) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(p) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = p - (n1 * math.tan(p) / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720
    )
    lon = (
        d - (1 + 2 * t1 + c1) * d**3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120
    ) / math.cos(p)
    return math.degrees(math.radians((zone - 1) * 6 - 177) + lon), math.degrees(lat)


GEOG_NAMES = [(r"WGS[ _]?(19)?84", 4326), (r"SIRGAS[ _]?2000", 4674), (r"NAD[ _]?(19)?83", 4269), (r"ETRS[ _]?(19)?89", 4258),
              (r"Arc[ _]?1960", 4210), (r"Adindan", 4201), (r"PSAD[ _]?(19)?56", 4248), (r"MAGNA", 4686),
              (r"WGS[ _]?(19)?72", 4322), (r"Indian[ _]?1975", 4240), (r"GDA[ _]?(19)?94", 4283)]  # fmt: skip


def crs_from_wkt(wkt: str) -> Dict[str, Any]:
    """{'code': 'EPSG:n' or None, 'name': str, 'geographic': bool, 'utm': (zone, south) or None}."""
    wkt = (wkt or "").strip()
    out: Dict[str, Any] = {"code": None, "name": None, "geographic": False, "utm": None}
    if not wkt:
        return out
    head = re.match(r"\s*(\w+)\s*\[\s*\"([^\"]*)\"", wkt)
    if head:
        out["name"] = head.group(2)
        out["geographic"] = head.group(1).upper() in ("GEOGCS", "GEOGCRS", "GEOGRAPHICCRS")
    # the root's own authority closes the string: ...,AUTHORITY["EPSG","32718"]]
    root_id = re.search(r"(?:AUTHORITY|ID)\[\s*\"(EPSG|ESRI)\"\s*,\s*\"?(\d+)\"?\s*\]\s*\]\s*$", wkt, re.I)
    if root_id:
        out["code"] = f"{root_id.group(1).upper()}:{root_id.group(2)}"
    name = out["name"] or ""
    if not out["code"]:
        if out["geographic"]:
            for pat, num in GEOG_NAMES:
                if re.search(pat, name, re.I):
                    out["code"] = f"EPSG:{num}"
                    break
        elif re.search(r"web[ _]mercator|pseudo[ _-]mercator|popular visualisation", name, re.I):
            out["code"] = "EPSG:3857"
    out["utm"] = utm_from_text(name)
    if out["utm"] and not out["code"] and re.search(r"WGS[ _]?(19)?84", wkt, re.I):
        zone, south = out["utm"]
        out["code"] = f"EPSG:{(32700 if south else 32600) + zone}"
    return out


def to_wgs84_bbox(xs: List[float], ys: List[float], crs: Dict[str, Any]) -> Optional[List[float]]:
    """Extent of the points (x, y) in WGS 84, or None when the CRS cannot be converted here."""
    if not xs or not ys:
        return None
    code = crs.get("code") or ""
    num = int(code.split(":")[1]) if re.match(r"^(EPSG|ESRI):\d+$", code) else None
    lon: List[float]
    lat: List[float]
    if crs.get("geographic") or num in (4326, 4269, 4258, 4674, 4167, 4283, 4618, 4148, 4210, 4201, 4248, 4686):
        lon, lat = list(xs), list(ys)
    elif num in WEB_MERCATOR:
        r = 6378137.0
        lon = [math.degrees(x / r) for x in xs]
        lat = [math.degrees(2 * math.atan(math.exp(y / r)) - math.pi / 2) for y in ys]
    else:
        utm = crs.get("utm") or (utm_from_epsg(num) if num else None)
        if utm:
            pts = [utm_to_lonlat(x, y, utm[0], utm[1]) for x, y in zip(xs, ys)]
        else:
            pts = _pyproj(xs, ys, crs)
            if pts is None:
                return None
        lon, lat = [p[0] for p in pts], [p[1] for p in pts]
    if any(math.isnan(v) or math.isinf(v) for v in lon + lat):
        return None
    if min(lat) < -90.001 or max(lat) > 90.001 or min(lon) < -180.001 or max(lon) > 360.001:
        return None
    if max(lon) > 180:  # 0..360 longitudes
        lon = [v - 360 if v > 180 else v for v in lon]
    w, e = max(min(lon), -180.0), min(max(lon), 180.0)
    s, n = max(min(lat), -90.0), min(max(lat), 90.0)
    return [round(w, 5), round(s, 5), round(e, 5), round(n, 5)]


def _pyproj(xs: List[float], ys: List[float], crs: Dict[str, Any]) -> Optional[list]:
    src = crs.get("code") or crs.get("wkt")
    if not src:
        return None
    try:
        from pyproj import Transformer

        t = Transformer.from_crs(src, "EPSG:4326", always_xy=True)
        return [t.transform(x, y) for x, y in zip(xs, ys)]
    except Exception:
        return None


def box_points(w: float, s: float, e: float, n: float) -> tuple:
    """Corners and edge midpoints of a box (enough to reproject its extent)."""
    mx, my = (w + e) / 2, (s + n) / 2
    return [w, e, w, e, mx, mx, w, e], [s, s, n, n, s, n, my, my]


def set_extent(f: Facts, xs: List[float], ys: List[float], crs: Dict[str, Any]) -> None:
    if crs.get("code"):
        f["crs"] = crs["code"]
    elif crs.get("name"):
        f["crs_name"] = crs["name"]
    if not xs:
        return
    bbox = to_wgs84_bbox(xs, ys, crs)
    if bbox:
        f["bbox"] = bbox
    elif crs.get("code") or crs.get("name"):
        f["problems"].append(
            f"extent not converted to WGS 84 from {crs.get('code') or crs.get('name')} (install pyproj)"
        )
    else:
        f["problems"].append("no coordinate reference system: extent unknown")


def read_prj(path: Path) -> Dict[str, Any]:
    for p in (path.with_suffix(".prj"), path.with_suffix(".PRJ"), Path(str(path) + ".prj")):
        if p.exists():
            wkt = p.read_text(errors="replace")
            crs = crs_from_wkt(wkt)
            crs["wkt"] = wkt
            return crs
    return {}


# -- metadata written by the producer ---------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(el: ET.Element) -> str:
    return " ".join(t.strip() for t in el.itertext() if t and t.strip())


META_TAGS = {
    "title": ("restitle", "title"),
    "abstract": ("idabs", "abstract", "description", "purpose", "idpurp"),
    "keywords": ("keyword", "themekey", "placekey"),
    "license": ("uselimit", "useconst", "otherconstraints", "license", "licence", "rights", "uselimitation"),
    "organization": ("rporgname", "organisationname", "organizationname", "cntorg", "organization"),
    "email": ("eMailAdd", "electronicmailaddress", "cntemail", "email"),
    "name": ("rpindname", "individualname", "cntper", "name"),
}


def read_meta_xml(path: Path) -> Dict[str, Any]:
    """Title, abstract, keywords, licence and organization from an ISO 19115/19139, ESRI, FGDC or QGIS
    (.qmd) metadata file. Unknown layouts give what their tag names match; nothing else is guessed."""
    try:
        root = ET.parse(str(path)).getroot()  # noqa: S314 - local metadata file chosen by the person
    except (ET.ParseError, OSError):
        return {}
    found: Dict[str, Any] = {}
    keywords: List[str] = []
    for el in root.iter():
        tag = _local(el.tag)
        txt = _text(el)
        if not txt or len(txt) > 4000:
            continue
        for key, tags in META_TAGS.items():
            if tag in (t.lower() for t in tags):
                if key == "keywords":
                    keywords.extend(k.strip() for k in re.split(r"[;,]", txt) if k.strip())
                elif key == "title" and found.get("title"):
                    pass  # the first title is the resource's own (later ones are citations, thesauri)
                elif key == "name" and tag == "name":
                    pass  # too generic outside contact blocks
                elif key not in found and not txt.startswith("<"):
                    found[key] = re.sub(r"\s+", " ", txt)
    if keywords:
        found["keywords"] = list(dict.fromkeys(keywords))[:20]
    return {k: v for k, v in found.items() if v}


def sidecar_meta(path: Path) -> Dict[str, Any]:
    stem = path.name.split(".")[0]
    for p in (
        Path(str(path) + ".xml"),
        path.with_suffix(".xml"),
        path.with_suffix(".qmd"),
        path.parent / f"{stem}.xml",
    ):
        if p.exists() and p != path and not p.name.endswith(".aux.xml"):
            meta = read_meta_xml(p)
            if meta:
                meta["source"] = p.name
                return meta
    return {}


# -- rasters ---------------------------------------------------------------------------------------
TIFF_TYPES = {1: "B", 2: "s", 3: "H", 4: "I", 5: "II", 6: "b", 7: "B", 8: "h", 9: "i", 10: "ii", 11: "f",
              12: "d", 16: "Q", 17: "q", 18: "Q"}  # fmt: skip
TIFF_WANTED = {256, 257, 258, 270, 277, 322, 339, 33550, 33922, 34264, 34735, 34736, 34737, 42112, 42113}


def _tiff_tags(path: Path) -> Dict[int, Any]:
    tags: Dict[int, Any] = {}
    with path.open("rb") as fh:
        head = fh.read(16)
        if head[:2] not in (b"II", b"MM"):
            return tags
        bo = "<" if head[:2] == b"II" else ">"
        magic = struct.unpack(bo + "H", head[2:4])[0]
        big = magic == 43
        if magic not in (42, 43):
            return tags
        ifd = struct.unpack(bo + ("Q" if big else "I"), head[8:16] if big else head[4:8])[0]
        fh.seek(ifd)
        n = struct.unpack(bo + ("Q" if big else "H"), fh.read(8 if big else 2))[0]
        size = 20 if big else 12
        raw = fh.read(n * size)
        for i in range(n):
            e = raw[i * size : (i + 1) * size]
            if big:
                tag, typ, count = struct.unpack(bo + "HHQ", e[:12])
                val = e[12:20]
            else:
                tag, typ, count = struct.unpack(bo + "HHI", e[:8])
                val = e[8:12]
            if tag not in TIFF_WANTED or typ not in TIFF_TYPES:
                continue
            fmt = TIFF_TYPES[typ]
            nbytes = struct.calcsize(bo + fmt) * count
            if nbytes > 1_000_000:
                continue
            if nbytes <= len(val):
                data = val[:nbytes]
            else:
                pos = fh.tell()
                fh.seek(struct.unpack(bo + ("Q" if big else "I"), val)[0])
                data = fh.read(nbytes)
                fh.seek(pos)
            if fmt == "s":
                tags[tag] = data.split(b"\0")[0].decode("latin-1")
            else:
                vals = struct.unpack(bo + fmt * count, data)
                if fmt in ("II", "ii"):
                    vals = tuple(vals[j] / vals[j + 1] if vals[j + 1] else 0 for j in range(0, len(vals), 2))
                tags[tag] = vals
    return tags


def _geokeys(tags: Dict[int, Any]) -> Dict[int, Any]:
    d = tags.get(34735)
    keys: Dict[int, Any] = {}
    if not d or len(d) < 4:
        return keys
    doubles, ascii_ = tags.get(34736, ()), tags.get(34737, "")
    for i in range(d[3]):
        kid, loc, cnt, off = d[4 + 4 * i : 8 + 4 * i]
        if loc == 0:
            keys[kid] = off
        elif loc == 34737:
            keys[kid] = ascii_[off : off + cnt].rstrip("|")
        elif loc == 34736:
            keys[kid] = doubles[off : off + cnt]
    return keys


def _dtype(bits: int, fmt: int) -> Optional[str]:
    kind = {1: "uint", 2: "int", 3: "float", 6: "cfloat"}.get(fmt or 1)
    if kind is None or bits not in (8, 16, 32, 64):
        return None
    if kind == "float" and bits == 8:
        return None
    return f"{kind}{bits}"


def _world_file(path: Path) -> Optional[tuple]:
    ext = path.suffix.lower()
    cands = [path.with_suffix(ext[:2] + ext[-1] + "w"), path.with_suffix(ext + "w"), path.with_suffix(".wld")]
    for p in cands:
        if p.exists():
            try:
                v = [float(x) for x in p.read_text().split()[:6]]
                return tuple(v) if len(v) == 6 else None
            except ValueError:
                return None
    return None


def _gdal_metadata(xml: str) -> tuple:
    """(dataset items, {band index: {role/name: value}}) from the GDAL_METADATA tag."""
    ds: Dict[str, str] = {}
    bands: Dict[int, Dict[str, str]] = {}
    try:
        root = ET.fromstring(xml)  # noqa: S314 - tag text of a local file
    except ET.ParseError:
        return ds, bands
    for it in root.iter("Item"):
        name, val = it.get("name", ""), (it.text or "").strip()
        if it.get("sample") is not None:
            bands.setdefault(int(it.get("sample")), {})[(it.get("role") or name).lower()] = val
        else:
            ds[name.lower()] = val
    return ds, bands


def read_geotiff(path: Path) -> Facts:
    f = new_facts("raster", "GeoTIFF", "image/tiff; application=geotiff")
    try:
        tags = _tiff_tags(path)
    except (OSError, struct.error) as err:
        f["problems"].append(f"TIFF not readable ({err})")
        return f
    if 256 not in tags:
        return _rasterio(path, f) or f
    width, height = tags[256][0], tags[257][0]
    nb = tags.get(277, (1,))[0]
    bits = tags.get(258, (8,))[0]
    sfmt = tags.get(339, (1,))[0]
    keys = _geokeys(tags)
    if not keys:
        f["media_type"] = "image/tiff"
    # CRS
    model = keys.get(1024)
    citation = " ".join(str(keys.get(k, "")) for k in (1026, 3073, 2049))
    crs: Dict[str, Any] = {"code": None, "name": citation.strip() or None, "geographic": model == 2, "utm": None}
    code = keys.get(3072) if model == 1 else keys.get(2048) if model == 2 else keys.get(3072) or keys.get(2048)
    if isinstance(code, int) and 1024 <= code < 32767:
        crs["code"] = f"EPSG:{code}"
    crs["utm"] = utm_from_text(citation)
    if not keys:
        prj = read_prj(path)
        if prj:
            crs = prj
    # georeferencing
    ox = oy = sx = sy = None
    if 33922 in tags and 33550 in tags:
        i, j, _, x, y, _ = tags[33922][:6]
        sx, sy = tags[33550][0], tags[33550][1]
        ox, oy = x - i * sx, y + j * sy
    elif 34264 in tags:
        m = tags[34264]
        ox, sx, oy, sy = m[3], m[0], m[7], -m[5]
    else:
        wf = _world_file(path)
        if wf:
            sx, sy, ox, oy = wf[0], -wf[3], wf[4] - wf[0] / 2, wf[5] - wf[3] / 2
            f["format"] = "TIFF + world file"
    if ox is None:
        f["kind"] = "raster" if nb else "other"
        f["problems"].append("no georeferencing in the file")
    else:
        w, n = ox, oy
        e, s = ox + width * sx, oy - height * sy
        xs, ys = box_points(min(w, e), min(s, n), max(w, e), max(s, n))
        set_extent(f, xs, ys, crs)
        f["resolution"] = {"value": _round_sig(abs(sx)), "unit": "degree" if crs.get("geographic") else "m"}
    f["size_px"] = [width, height]
    # bands
    ds_meta, band_meta = _gdal_metadata(tags.get(42112, "")) if 42112 in tags else ({}, {})
    dtype = _dtype(bits, sfmt)
    nodata = tags.get(42113)
    f["variables"] = _band_variables(nb, dtype, nodata, band_meta)
    if nb > 12 and not band_meta:
        f["problems"].append(f"{nb} bands without names in the file")
    meta = {k: ds_meta[k] for k in ("title", "description", "license", "keywords") if ds_meta.get(k)}
    if tags.get(270) and len(tags[270]) < 500 and not tags[270].startswith("{"):
        meta.setdefault("description", tags[270])
    if meta:
        meta["source"] = "GeoTIFF tags"
        if "description" in meta:
            meta["abstract"] = meta.pop("description")
    f["meta"] = meta
    return f


def _band_variables(nb: int, dtype: Optional[str], nodata: Any, band_meta: Dict[int, Dict[str, str]]) -> list:
    out = []
    names_known = bool(band_meta)
    for b in range(min(nb, 12) if not names_known else nb):
        bm = band_meta.get(b, {})
        v: Dict[str, Any] = {"name": bm.get("description") or f"band_{b + 1}"}
        if dtype:
            v["data_type"] = dtype
        if bm.get("unittype"):
            v["unit"] = bm["unittype"]
        if nodata not in (None, ""):
            with contextlib.suppress(ValueError):
                v["nodata"] = float(nodata) if "." in str(nodata) or "e" in str(nodata).lower() else int(nodata)
        out.append(v)
    if nb > 12 and not names_known:  # one entry for many unnamed bands
        first = out[0]
        out = [{"name": "bands", "description": f"{nb} bands, not named in the file",
                **{k: first[k] for k in ("data_type", "nodata") if k in first}}]  # fmt: skip
    return out


def _round_sig(v: float, sig: int = 6) -> float:
    if v == 0:
        return 0.0
    return round(v, sig - math.floor(math.log10(abs(v))) - 1)


def read_ascii_grid(path: Path) -> Facts:
    f = new_facts("raster", "ESRI ASCII grid", "text/plain")
    head: Dict[str, float] = {}
    with path.open(errors="replace") as fh:
        for _ in range(7):
            parts = fh.readline().split()
            if len(parts) == 2 and re.match(r"^[a-zA-Z_]+$", parts[0]):
                try:
                    head[parts[0].lower()] = float(parts[1])
                except ValueError:
                    break
    if not {"ncols", "nrows", "cellsize"} <= set(head):
        f["problems"].append("ASCII grid header not found")
        return f
    cs = head["cellsize"]
    w = head.get("xllcorner", head.get("xllcenter", 0) - cs / 2)
    s = head.get("yllcorner", head.get("yllcenter", 0) - cs / 2)
    crs = read_prj(path)
    xs, ys = box_points(w, s, w + head["ncols"] * cs, s + head["nrows"] * cs)
    set_extent(f, xs, ys, crs)
    f["resolution"] = {"value": _round_sig(cs), "unit": "degree" if crs.get("geographic") else "m"}
    v: Dict[str, Any] = {"name": path.stem, "data_type": "number"}
    if "nodata_value" in head:
        v["nodata"] = head["nodata_value"]
    f["variables"] = [v]
    return f


def read_vrt(path: Path) -> Facts:
    f = new_facts("raster", "GDAL virtual raster (VRT)", "application/xml")
    try:
        root = ET.parse(str(path)).getroot()  # noqa: S314
    except ET.ParseError:
        f["problems"].append("VRT not readable")
        return f
    w, h = int(root.get("rasterXSize", 0)), int(root.get("rasterYSize", 0))
    srs = root.findtext("SRS") or ""
    crs = crs_from_wkt(srs) if srs.strip().startswith(("GEOG", "PROJ", "COMPD")) else {}
    if not crs.get("code") and re.match(r"^EPSG:\d+$", srs.strip()):
        crs = {
            "code": srs.strip(),
            "geographic": srs.strip() == "EPSG:4326",
            "utm": utm_from_epsg(int(srs.split(":")[1])),
        }
    gt = [float(x) for x in (root.findtext("GeoTransform") or "").replace(",", " ").split()]
    if len(gt) == 6:
        xs, ys = box_points(gt[0], gt[3] + h * gt[5], gt[0] + w * gt[1], gt[3])
        set_extent(f, xs, ys, crs)
        f["resolution"] = {"value": _round_sig(abs(gt[1])), "unit": "degree" if crs.get("geographic") else "m"}
    f["variables"] = [
        {"name": b.findtext("Description") or f"band_{i + 1}", **({"data_type": b.get("dataType").lower()} if b.get("dataType", "").lower() in _DTYPES else {})}
        for i, b in enumerate(root.findall("VRTRasterBand"))
    ]  # fmt: skip
    return f


_DTYPES = {"byte": "uint8", "uint8": "uint8", "int8": "int8", "uint16": "uint16", "int16": "int16", "uint32": "uint32",
           "int32": "int32", "float32": "float32", "float64": "float64", "int64": "int64", "uint64": "uint64"}  # fmt: skip


def _rasterio(path: Path, f: Facts) -> Optional[Facts]:
    try:
        import rasterio  # optional
    except ImportError:
        f["problems"].append(f"{path.suffix} raster not read (install rasterio for details)")
        return None
    try:
        with rasterio.open(str(path)) as ds:
            crs: Dict[str, Any] = {"code": None, "geographic": False, "utm": None}
            if ds.crs:
                epsg = ds.crs.to_epsg()
                crs = {"code": f"EPSG:{epsg}" if epsg else None, "name": ds.crs.to_string(), "geographic": ds.crs.is_geographic,
                       "utm": utm_from_epsg(epsg) if epsg else None, "wkt": ds.crs.to_wkt()}  # fmt: skip
            b = ds.bounds
            xs, ys = box_points(b.left, b.bottom, b.right, b.top)
            set_extent(f, xs, ys, crs)
            f["resolution"] = {"value": _round_sig(abs(ds.res[0])), "unit": "degree" if crs.get("geographic") else "m"}
            f["variables"] = [
                {"name": (ds.descriptions[i] or f"band_{i + 1}"), "data_type": ds.dtypes[i]}
                for i in range(min(ds.count, 50))
            ]
            f["format"] = ds.driver
            tags = ds.tags()
            meta = {k: tags[k] for k in ("title", "license") if tags.get(k)}
            if meta:
                meta["source"] = "file tags"
            f["meta"] = meta
        return f
    except Exception as err:
        f["problems"].append(f"raster not readable ({err.__class__.__name__})")
        return f


# -- NetCDF -----------------------------------------------------------------------------------------
NC_TYPES = {1: ("b", "int8"), 2: ("c", "string"), 3: ("h", "int16"), 4: ("i", "int32"), 5: ("f", "float32"),
            6: ("d", "float64"), 7: ("B", "uint8"), 8: ("H", "uint16"), 9: ("I", "uint32"), 10: ("q", "int64"),
            11: ("Q", "uint64")}  # fmt: skip


class _NC:
    def __init__(self, data: bytes, version: int):
        self.d, self.p, self.v = data, 4, version

    def int(self, big: bool = False) -> int:
        fmt, n = (">q", 8) if (big or self.v == 5) else (">i", 4)
        val = struct.unpack(fmt, self.d[self.p : self.p + n])[0]
        self.p += n
        return val

    def i4(self) -> int:
        val = struct.unpack(">i", self.d[self.p : self.p + 4])[0]
        self.p += 4
        return val

    def name(self) -> str:
        n = self.int()
        s = self.d[self.p : self.p + n].decode("utf-8", errors="replace")
        self.p += n + (-n % 4)
        return s

    def values(self, typ: int, n: int) -> Any:
        code = NC_TYPES[typ][0]
        size = struct.calcsize(">" + code) * n
        raw = self.d[self.p : self.p + size]
        self.p += size + (-size % 4)
        if code == "c":
            return raw.decode("utf-8", errors="replace").rstrip("\0")
        vals = struct.unpack(">" + code * n, raw)
        return vals[0] if n == 1 else list(vals)

    def attrs(self) -> Dict[str, Any]:
        tag, n = self.i4(), self.int()
        out: Dict[str, Any] = {}
        if tag == 0:
            return out
        for _ in range(n):
            name = self.name()
            typ = self.i4()
            out[name] = self.values(typ, self.int())
        return out


def _nc_classic(path: Path) -> Optional[Dict[str, Any]]:
    with path.open("rb") as fh:
        head = fh.read(4)
        if head[:3] != b"CDF" or head[3] not in (1, 2, 5):
            return None
        data = head + fh.read(4 * 1024 * 1024)  # the header is at the start
    nc = _NC(data, head[3])
    numrecs = nc.int()
    dims: List[tuple] = []
    tag, n = nc.i4(), nc.int()
    for _ in range(n if tag else 0):
        dims.append((nc.name(), nc.int()))
    gatts = nc.attrs()
    tag, n = nc.i4(), nc.int()
    variables = []
    for _ in range(n if tag else 0):
        name = nc.name()
        ndim = nc.int()
        dimids = [nc.int() for _ in range(ndim)]
        atts = nc.attrs()
        typ = nc.i4()
        vsize = nc.int()
        begin = nc.int(big=head[3] in (2, 5))
        variables.append({"name": name, "dims": [dims[i][0] for i in dimids], "dimids": dimids, "atts": atts,
                          "type": typ, "vsize": vsize, "begin": begin})  # fmt: skip
    rec_dim = next((i for i, d in enumerate(dims) if d[1] == 0), None)
    rec_vars = [v for v in variables if v["dimids"] and v["dimids"][0] == rec_dim]
    recsize = sum(v["vsize"] for v in rec_vars) if len(rec_vars) != 1 else None
    dim_len = {d[0]: (numrecs if i == rec_dim else d[1]) for i, d in enumerate(dims)}

    def ends(v: Dict[str, Any]) -> Optional[tuple]:
        if len(v["dims"]) != 1 or v["type"] not in NC_TYPES or v["type"] == 2:
            return None
        code = ">" + NC_TYPES[v["type"]][0]
        size = struct.calcsize(code)
        n_ = dim_len[v["dims"][0]]
        if n_ < 1:
            return None
        if v in rec_vars:
            step = recsize if recsize is not None else size
            offsets = [v["begin"], v["begin"] + (n_ - 1) * step]
        else:
            offsets = [v["begin"], v["begin"] + (n_ - 1) * size]
        out = []
        with path.open("rb") as fh:
            for off in offsets:
                fh.seek(off)
                out.append(struct.unpack(code, fh.read(size))[0])
        return out[0], out[1], n_

    return {"dims": dim_len, "gatts": gatts, "vars": variables, "ends": ends}


def _cf_time(units: str, values: List[float], calendar: str = "standard") -> Optional[List[str]]:
    m = re.match(
        r"^\s*(second|minute|hour|day)s?\s+since\s+(\d{1,4}-\d{1,2}-\d{1,2})(?:[ T](\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?",
        units or "",
        re.I,
    )
    if not m or (calendar or "standard").lower() not in ("standard", "gregorian", "proleptic_gregorian"):
        return None
    y, mo, d = (int(x) for x in m.group(2).split("-"))
    base = datetime(y, mo, d)
    if m.group(3):
        hh, mm = m.group(3).split(":")[:2]
        base = base.replace(hour=int(hh), minute=int(mm))
    mult = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[m.group(1).lower()]
    try:
        return [(base + timedelta(seconds=float(v) * mult)).strftime("%Y-%m-%d") for v in values]
    except (OverflowError, ValueError):
        return None


def _nc_facts(
    f: Facts, dims: Dict[str, int], gatts: Dict[str, Any], variables: List[Dict[str, Any]], ends: Callable
) -> Facts:
    coord = {v["name"]: v for v in variables if v["dims"] == [v["name"]]}

    def role(v: Dict[str, Any]) -> Optional[str]:
        a = v["atts"]
        sn, un, nm = str(a.get("standard_name", "")).lower(), str(a.get("units", "")).lower(), v["name"].lower()
        if sn == "latitude" or un in ("degrees_north", "degree_north", "degrees_n") or nm in ("lat", "latitude"):
            return "y"
        if (
            sn == "longitude"
            or un in ("degrees_east", "degree_east", "degrees_e")
            or nm in ("lon", "long", "longitude")
        ):
            return "x"
        if sn == "time" or " since " in un or nm == "time":
            return "t"
        return None

    roles = {r: v for v in coord.values() if (r := role(v))}
    if "x" in roles and "y" in roles:
        ex, ey = ends(roles["x"]), ends(roles["y"])
        if ex and ey:
            rx = abs(ex[1] - ex[0]) / (ex[2] - 1) if ex[2] > 1 else 0
            ry = abs(ey[1] - ey[0]) / (ey[2] - 1) if ey[2] > 1 else 0
            xs = [min(ex[:2]) - rx / 2, max(ex[:2]) + rx / 2]
            ys = [min(ey[:2]) - ry / 2, max(ey[:2]) + ry / 2]
            set_extent(f, xs, ys, {"code": "EPSG:4326", "geographic": True})
            if rx:
                f["resolution"] = {"value": _round_sig(rx), "unit": "degree"}
    elif all(
        k in gatts for k in ("geospatial_lon_min", "geospatial_lat_min", "geospatial_lon_max", "geospatial_lat_max")
    ):
        g = gatts
        set_extent(f, [g["geospatial_lon_min"], g["geospatial_lon_max"]], [g["geospatial_lat_min"], g["geospatial_lat_max"]],
                   {"code": "EPSG:4326", "geographic": True})  # fmt: skip
    if "t" in roles:
        et = ends(roles["t"])
        if et:
            dates = _cf_time(
                str(roles["t"]["atts"].get("units", "")),
                list(et[:2]),
                str(roles["t"]["atts"].get("calendar", "standard")),
            )
            if dates:
                f["time"] = {"start": min(dates), "end": max(dates), "steps": et[2]}
    out = []
    for v in variables:
        if (
            v["name"] in coord
            or not v["dims"]
            or v["name"] in ("crs", "spatial_ref")
            or "grid_mapping_name" in v["atts"]
        ):
            continue
        a = v["atts"]
        item: Dict[str, Any] = {"name": v["name"]}
        if a.get("long_name") or a.get("description"):
            item["description"] = str(a.get("long_name") or a.get("description"))[:300]
        if v.get("type") in NC_TYPES:
            item["data_type"] = NC_TYPES[v["type"]][1]
        elif v.get("dtype"):
            item["data_type"] = v["dtype"]
        if a.get("units") and str(a["units"]).strip() not in ("1", "", "none"):
            item["unit"] = str(a["units"])
        fill = a.get("_FillValue", a.get("missing_value"))
        if isinstance(fill, (int, float)) and not (isinstance(fill, float) and math.isnan(fill)):
            item["nodata"] = fill
        out.append(item)
    f["variables"] = out[:50]
    f["dims"] = {k: v for k, v in dims.items()}
    meta: Dict[str, Any] = {}
    for key, names in (("title", ("title",)), ("abstract", ("summary", "abstract", "description", "comment")),
                       ("license", ("license", "licence", "rights")), ("keywords", ("keywords",)),
                       ("organization", ("institution", "creator_institution", "publisher_institution")),
                       ("name", ("creator_name",)), ("email", ("creator_email",)), ("citation", ("references",))):  # fmt: skip
        for n in names:
            if isinstance(gatts.get(n), str) and gatts[n].strip():
                meta[key] = gatts[n].strip()[:2000]
                break
    if isinstance(meta.get("keywords"), str):
        meta["keywords"] = [k.strip() for k in re.split(r"[;,]", meta["keywords"]) if k.strip()][:20]
    if meta:
        meta["source"] = "NetCDF global attributes"
    f["meta"] = meta
    return f


def read_netcdf(path: Path) -> Facts:
    f = new_facts("raster", "NetCDF", "application/x-netcdf")
    try:
        nc = _nc_classic(path)
    except (OSError, struct.error, KeyError, IndexError, UnicodeDecodeError) as err:
        f["problems"].append(f"NetCDF header not readable ({err.__class__.__name__})")
        return f
    if nc:
        return _nc_facts(f, nc["dims"], nc["gatts"], nc["vars"], nc["ends"])
    f["format"] = "NetCDF-4 / HDF5"
    try:
        import netCDF4  # optional

        with netCDF4.Dataset(str(path)) as ds:
            dims = {k: len(d) for k, d in ds.dimensions.items()}
            gatts = {k: ds.getncattr(k) for k in ds.ncattrs()}
            variables = [{"name": k, "dims": list(v.dimensions), "atts": {a: v.getncattr(a) for a in v.ncattrs()},
                          "dtype": _DTYPES.get(str(v.dtype))} for k, v in ds.variables.items()]  # fmt: skip

            def ends(v: Dict[str, Any]) -> Optional[tuple]:
                arr = ds.variables[v["name"]]
                if arr.ndim != 1 or arr.shape[0] < 1:
                    return None
                return float(arr[0]), float(arr[-1]), arr.shape[0]

            return _nc_facts(f, dims, gatts, variables, ends)
    except ImportError:
        f["problems"].append("NetCDF-4 not read (install netCDF4 for details)")
    except Exception as err:
        f["problems"].append(f"NetCDF-4 not readable ({err.__class__.__name__})")
    return f


# -- vectors ---------------------------------------------------------------------------------------
SHP_TYPES = {1: "point", 8: "point", 11: "point", 18: "point", 21: "point", 28: "point",
             3: "line", 13: "line", 23: "line", 5: "polygon", 15: "polygon", 25: "polygon", 31: "polygon"}  # fmt: skip
DBF_TYPES = {"C": "string", "N": "number", "F": "number", "L": "boolean", "D": "date", "I": "int32", "M": "string",
             "B": "float64", "O": "float64", "@": "datetime", "+": "int32", "T": "datetime", "Y": "number"}  # fmt: skip


def read_dbf(path: Path) -> tuple:
    """(row count, variables) of a dBase table."""
    enc = "utf-8"
    cpg = path.with_suffix(".cpg")
    if cpg.exists():
        enc = cpg.read_text(errors="replace").strip() or enc
    with path.open("rb") as fh:
        head = fh.read(32)
        count = struct.unpack("<I", head[4:8])[0]
        hlen = struct.unpack("<H", head[8:10])[0]
        raw = fh.read(max(hlen - 32, 0))
    variables = []
    for i in range(0, len(raw) - 31, 32):
        if raw[i] == 0x0D:
            break
        name = raw[i : i + 11].split(b"\0")[0]
        try:
            name_s = name.decode(enc, errors="replace")
        except LookupError:
            name_s = name.decode("latin-1")
        typ = chr(raw[i + 11])
        dec = raw[i + 17]
        dt = DBF_TYPES.get(typ, "string")
        if typ == "N" and dec == 0:
            dt = "integer"
        variables.append({"name": name_s.strip(), "data_type": dt})
    return count, variables


def read_dbf_table(path: Path) -> Facts:
    f = new_facts("tabular", "dBase table", "application/dbase")
    f["feature_count"], f["variables"] = read_dbf(path)
    return f


def read_shapefile(path: Path) -> Facts:
    f = new_facts("vector", "Shapefile", "application/vnd.shp")
    with path.open("rb") as fh:
        head = fh.read(100)
    if len(head) < 100 or struct.unpack(">i", head[:4])[0] != 9994:
        f["problems"].append("not a valid .shp file")
        return f
    stype = struct.unpack("<i", head[32:36])[0]
    xmin, ymin, xmax, ymax = struct.unpack("<4d", head[36:68])
    if SHP_TYPES.get(stype):
        f["geometry_type"] = SHP_TYPES[stype]
    crs = read_prj(path)
    if xmax >= xmin and (xmin, ymin, xmax, ymax) != (0, 0, 0, 0):
        xs, ys = box_points(xmin, ymin, xmax, ymax)
        set_extent(f, xs, ys, crs)
    for dbf in (path.with_suffix(".dbf"), path.with_suffix(".DBF")):
        if dbf.exists():
            f["feature_count"], f["variables"] = read_dbf(dbf)
            break
    missing = [
        e for e in (".shx", ".dbf") if not (path.with_suffix(e).exists() or path.with_suffix(e.upper()).exists())
    ]
    if missing:
        f["problems"].append(f"Shapefile without {', '.join(missing)}")
    if not crs:
        f["problems"].append("Shapefile without .prj (coordinate system unknown)")
    return f


GEOJSON_TYPES = {"Point": "point", "MultiPoint": "point", "LineString": "line", "MultiLineString": "line",
                 "Polygon": "polygon", "MultiPolygon": "polygon"}  # fmt: skip


def _walk_coords(c: Any, xs: List[float], ys: List[float]) -> None:
    if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
        if len(c) >= 2:
            xs.append(float(c[0]))
            ys.append(float(c[1]))
        return
    if isinstance(c, (list, tuple)):
        for item in c:
            _walk_coords(item, xs, ys)


def _value_type(v: Any) -> Optional[str]:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            return "date"
        if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", v):
            return "datetime"
        return "string"
    if isinstance(v, (list, dict)):
        return "other"
    return None


def _merge_types(types: List[str]) -> Optional[str]:
    s = set(t for t in types if t)
    if not s:
        return None
    if s <= {"integer", "number"}:
        return "number" if "number" in s else "integer"
    return s.pop() if len(s) == 1 else "string"


def read_geojson(path: Path) -> Facts:
    f = new_facts("vector", "GeoJSON", "application/geo+json")
    if path.stat().st_size > MAX_PARSE:
        f["problems"].append("GeoJSON larger than 300 MB: not parsed")
        return f
    try:
        doc = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        f["problems"].append("not valid JSON")
        f["kind"] = "other"
        return f
    if not isinstance(doc, dict) or doc.get("type") not in (
        "FeatureCollection",
        "Feature",
        *GEOJSON_TYPES,
        "GeometryCollection",
    ):
        f["kind"], f["format"], f["media_type"] = "other", "JSON", "application/json"  # config, STAC, metadata...
        return f
    feats = doc.get("features") if doc.get("type") == "FeatureCollection" else [doc]
    feats = feats if isinstance(feats, list) else []
    xs: List[float] = []
    ys: List[float] = []
    gtypes = set()
    props: Dict[str, List[str]] = {}
    for i, ft in enumerate(feats):
        geom = ft.get("geometry") if ft.get("type") == "Feature" else ft
        if isinstance(geom, dict):
            gtypes.add(GEOJSON_TYPES.get(geom.get("type"), "mixed"))
            _walk_coords(geom.get("coordinates"), xs, ys)
        if i < SAMPLE_ROWS and isinstance(ft.get("properties"), dict):
            for k, v in ft["properties"].items():
                props.setdefault(k, []).append(_value_type(v))
    f["feature_count"] = len(feats)
    if gtypes:
        f["geometry_type"] = gtypes.pop() if len(gtypes) == 1 else "mixed"
    crs: Dict[str, Any] = {"code": "EPSG:4326", "geographic": True}
    name = ((doc.get("crs") or {}).get("properties") or {}).get("name", "")
    m = re.search(r"EPSG:+(\d+)", name)
    if m and m.group(1) not in ("4326",):
        num = int(m.group(1))
        crs = {"code": f"EPSG:{num}", "geographic": num in (4326, 4269, 4258, 4674), "utm": utm_from_epsg(num)}
    elif "CRS84" in name or not name:
        crs = {"code": "EPSG:4326", "geographic": True}
    if xs:
        set_extent(f, [min(xs), max(xs)], [min(ys), max(ys)], crs)
    f["variables"] = [{"name": k, **({"data_type": t} if (t := _merge_types(v)) else {})} for k, v in props.items()]
    meta = {k: doc[k] for k in ("name", "title", "description") if isinstance(doc.get(k), str) and doc[k].strip()}
    if meta:
        f["meta"] = {
            "title": meta.get("title") or meta.get("name"),
            "abstract": meta.get("description"),
            "source": "GeoJSON members",
        }
        f["meta"] = {k: v for k, v in f["meta"].items() if v}
    return f


GPKG_TYPES = {"INTEGER": "int64", "INT": "int64", "MEDIUMINT": "int32", "SMALLINT": "int16", "TINYINT": "int8",
              "REAL": "float64", "DOUBLE": "float64", "FLOAT": "float32", "TEXT": "string", "DATE": "date",
              "DATETIME": "datetime", "BOOLEAN": "boolean", "BLOB": "binary"}  # fmt: skip


def read_geopackage(path: Path) -> Facts:
    f = new_facts("vector", "GeoPackage", "application/geopackage+sqlite3")
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    except sqlite3.Error as err:
        f["problems"].append(f"GeoPackage not readable ({err})")
        return f
    try:
        rows = con.execute(
            "SELECT c.table_name, c.data_type, c.identifier, c.description, c.min_x, c.min_y, c.max_x, c.max_y, "
            "s.organization, s.organization_coordsys_id, s.definition FROM gpkg_contents c "
            "LEFT JOIN gpkg_spatial_ref_sys s ON s.srs_id = c.srs_id"
        ).fetchall()
        geoms = dict(con.execute("SELECT table_name, geometry_type_name FROM gpkg_geometry_columns").fetchall())
        gcols = dict(con.execute("SELECT table_name, column_name FROM gpkg_geometry_columns").fetchall())
        layers, kinds, xs, ys, gtypes, total = [], set(), [], [], set(), 0
        crs: Dict[str, Any] = {}
        for t, dtype, ident, desc, x0, y0, x1, y1, org, code, wkt in rows:
            kinds.add({"features": "vector", "tiles": "raster", "attributes": "tabular"}.get(dtype, "other"))
            layer: Dict[str, Any] = {"name": t}
            if dtype in ("features", "attributes"):
                cols = con.execute(f'PRAGMA table_info("{t}")').fetchall()
                layer["variables"] = [
                    {"name": c[1], **({"data_type": GPKG_TYPES[c[2].split("(")[0].upper()]} if c[2].split("(")[0].upper() in GPKG_TYPES else {})}
                    for c in cols if c[1] != gcols.get(t) and not c[5]
                ]  # fmt: skip
                n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]  # noqa: S608
                layer["feature_count"] = n
                total += n
                if gcols.get(t):
                    layer["geometry_column"] = gcols[t]
            g = (geoms.get(t) or "").upper()
            if g:
                gtypes.add(
                    "point" if "POINT" in g else "line" if "LINE" in g else "polygon" if "POLYGON" in g else "mixed"
                )
            if None not in (x0, y0, x1, y1):
                c = crs_from_wkt(wkt or "")
                if org and str(org).upper() in ("EPSG", "ESRI") and code and int(code) > 0:
                    c["code"] = f"{str(org).upper()}:{code}"
                    c["utm"] = c.get("utm") or utm_from_epsg(int(code))
                    c["geographic"] = c.get("geographic") or int(code) == 4326
                c["wkt"] = wkt
                crs = crs or c
                bx, by = box_points(x0, y0, x1, y1)
                b = to_wgs84_bbox(bx, by, c)
                if b:
                    xs += [b[0], b[2]]
                    ys += [b[1], b[3]]
            if ident and ident != t:
                layer["title"] = ident
            if desc:
                layer["description"] = desc
            layers.append(layer)
        if crs.get("code"):
            f["crs"] = crs["code"]
        if xs:
            f["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
        if len(kinds) == 1:
            f["kind"] = kinds.pop()
        elif kinds:
            f["kind"] = "mixed"
        if gtypes:
            f["geometry_type"] = gtypes.pop() if len(gtypes) == 1 else "mixed"
        if len(layers) == 1:
            lay = layers[0]
            f["variables"] = lay.get("variables", [])
            if "feature_count" in lay:
                f["feature_count"] = lay["feature_count"]
            if lay.get("geometry_column"):
                f["geometry_column"] = lay["geometry_column"]
            if lay.get("title") or lay.get("description"):
                f["meta"] = {k: v for k, v in (("title", lay.get("title")), ("abstract", lay.get("description"))) if v}
                f["meta"]["source"] = "GeoPackage contents"
        else:
            f["layers"] = layers
            f["feature_count"] = total
    except sqlite3.Error as err:
        f["problems"].append(f"not a GeoPackage ({err})")
    finally:
        con.close()
    return f


def read_kml(path: Path, data: Optional[bytes] = None) -> Facts:
    f = new_facts("vector", "KML", "application/vnd.google-earth.kml+xml")
    try:
        root = ET.fromstring(data if data is not None else path.read_bytes())  # noqa: S314
    except ET.ParseError:
        f["problems"].append("KML not readable")
        return f
    xs: List[float] = []
    ys: List[float] = []
    gtypes, count, fields = set(), 0, []
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "placemark":
            count += 1
        elif tag in ("point", "linestring", "polygon", "linearring"):
            gtypes.add({"point": "point", "linestring": "line"}.get(tag, "polygon"))
        elif tag == "coordinates" and el.text:
            for tok in el.text.split():
                parts = tok.split(",")
                if len(parts) >= 2:
                    try:
                        xs.append(float(parts[0]))
                        ys.append(float(parts[1]))
                    except ValueError:
                        pass
        elif tag == "simplefield" and el.get("name"):
            fields.append({"name": el.get("name")})
    f["feature_count"] = count
    if gtypes:
        f["geometry_type"] = gtypes.pop() if len(gtypes) == 1 else "mixed"
    if xs:
        set_extent(f, [min(xs), max(xs)], [min(ys), max(ys)], {"code": "EPSG:4326", "geographic": True})
    if fields:
        f["variables"] = fields
    doc = next((el for el in root.iter() if _local(el.tag) == "document"), None)
    if doc is not None:
        meta = {}
        for child in doc:
            if _local(child.tag) == "name" and (child.text or "").strip():
                meta["title"] = child.text.strip()
            if _local(child.tag) == "description" and (child.text or "").strip():
                meta["abstract"] = re.sub(r"<[^>]+>", " ", child.text).strip()[:2000]
        if meta:
            meta["source"] = "KML document"
            f["meta"] = meta
    return f


def read_kmz(path: Path) -> Facts:
    with zipfile.ZipFile(path) as z:
        kmls = [n for n in z.namelist() if n.lower().endswith(".kml")]
        if not kmls:
            f = new_facts("vector", "KMZ", "application/vnd.google-earth.kmz")
            f["problems"].append("no KML inside the KMZ")
            return f
        f = read_kml(path, z.read(kmls[0]))
    f["format"], f["media_type"] = "KMZ", "application/vnd.google-earth.kmz"
    return f


# -- tables ----------------------------------------------------------------------------------------
def _cell_type(v: str) -> Optional[str]:
    v = v.strip()
    if not v or v.lower() in ("na", "nan", "null", "none", "-", "n/a"):
        return None
    if re.match(r"^[+-]?\d+$", v):
        return "integer"
    if re.match(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$", v):
        return "number"
    if v.lower() in ("true", "false"):
        return "boolean"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        return "date"
    return "string"


def read_csv(path: Path) -> Facts:
    f = new_facts("tabular", "CSV" if path.suffix.lower() != ".tsv" else "TSV", "text/csv")
    with path.open("rb") as fh:
        raw = fh.read(2_000_000)
    text = ""
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.splitlines()[0] if text else ""
    try:
        dialect: Any = csv.Sniffer().sniff(first, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if len(raw) == 2_000_000 and rows:
        rows = rows[:-1]  # last row may be cut
    if not rows:
        f["problems"].append("empty table")
        return f
    header = [h.strip() for h in rows[0]]
    cols: List[List[Optional[str]]] = [[] for _ in header]
    for r in rows[1 : SAMPLE_ROWS + 1]:
        for i, v in enumerate(r[: len(header)]):
            cols[i].append(_cell_type(v))
    if path.stat().st_size <= len(raw):
        f["feature_count"] = len(rows) - 1
    else:
        with path.open("rb") as fh:
            f["feature_count"] = max(sum(1 for _ in fh) - 1, 0)  # approximate when cells hold line breaks
    low = {h.lower(): i for i, h in enumerate(header)}
    lat = next((low[n] for n in low if n in LAT_NAMES), None)
    lon = next((low[n] for n in low if n in LON_NAMES), None)
    geom = next((low[n] for n in low if n in GEOM_NAMES), None)
    skip = set()
    if lat is not None and lon is not None:
        xs, ys = [], []
        for r in rows[1:]:
            try:
                x, y = float(r[lon]), float(r[lat])
            except (ValueError, IndexError):
                continue
            if -180 <= x <= 360 and -90 <= y <= 90:
                xs.append(x)
                ys.append(y)
        if xs:
            set_extent(f, [min(xs), max(xs)], [min(ys), max(ys)], {"code": "EPSG:4326", "geographic": True})
            f["dimensions"] = [
                {"name": header[lon], "type": "x", "unit": "degree", "description": "Longitude column"},
                {"name": header[lat], "type": "y", "unit": "degree", "description": "Latitude column"},
            ]
            skip = {lat, lon}
    elif geom is not None:
        f["geometry_column"] = header[geom]
        skip = {geom}
    f["variables"] = [
        {"name": h, **({"data_type": t} if (t := _merge_types(cols[i])) else {})}
        for i, h in enumerate(header)
        if h and i not in skip
    ]
    return f


def read_xlsx(path: Path) -> Facts:
    f = new_facts("tabular", "Excel workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    try:
        with zipfile.ZipFile(path) as z:
            shared: List[str] = []
            if "xl/sharedStrings.xml" in z.namelist():
                for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(ns + "si"):  # noqa: S314
                    shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
            wb = ET.fromstring(z.read("xl/workbook.xml"))  # noqa: S314
            names = [s.get("name") for s in wb.iter(ns + "sheet")]
            layers = []
            for i, name in enumerate(names, start=1):
                member = f"xl/worksheets/sheet{i}.xml"
                if member not in z.namelist():
                    continue
                header: List[str] = []
                nrows = 0
                with z.open(member) as fh:
                    for _, el in ET.iterparse(fh):  # noqa: S314
                        if el.tag == ns + "dimension":
                            m = re.search(r":[A-Z]+(\d+)$", el.get("ref", ""))
                            nrows = int(m.group(1)) - 1 if m else 0
                        if el.tag == ns + "row":
                            for c in el.iter(ns + "c"):
                                v = c.findtext(ns + "v") or c.findtext(f"{ns}is/{ns}t") or ""
                                header.append(
                                    shared[int(v)] if c.get("t") == "s" and v.isdigit() and int(v) < len(shared) else v
                                )
                            break
                layers.append(
                    {"name": name, "variables": [{"name": h} for h in header if h], "feature_count": max(nrows, 0)}
                )
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as err:
        f["problems"].append(f"workbook not readable ({err.__class__.__name__})")
        return f
    if len(layers) == 1:
        f["variables"], f["feature_count"] = layers[0]["variables"], layers[0]["feature_count"]
    else:
        f["layers"] = layers
    return f


def read_parquet(path: Path) -> Facts:
    f = new_facts("tabular", "Parquet", "application/vnd.apache.parquet")
    try:
        import pyarrow.parquet as pq  # optional
    except ImportError:
        f["problems"].append("Parquet not read (install pyarrow for details)")
        return f
    try:
        pf = pq.ParquetFile(str(path))
        f["feature_count"] = pf.metadata.num_rows
        geo = json.loads((pf.schema_arrow.metadata or {}).get(b"geo", b"{}") or b"{}")
        gcol = geo.get("primary_column")
        f["variables"] = [{"name": n} for n in pf.schema_arrow.names if n != gcol]
        if gcol:
            f["kind"], f["format"], f["geometry_column"] = "vector", "GeoParquet", gcol
            b = (geo.get("columns", {}).get(gcol) or {}).get("bbox")
            if b and len(b) == 4:
                set_extent(f, [b[0], b[2]], [b[1], b[3]], {"code": "EPSG:4326", "geographic": True})
    except Exception as err:
        f["problems"].append(f"Parquet not readable ({err.__class__.__name__})")
    return f


def read_ogr(path: Path) -> Facts:
    """Any other vector source (File Geodatabase, GML, GPX, MapInfo, FlatGeobuf...) with pyogrio or fiona."""
    f = new_facts("vector", path.suffix.lstrip(".").upper() or "vector", None)
    try:
        import pyogrio  # optional

        layers = pyogrio.list_layers(str(path))
        info = pyogrio.read_info(str(path), layer=layers[0][0])
        f["feature_count"] = int(info.get("features") or 0)
        f["variables"] = [{"name": n} for n in info.get("fields", [])]
        crs = {"code": info.get("crs"), "geographic": info.get("crs") == "EPSG:4326"}
        b = info.get("total_bounds")
        if b is not None:
            xs, ys = box_points(*b)
            set_extent(f, xs, ys, crs)
        if len(layers) > 1:
            f["layers"] = [{"name": n} for n, _ in layers]
        return f
    except ImportError:
        pass
    except Exception as err:
        f["problems"].append(f"not readable ({err.__class__.__name__})")
        return f
    f["problems"].append(f"{path.suffix or path.name} not read (install pyogrio for details)")
    return f


# -- archives and dispatch ---------------------------------------------------------------------------
def _safe_member(name: str) -> bool:
    norm = name.replace("\\", "/")
    parts = PurePosixPath(norm).parts
    if not parts or norm.endswith("/") or norm.startswith("/") or "__MACOSX" in parts:
        return False
    return ":" not in parts[0] and ".." not in parts


def read_zip(path: Path) -> Facts:
    with zipfile.ZipFile(path) as z:
        members = [m for m in z.namelist() if _safe_member(m)]
        data = [
            m for m in members if Path(m).suffix.lower() in READERS and Path(m).suffix.lower() not in (".zip", ".kmz")
        ]
        if not data:
            rasters = [m for m in members if Path(m).suffix.lower() in RASTER_ONLY_EXT]
            f = new_facts("raster" if rasters else "other", "ZIP archive", "application/zip")
            f["problems"].append("raster format inside the zip not read" if rasters else "no data file inside the zip")
            f["members"] = len(members)
            return f
        total = sum(z.getinfo(m).file_size for m in members)
        if total > 2 * 1000 * 1000 * 1000:
            f = new_facts("other", "ZIP archive", "application/zip")
            f["problems"].append("zip expands to more than 2 GB: not inspected")
            return f
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            files = []
            for m in members:
                p = Path(z.extract(m, tmp)).resolve()
                if root in p.parents:
                    files.append(p)
            mains = [p for p in files if p.suffix.lower() in READERS and p.suffix.lower() not in (".zip", ".kmz")]
            mains = [p for p in mains if not (p.suffix.lower() == ".dbf" and p.with_suffix(".shp").exists())]
            facts = [read_file(p) for p in mains[:20]] or [new_facts("other", "ZIP archive")]
    f = facts[0] if len(facts) == 1 else merge_facts(facts)
    f["format"] = f"ZIP of {f.get('format')}"
    f["media_type"] = "application/zip"
    f["members"] = len(members)
    return f


def merge_facts(items: List[Facts], names: Optional[List[str]] = None) -> Facts:
    """One set of facts for several files of one dataset (a series, a folder, a zip). ``names``: the
    files' stems, used to name the variables (one per file) or the layers when the files differ."""
    kinds = {i.get("kind") for i in items}
    first = items[0]
    f = new_facts(kinds.pop() if len(kinds) == 1 else "mixed", first.get("format", ""), first.get("media_type"))
    boxes = [i["bbox"] for i in items if i.get("bbox")]
    if boxes:
        f["bbox"] = [
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        ]
    for key in ("crs", "resolution", "geometry_type"):
        vals = {json.dumps(i.get(key), sort_keys=True) for i in items if i.get(key) is not None}
        if len(vals) == 1:
            f[key] = next(i[key] for i in items if i.get(key) is not None)
        elif key == "geometry_type" and vals:
            f[key] = "mixed"
    counts = [i["feature_count"] for i in items if isinstance(i.get("feature_count"), int)]
    if counts and len(counts) == len(items):
        f["feature_count"] = sum(counts)
    distinct = {json.dumps(i.get("variables"), sort_keys=True) for i in items if i.get("variables")}
    if len(distinct) == 1:
        f["variables"] = next(i["variables"] for i in items if i.get("variables"))
    elif distinct and names and len(names) == len(items):
        if all(len(i.get("variables") or []) <= 1 for i in items):  # one band or column per file
            f["variables"] = [{"name": n, **{k: v for k, v in ((i.get("variables") or [{}])[0]).items() if k not in ("name",)}}
                              for n, i in zip(names, items)][:50]  # fmt: skip
        else:
            f["layers"] = [{"name": n, "variables": i.get("variables") or [], "geometry_column": i.get("geometry_column")}
                           for n, i in zip(names, items)][:20]  # fmt: skip
    times = [i["time"] for i in items if i.get("time")]
    if times:
        f["time"] = {"start": min(t["start"] for t in times), "end": max(t["end"] for t in times)}
    f["meta"] = next((i["meta"] for i in items if i.get("meta")), {})
    f["problems"] = sorted({p for i in items for p in i.get("problems", [])})[:5]
    return f


DOC_EXT = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".md", ".txt", ".html", ".htm", ".pptx", ".ppt"}
READERS: Dict[str, Callable[[Path], Facts]] = {
    ".tif": read_geotiff, ".tiff": read_geotiff, ".gtiff": read_geotiff, ".asc": read_ascii_grid, ".vrt": read_vrt,
    ".nc": read_netcdf, ".nc4": read_netcdf, ".cdf": read_netcdf, ".netcdf": read_netcdf, ".h5": read_netcdf,
    ".hdf5": read_netcdf, ".shp": read_shapefile, ".geojson": read_geojson, ".json": read_geojson,
    ".gpkg": read_geopackage, ".dbf": read_dbf_table, ".kml": read_kml, ".kmz": read_kmz, ".csv": read_csv, ".tsv": read_csv,
    ".xlsx": read_xlsx, ".parquet": read_parquet, ".geoparquet": read_parquet, ".zip": read_zip,
    ".gdb": read_ogr, ".gml": read_ogr, ".gpx": read_ogr, ".tab": read_ogr, ".fgb": read_ogr, ".mif": read_ogr,
}  # fmt: skip
RASTER_ONLY_EXT = {".img", ".jp2", ".hdf", ".grd", ".bil", ".dem", ".sid", ".ecw", ".rst", ".sdat", ".nc3", ".grib", ".grb", ".grb2", ".zarr"}  # fmt: skip


def read_file(path: Path) -> Facts:
    ext = path.suffix.lower()
    try:
        if ext in READERS:
            f = READERS[ext](path)
        elif ext in RASTER_ONLY_EXT:
            f = _rasterio(path, new_facts("raster", ext.lstrip(".").upper(), None)) or new_facts(
                "raster", ext.lstrip(".").upper()
            )
            if not f.get("problems") and not f.get("bbox"):
                f["problems"].append(f"{ext} raster not read (install rasterio for details)")
        elif ext in DOC_EXT:
            f = new_facts("document", ext.lstrip(".").upper(), None)
        else:
            f = new_facts("other", ext.lstrip(".") or "file", None)
    except Exception as err:  # a reader must never stop the scan
        f = new_facts("other", ext.lstrip(".") or "file", None)
        f["problems"].append(f"not readable ({err.__class__.__name__}: {str(err)[:80]})")
    if not f.get("meta"):
        side = sidecar_meta(path)
        if side:
            f["meta"] = side
    return f
