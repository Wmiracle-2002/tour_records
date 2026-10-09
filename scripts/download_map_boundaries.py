"""Fetch public DataV GeoAtlas boundaries and preserve an auditable manifest."""

import hashlib
import json
from pathlib import Path
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "app/src/main/assets/maps"
CATALOG = ROOT / "app/src/main/assets/administrative_divisions_2023.json"
MUNICIPALITIES = {"110000", "120000", "310000", "500000"}


def validate(data):
    assert data["type"] == "FeatureCollection" and data["features"]
    codes = []
    for feature in data["features"]:
        codes.append(str(feature["properties"]["adcode"]))
        geometry = feature["geometry"]
        assert geometry["type"] in {"Polygon", "MultiPolygon"}
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        assert polygons
        for polygon in polygons:
            assert polygon
            for ring in polygon:
                assert len(ring) >= 4
                assert all(-180 <= p[0] <= 180 and -85 <= p[1] <= 85 for p in ring)
    assert len(codes) == len(set(codes))


def main():
    provinces = json.loads(CATALOG.read_text(encoding="utf-8"))
    codes = ["100000"] + [p["code"].ljust(6, "0") for p in provinces if p["code"].ljust(6, "0") not in MUNICIPALITIES]
    # Read-only public downloads; do not inherit a possibly unavailable local proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    DESTINATION.mkdir(parents=True, exist_ok=True)
    manifest = {"source": "https://datav.aliyun.com/portal/school/atlas/area_selector", "downloaded_on": "2026-10-09", "files": []}
    for code in codes:
        url = f"https://geo.datav.aliyun.com/areas_v3/bound/{code}_full.json"
        with opener.open(url, timeout=30) as response:
            raw = response.read()
        data = json.loads(raw)
        validate(data)
        if code != "100000":
            assert all(str(f["properties"]["parent"]["adcode"]) == code for f in data["features"])
        (DESTINATION / f"{code}.json").write_bytes(raw)
        manifest["files"].append({"code": code, "url": url, "bytes": len(raw), "features": len(data["features"]), "sha256": hashlib.sha256(raw).hexdigest()})
    (DESTINATION / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(codes), "bytes": sum(f["bytes"] for f in manifest["files"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
