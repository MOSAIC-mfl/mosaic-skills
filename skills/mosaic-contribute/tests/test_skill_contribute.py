"""Tests of the mosaic-contribute skill: readers on synthetic files, then scan -> set -> build -> submit --bundle.

The full check with the catalogue's own validator runs when the mosaic-standard tool is installed (CI)."""

from __future__ import annotations

import csv
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "scripts")]
import mosaic_contribute as mc  # noqa: E402
import readers  # noqa: E402
from datafiles import write_geojson, write_geotiff, write_gpkg, write_netcdf, write_shapefile  # noqa: E402

yaml = pytest.importorskip("yaml")


# -- readers ---------------------------------------------------------------------------------------
def test_geotiff_geographic_with_band_names(tmp_path: Path) -> None:
    p = write_geotiff(tmp_path / "ndvi.tif", epsg=4326, origin=(-75.5, -8.0), pixel=0.25, size=(4, 4), bands=2,
                      band_names=["ndvi", "evi"])  # fmt: skip
    f = readers.read_file(p)
    assert f["kind"] == "raster" and f["crs"] == "EPSG:4326"
    assert f["bbox"] == [-75.5, -9.0, -74.5, -8.0]
    assert f["resolution"] == {"value": 0.25, "unit": "degree"}
    assert [v["name"] for v in f["variables"]] == ["ndvi", "evi"]
    assert f["variables"][0]["data_type"] == "float32"


def test_geotiff_utm_is_converted_to_wgs84(tmp_path: Path) -> None:
    p = write_geotiff(tmp_path / "dem.tif", epsg=32718, origin=(499000.0, 9001000.0), pixel=1000.0, size=(2, 2),
                      geographic=False, bits=16, fmt=1)  # fmt: skip
    f = readers.read_file(p)
    assert f["crs"] == "EPSG:32718"
    w, s, e, n = f["bbox"]
    assert -75.01 < w < -75.0 < e < -74.99
    assert -9.06 < s < n < -9.02  # 1000 km south of the equator is about 9.04 degrees
    assert f["resolution"] == {"value": 1000.0, "unit": "m"}
    assert f["variables"][0]["data_type"] == "uint16"


def test_shapefile(tmp_path: Path) -> None:
    p = write_shapefile(tmp_path / "plots.shp", [[(36.0, -1.0), (36.5, -1.0), (36.5, -0.5), (36.0, -1.0)]],
                        {"plot_id": ["P1"], "area_ha": [12]})  # fmt: skip
    f = readers.read_file(p)
    assert (f["kind"], f["geometry_type"], f["feature_count"], f["crs"]) == ("vector", "polygon", 1, "EPSG:4326")
    assert f["bbox"] == [36.0, -1.0, 36.5, -0.5]
    assert f["variables"] == [{"name": "plot_id", "data_type": "string"}, {"name": "area_ha", "data_type": "integer"}]


def test_shapefile_utm_prj_without_code(tmp_path: Path) -> None:
    prj = 'PROJCS["WGS_1984_UTM_Zone_37N",GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984"]],PROJECTION["Transverse_Mercator"]]'
    p = write_shapefile(
        tmp_path / "farms.shp", [[(500000, 0), (510000, 0), (510000, 10000), (500000, 0)]], {"id": [1]}, prj
    )
    f = readers.read_file(p)
    assert f["crs"] == "EPSG:32637"
    assert abs(f["bbox"][0] - 39.0) < 1e-4 and 0.08 < f["bbox"][3] < 0.1


