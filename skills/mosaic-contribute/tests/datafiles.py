"""Writers of small, valid data files (standard library only) for the mosaic-contribute tests."""

from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)


def write_geotiff(path: Path, *, epsg: int, origin: tuple, pixel: float, size: tuple = (4, 3), bands: int = 1,
                  geographic: bool = True, band_names: list | None = None, bits: int = 32, fmt: int = 3) -> Path:  # fmt: skip
    """An uncompressed little-endian GeoTIFF with ModelPixelScale, ModelTiepoint and GeoKeys."""
    w, h = size
    nbytes = bits // 8
    data = bytes(w * h * bands * nbytes)
    geokeys = [1, 1, 0, 2, 1024, 0, 1, 2 if geographic else 1, 2048 if geographic else 3072, 0, 1, epsg]
    meta = ""
    if band_names:
        items = "".join(
            f'<Item name="DESCRIPTION" sample="{i}" role="description">{n}</Item>' for i, n in enumerate(band_names)
        )
        meta = f"<GDALMetadata>{items}</GDALMetadata>"
    entries = [
        (256, 3, [w]), (257, 3, [h]), (258, 3, [bits] * bands), (259, 3, [1]), (262, 3, [1]),
        (273, 4, [0]), (277, 3, [bands]), (278, 3, [h]), (279, 4, [len(data)]), (284, 3, [1 if bands == 1 else 2]),
        (339, 3, [fmt] * bands), (33550, 12, [pixel, pixel, 0.0]), (33922, 12, [0.0, 0.0, 0.0, origin[0], origin[1], 0.0]),
        (34735, 3, geokeys),
    ]  # fmt: skip
    if meta:
        entries.append((42112, 2, meta))
    entries.sort()
    codes = {3: "H", 4: "I", 12: "d"}
    head = 8
    ifd_size = 2 + 12 * len(entries) + 4
    extra = bytearray()
    extra_base = head + ifd_size
    ifd = struct.pack("<H", len(entries))
    patched = []
    for tag, typ, vals in entries:
        if typ == 2:
            raw = vals.encode() + b"\0"
            count = len(raw)
        else:
            raw = struct.pack("<" + codes[typ] * len(vals), *vals)
            count = len(vals)
        if len(raw) <= 4:
            ifd += struct.pack("<HHI", tag, typ, count) + raw.ljust(4, b"\0")
        else:
            patched.append((len(ifd), extra_base + len(extra)))
            ifd += struct.pack("<HHI", tag, typ, count) + struct.pack("<I", extra_base + len(extra))
            extra += raw + (b"\0" if len(raw) % 2 else b"")
    ifd += struct.pack("<I", 0)
    strip = extra_base + len(extra)
    blob = bytearray(b"II*\0" + struct.pack("<I", head) + ifd + extra + data)
    # point StripOffsets at the pixel data
    i = 0
    for k, (tag, _typ, _vals) in enumerate(entries):
        if tag == 273:
            i = head + 2 + 12 * k + 8
    blob[i : i + 4] = struct.pack("<I", strip)
    path.write_bytes(bytes(blob))
    return path


