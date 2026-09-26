"""Download current Manhattan parking signs for the Village study area.

Writes data/raw_signs.json from NYC Open Data dataset nfid-uabd.
The box is the neighborhood the map covers (about Houston to 14th Street,
6th Avenue to Avenue A), not a home or a single address.
"""
import json
import os
import urllib.parse

import requests
from pyproj import Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "raw_signs.json")

# WGS84 corners of the study area, same box the feature builder clips to.
CORNERS = [(-74.0045, 40.7285), (-73.9972, 40.7390), (-73.9798, 40.7318), (-73.9862, 40.7212)]


def main():
    to_sp = Transformer.from_crs("EPSG:4326", "EPSG:2263", always_xy=True)
    xy = [to_sp.transform(*c) for c in CORNERS]
    xs = [p[0] for p in xy]
    ys = [p[1] for p in xy]
    where = (
        "borough='Manhattan' AND record_type='Current' "
        f"AND sign_x_coord between {int(min(xs))} and {int(max(xs))} "
        f"AND sign_y_coord between {int(min(ys))} and {int(max(ys))}"
    )
    rows = []
    off = 0
    while True:
        q = urllib.parse.urlencode({
            "$where": where,
            "$limit": 50000,
            "$offset": off,
            "$order": "order_number",
        })
        r = requests.get("https://data.cityofnewyork.us/resource/nfid-uabd.json?" + q, timeout=120)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        print(len(batch))
        if len(batch) < 50000:
            break
        off += 50000
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(rows, f)
    print("wrote", OUT, len(rows))


if __name__ == "__main__":
    main()