def test_geojson_csv_geopackage_netcdf_kml(tmp_path: Path) -> None:
    g = readers.read_file(write_geojson(tmp_path / "villages.geojson"))
    assert (g["geometry_type"], g["feature_count"], g["bbox"]) == ("point", 2, [36.1, -1.2, 36.5, -1.0])
    assert {v["name"]: v.get("data_type") for v in g["variables"]} == {
        "name": "string",
        "pop": "number",
        "surveyed": "date",
    }

    c = tmp_path / "stations.csv"
    with c.open("w", newline="") as fh:
        csv.writer(fh).writerows(
            [["station", "latitude", "longitude", "rain_mm"], ["a", "-1.5", "36.2", "3.4"], ["b", "-1.0", "36.9", "0"]]
        )
    t = readers.read_file(c)
    assert (t["kind"], t["feature_count"], t["bbox"]) == ("tabular", 2, [36.2, -1.5, 36.9, -1.0])
    assert [d["type"] for d in t["dimensions"]] == ["x", "y"]
    assert [v["name"] for v in t["variables"]] == ["station", "rain_mm"]

    k = readers.read_file(write_gpkg(tmp_path / "wells.gpkg"))
    assert (k["kind"], k["crs"], k["geometry_type"], k["feature_count"]) == ("vector", "EPSG:32637", "point", 2)
    assert k["meta"]["title"] == "Water wells" and [v["name"] for v in k["variables"]] == ["depth_m", "status"]
    assert 37.1 < k["bbox"][0] < 37.3

    n = readers.read_file(write_netcdf(tmp_path / "pr.nc", [-9.75, -9.25, -8.75], [-75.75, -75.25], [0, 31, 59]))
    assert n["bbox"] == [-76.0, -10.0, -75.0, -8.5]
    assert n["time"] == {"start": "2000-01-01", "end": "2000-02-29", "steps": 3}
    assert n["variables"] == [{"name": "pr", "description": "precipitation", "data_type": "float32", "unit": "mm d-1"}]
    assert n["meta"]["license"] == "CC-BY-4.0"

    kml = tmp_path / "sites.kml"
    kml.write_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Sites</name><Placemark><Point>'
                   "<coordinates>10.5,36.1,0</coordinates></Point></Placemark></Document></kml>")  # fmt: skip
    m = readers.read_file(kml)
    assert (m["geometry_type"], m["feature_count"], m["meta"]["title"]) == ("point", 1, "Sites")


def test_zip_and_esri_metadata(tmp_path: Path) -> None:
    shp = write_shapefile(
        tmp_path / "roads.shp", [[(9.0, 36.0), (9.5, 36.0), (9.5, 36.4), (9.0, 36.0)]], {"name": ["x"]}
    )
    Path(str(shp) + ".xml").write_text(
        "<metadata><dataIdInfo><idCitation><resTitle>Roads of Northwestern Tunisia</resTitle></idCitation>"
        "<idAbs>Main roads digitised from 2020 imagery.</idAbs><resConst><Consts><useLimit>CC BY 4.0</useLimit>"
        "</Consts></resConst></dataIdInfo></metadata>"
    )
    f = readers.read_file(shp)
    assert f["meta"]["title"] == "Roads of Northwestern Tunisia" and f["meta"]["license"] == "CC BY 4.0"
    z = tmp_path / "roads.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            zf.write(shp.with_suffix(ext), "roads" + ext)
    zf_facts = readers.read_file(z)
    assert zf_facts["format"] == "ZIP of Shapefile" and zf_facts["bbox"] == [9.0, 36.0, 9.5, 36.4]


# -- YAML writer -----------------------------------------------------------------------------------
def test_yaml_writer_round_trips() -> None:
    obj = {
        "title": "TUNISIA: Admin #2 boundaries", "date": "2020", "yes": "yes", "dash": "- not a list",
        "keywords": ["a, b", "[x]", "plain", "2021-01", "data[].kind"], "empty": [], "n": 3, "f": 0.25, "none": None,
        "long": "word " * 40 + "end", "multi": "line one\nline two", "unicode": "Año – café",
        "nested": [{"name": "x", "roles": ["producer", "licensor"]}, {"bbox": [-75.5, -9.0, 1e-05, 2]}],
    }  # fmt: skip
    assert yaml.safe_load(mc.to_yaml(obj)) == obj


# -- workflow --------------------------------------------------------------------------------------
def make_folder(root: Path) -> Path:
    data = root / "my data"
    data.mkdir()
    for year in (2001, 2002, 2003):
        write_geotiff(data / f"chirps_{year}.tif", epsg=4326, origin=(-75.9, -8.0), pixel=0.05, size=(20, 20))
    write_shapefile(
        data / "ucayali_roads.shp", [[(-75.0, -9.0), (-74.6, -9.0), (-74.6, -8.6), (-75.0, -9.0)]], {"name": ["r1"]}
    )
    (data / "README.md").write_text("Rainfall and roads for Ucayali.")
    (data / "notes.xyz").write_text("not data")
    return data


def run(capsys: pytest.CaptureFixture, work: Path, *args: str) -> str:
    rc = mc.main(["--work", str(work), *args])
    out = capsys.readouterr().out
    assert rc in (0, 1), out
    return out


