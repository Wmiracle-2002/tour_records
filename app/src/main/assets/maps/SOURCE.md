# Boundary source

Public geographic data from Alibaba Cloud DataV.GeoAtlas:
https://datav.aliyun.com/portal/school/atlas/area_selector

Downloaded 2026-10-09. `manifest.json` records every URL, byte count,
feature count and SHA256. Raw GeoJSON geometries are preserved without
removing islands, polygon holes or the extra national boundary feature.

`100000.json` contains 35 national features. Other files contain province
children. Municipalities reuse their national polygon because the travel
record model selects the municipality, not its districts.

The app's 2023 selectable city catalog includes Xinxing (659011) and Baiyang
(659012), which are absent from this boundary version. Both remain available
through the city selector; no substitute polygon is invented.

Public boundaries contain no account data. Regenerate with
`python scripts/download_map_boundaries.py` and verify all assets before use.