def write_shapefile(path: Path, polygons: list, fields: dict, prj: str | None = WGS84_PRJ) -> Path:
    """Polygons (lists of (x, y)) with dBase fields {name: [values]} (C or N)."""
    recs = []
    xs = [x for poly in polygons for x, _ in poly]
    ys = [y for poly in polygons for _, y in poly]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    for poly in polygons:
        pts = b"".join(struct.pack("<2d", *p) for p in poly)
        pb = (min(p[0] for p in poly), min(p[1] for p in poly), max(p[0] for p in poly), max(p[1] for p in poly))
        content = struct.pack("<i4d2i", 5, *pb, 1, len(poly)) + struct.pack("<i", 0) + pts
        recs.append(content)

    def header(length_words: int) -> bytes:
        return struct.pack(">7i", 9994, 0, 0, 0, 0, 0, length_words) + struct.pack(
            "<2i4d4d", 1000, 5, *bbox, 0, 0, 0, 0
        )

    body, index, offset = b"", b"", 50
    for n, content in enumerate(recs, start=1):
        body += struct.pack(">2i", n, len(content) // 2) + content
        index += struct.pack(">2i", offset, len(content) // 2)
        offset += 4 + len(content) // 2
    path.write_bytes(header(50 + len(body) // 2) + body)
    path.with_suffix(".shx").write_bytes(header(50 + len(index) // 2) + index)
    names = list(fields)
    nrec = len(polygons)
    desc = b""
    widths = []
    for name in names:
        numeric = all(isinstance(v, (int, float)) for v in fields[name])
        width = 12 if numeric else 30
        widths.append((width, numeric))
        desc += (
            name.encode().ljust(11, b"\0") + (b"N" if numeric else b"C") + b"\0" * 4 + bytes([width, 0]) + b"\0" * 14
        )
    hlen = 32 + len(desc) + 1
    rlen = 1 + sum(w for w, _ in widths)
    dbf = struct.pack("<BBBBIHH20x", 3, 126, 1, 1, nrec, hlen, rlen) + desc + b"\r"
    for i in range(nrec):
        row = b" "
        for (width, numeric), name in zip(widths, names):
            v = str(fields[name][i]).encode()
            row += v.rjust(width) if numeric else v.ljust(width)
        dbf += row
    path.with_suffix(".dbf").write_bytes(dbf + b"\x1a")
    if prj:
        path.with_suffix(".prj").write_text(prj)
    return path


def write_netcdf(path: Path, lats: list, lons: list, times: list, units: str = "days since 2000-01-01") -> Path:
    """A classic (CDF-1) NetCDF file: time (record dimension), lat, lon and one float variable pr(time, lat, lon)."""

    def name(s: str) -> bytes:
        b = s.encode()
        return struct.pack(">i", len(b)) + b + b"\0" * (-len(b) % 4)

    def att_text(k: str, v: str) -> bytes:
        b = v.encode()
        return name(k) + struct.pack(">ii", 2, len(b)) + b + b"\0" * (-len(b) % 4)

    def atts(items: list) -> bytes:
        if not items:
            return struct.pack(">ii", 0, 0)
        return struct.pack(">ii", 12, len(items)) + b"".join(att_text(k, v) for k, v in items)

    dims = struct.pack(">ii", 10, 3) + name("time") + struct.pack(">i", 0) + name("lat") + struct.pack(">i", len(lats))
    dims += name("lon") + struct.pack(">i", len(lons))
    gatts = atts([("title", "Test rainfall"), ("license", "CC-BY-4.0"), ("institution", "Test Institute")])
    variables = [
        ("lat", [1], [("units", "degrees_north")], 6, 8 * len(lats), False),
        ("lon", [2], [("units", "degrees_east")], 6, 8 * len(lons), False),
        ("time", [0], [("units", units), ("calendar", "standard")], 6, 8, True),
        ("pr", [0, 1, 2], [("units", "mm d-1"), ("long_name", "precipitation")], 5, 4 * len(lats) * len(lons), True),
    ]

    def var_block(begins: list) -> bytes:
        out = struct.pack(">ii", 11, len(variables))
        for (vname, dimids, va, typ, vsize, _), begin in zip(variables, begins):
            out += name(vname) + struct.pack(">i", len(dimids)) + b"".join(struct.pack(">i", d) for d in dimids)
            out += atts(va) + struct.pack(">iii", typ, vsize, begin)
        return out

    head_len = len(b"CDF\x01" + struct.pack(">i", len(times)) + dims + gatts + var_block([0] * 4))
    begins, pos = [], head_len
    for v in variables[:2]:
        begins.append(pos)
        pos += v[4]
    rec_start = pos
    begins += [rec_start, rec_start + 8]
    recsize = 8 + 4 * len(lats) * len(lons)
    out = b"CDF\x01" + struct.pack(">i", len(times)) + dims + gatts + var_block(begins)
    out += struct.pack(f">{len(lats)}d", *lats) + struct.pack(f">{len(lons)}d", *lons)
    for t in times:
        out += struct.pack(">d", t) + b"\0" * (recsize - 8)
    path.write_bytes(out)
    return path


def write_gpkg(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT, srs_id INTEGER PRIMARY KEY, organization TEXT,
            organization_coordsys_id INTEGER, definition TEXT, description TEXT);
        INSERT INTO gpkg_spatial_ref_sys VALUES ('WGS 84 / UTM zone 37N', 32637, 'EPSG', 32637, 'PROJCS["WGS 84 / UTM zone 37N"]', '');
        CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, data_type TEXT, identifier TEXT, description TEXT,
            last_change TEXT, min_x REAL, min_y REAL, max_x REAL, max_y REAL, srs_id INTEGER);
        INSERT INTO gpkg_contents VALUES ('wells', 'features', 'Water wells', 'Boreholes surveyed in 2024', '',
            300000, 100000, 400000, 200000, 32637);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, geometry_type_name TEXT, srs_id INTEGER,
            z INTEGER, m INTEGER);
        INSERT INTO gpkg_geometry_columns VALUES ('wells', 'geom', 'POINT', 32637, 0, 0);
        CREATE TABLE wells (fid INTEGER PRIMARY KEY, geom BLOB, depth_m REAL, status TEXT);
        INSERT INTO wells (depth_m, status) VALUES (12.5, 'ok'), (30.0, 'dry');
    """)
    con.commit()
    con.close()
    return path


def write_geojson(path: Path) -> Path:
    doc = {"type": "FeatureCollection", "name": "villages", "features": [
        {"type": "Feature", "properties": {"name": "A", "pop": 120, "surveyed": "2023-05-01"}, "geometry": {"type": "Point", "coordinates": [36.1, -1.2]}},
        {"type": "Feature", "properties": {"name": "B", "pop": 80.5, "surveyed": "2023-06-01"}, "geometry": {"type": "Point", "coordinates": [36.5, -1.0]}},
    ]}  # fmt: skip
    path.write_text(json.dumps(doc))
    return path