def test_scan_set_build_bundle(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "fetch_json", lambda *a, **k: None)  # offline: built-in vocabularies
    data = make_folder(tmp_path)
    work = tmp_path / "work"
    out = run(capsys, work, "scan", str(data))
    assert "2 dataset(s)" in out
    assert "d01 | raster | chirps_2001.tif … chirps_2003.tif (3 files)" in out
    assert "README.md" in out and ".xyz" in out
    assert "Ask once for all datasets: contact, license, access" in out
    assert "temporal=2001..2003" in out and "landscapes=[PER-PCL]" in out
    scan = json.loads((work / "scan.json").read_text())
    assert scan["datasets"][0]["suggest"]["themes"][0] == "water-hydrology"

    out = run(capsys, work, "set", "shared.themes=bogus", "d01.description+=x")
    assert "unknown theme" in out and "+= only adds to lists" in out

    out = run(capsys, work, "set", "shared.contact=Test Centre | Ana Test | ana@example.org", "shared.license=CC-BY-4.0",
              "shared.access=restricted", "shared.access_note=On request from the contact.", "accept=all",
              "d01.description=Daily rainfall estimates.", "d02.description=Main roads.", "d02.themes=pressures-drivers")  # fmt: skip
    assert out.startswith("ok:") and "!" not in out
    out = run(capsys, work, "build")
    assert "NEW-01 d01" in out and "missing" not in out.split("structure")[0]
    rec = yaml.safe_load((work / "records/NEW-01/record.yaml").read_text())
    assert rec["temporal"] == {"start_date": "2001", "end_date": "2003"}
    assert rec["spatial"]["landscapes"] == ["PER-PCL"] and rec["spatial"]["geography"] == ["PER"]
    assert rec["contact"][0]["roles"] == ["producer", "licensor", "point-of-contact"]
    assert rec["data"][0]["access_method"] == "request" and "locations" not in rec["data"][0]
    assert "spatial.bbox" in rec["derived"] and "temporal.start_date" not in rec["derived"]
    roads = yaml.safe_load((work / "records/NEW-02/record.yaml").read_text())
    assert roads["data"][0]["geometry_type"] == "polygon" and roads["themes"] == ["pressures-drivers"]

    # answers follow their dataset when the folder changes
    write_geotiff(data / "aaa_dem.tif", epsg=4326, origin=(-75.9, -8.0), pixel=0.05)
    run(capsys, work, "scan", str(data))
    answers = json.loads((work / "answers.json").read_text())
    assert answers["datasets"]["d02"]["description"] == "Daily rainfall estimates."

    out = run(capsys, work, "submit", "--bundle")
    assert "run build first" in out
    run(capsys, work, "build")
    out = run(capsys, work, "submit", "--bundle")
    assert "incomplete" in out  # the new DEM has no description yet
    out = run(capsys, work, "submit", "--bundle", "--allow-incomplete")
    bundle = next(work.glob("mosaic-submission-*.zip"))
    with zipfile.ZipFile(bundle) as z:
        assert {"records/NEW-01/record.yaml", "SUBMISSION.md"} <= set(z.namelist())


def test_official_validator_accepts_built_records(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    pytest.importorskip("mosaic_catalog")
    data = make_folder(tmp_path)
    work = tmp_path / "work"
    run(capsys, work, "scan", str(data))
    run(capsys, work, "set", "shared.contact=Test Centre | Ana Test | ana@example.org", "shared.license=CC-BY-4.0",
        "shared.access=public", "shared.url=https://doi.org/10.5281/zenodo.123", "accept=all",
        "all.description=Test.", "d02.themes=pressures-drivers")  # fmt: skip
    out = run(capsys, work, "build")
    assert "2 checked: 2 complete" in out, out


def test_dates_shared_by_every_dataset_are_ignored(tmp_path: Path) -> None:
    files = [tmp_path / f"MFL-2026-0{i}__layer.tif" for i in range(3)]
    assert mc.date_tokens("MFL-2026-030__Forest2000_Loss2001_2024") == ["2026", "2000", "2001", "2024"]
    sug = mc.suggest_for({"bbox": None}, files[:1], "layer", mc.FALLBACK_LANDSCAPES, {"2026"})
    assert "temporal" not in sug


def test_next_ids(tmp_path: Path) -> None:
    year = mc.date.today().year
    for n in (f"MFL-{year}-007", f"MFL-{year}-010", "MFL-2020-500"):
        (tmp_path / n).mkdir()
    assert mc.next_ids(tmp_path, 2) == [f"MFL-{year}-011", f"MFL-{year}-012"]
