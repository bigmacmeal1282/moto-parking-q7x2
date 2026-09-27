"""Download current Manhattan parking signs and street centerlines.

Writes data/raw_signs.json (NYC Open Data dataset nfid-uabd) and adds any
missing street-centerline segments to data/centerline.json (dataset inkn-q76z).

Two neighborhood boxes:
- Greenwich Village / Washington Square (Houston St to 14th St, 6th Ave to Ave A)
- Lower Manhattan: Battery Park City, the southern edge of Tribeca, and the
  west side of the Financial District (about Chambers St south to Battery
  Place, the Hudson River east to about Broadway / Church St)

Corners are the study-area extent only. Centerline rows keep street geometry
and names; house-number fields from the centerline dataset are not stored.
Segments already in data/centerline.json are left unchanged.
"""
import datetime
import json
import os
import urllib.parse

import requests
from pyproj import Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SIGNS_OUT = os.path.join(DATA, "raw_signs.json")
CENTERLINE_OUT = os.path.join(DATA, "centerline.json")
PULLED_OUT = os.path.join(DATA, "PULLED.txt")

SIGNS_URL = "https://data.cityofnewyork.us/resource/nfid-uabd.json"
CENTERLINE_URL = "https://data.cityofnewyork.us/resource/inkn-q76z.json"
CENTERLINE_FIELDS = ",".join([
    "the_geom", "full_street_name", "stname_label", "rw_type", "physicalid",
    "l_blockfaceid", "r_blockfaceid", "trafdir",
])
# Roadway and alley segments. Paths are kept only when a street has no roadway,
# so a greenway that shares a name does not pull the curb line off the street.
ROAD_TYPES = {"1", "2", "8", "10"}
PATH_TYPES = {"6"}
# Extra centerline past the sign box so a cross street just outside still matches.
CENTERLINE_BUFFER = 0.001

# WGS84 corners. The same boxes the feature builder clips to.
AREAS = [
    {
        "id": "village",
        "corners": [(-74.0045, 40.7285), (-73.9972, 40.7390), (-73.9798, 40.7318), (-73.9862, 40.7212)],
    },
    {
        "id": "lower",
        "corners": [(-74.0200, 40.7050), (-74.0050, 40.7050), (-74.0050, 40.7210), (-74.0200, 40.7210)],
    },
]


def _get(url, params):
    q = urllib.parse.urlencode(params)
    r = requests.get(url + "?" + q, timeout=120)
    r.raise_for_status()
    return r.json()


def _bbox(corners):
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    return min(lons), min(lats), max(lons), max(lats)


def fetch_signs(corners):
    to_sp = Transformer.from_crs("EPSG:4326", "EPSG:2263", always_xy=True)
    xy = [to_sp.transform(*c) for c in corners]
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
        batch = _get(SIGNS_URL, {
            "$where": where,
            "$limit": 50000,
            "$offset": off,
            "$order": "order_number",
        })
        rows.extend(batch)
        print(len(batch))
        if len(batch) < 50000:
            break
        off += 50000
    return rows


def _polygon_wkt(corners, buf):
    west, south, east, north = _bbox(corners)
    west -= buf
    south -= buf
    east += buf
    north += buf
    ring = f"{west} {south}, {east} {south}, {east} {north}, {west} {north}, {west} {south}"
    return f"POLYGON(({ring}))"


def fetch_centerline(corners):
    where = f"intersects(the_geom, '{_polygon_wkt(corners, CENTERLINE_BUFFER)}')"
    rows = []
    off = 0
    while True:
        batch = _get(CENTERLINE_URL, {
            "$select": CENTERLINE_FIELDS,
            "$where": where,
            "$limit": 5000,
            "$offset": off,
            "$order": "physicalid",
        })
        rows.extend(batch)
        print("centerline", len(batch))
        if len(batch) < 5000:
            break
        off += 5000
    return rows


def _sig(row):
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def merge_signs(existing, fresh):
    """Keep every stored row, then append sign records that are not already there.

    Stored Village rows stay in their original order, including duplicate work
    orders, so rebuilding does not change blocks that were already published.
    """
    out = list(existing)
    seen = {_sig(r) for r in existing}
    for row in fresh:
        sig = _sig(row)
        if sig in seen:
            continue
        out.append(row)
        seen.add(sig)
    return out


def _nkey(name):
    toks = {"EAST": "E", "WEST": "W", "NORTH": "N", "SOUTH": "S", "STREET": "ST",
            "AVENUE": "AVE", "PLACE": "PL", "SQUARE": "SQ", "LANE": "LN", "ALLEY": "ALY"}
    parts = (name or "").upper().split()
    return "".join(toks.get(p, p) for p in parts)


def _coords(geom):
    if not geom:
        return
    gtype = geom.get("type")
    if gtype == "LineString":
        yield from geom.get("coordinates") or []
    elif gtype == "MultiLineString":
        for part in geom.get("coordinates") or []:
            yield from part


def _hits_box(seg, corners, buf):
    west, south, east, north = _bbox(corners)
    west -= buf
    south -= buf
    east += buf
    north += buf
    for lon, lat in _coords(seg.get("the_geom")):
        if west <= lon <= east and south <= lat <= north:
            return True
    return False


def _keep_centerline(seg, road_names):
    rw = str(seg.get("rw_type"))
    if rw in ROAD_TYPES:
        return True
    if rw in PATH_TYPES and _nkey(seg.get("full_street_name")) not in road_names:
        return True
    return False


def merge_centerline(existing, fresh, lower_corners):
    """Append new roadway segments. Do not replace stored Village geometry."""
    road_names = set()
    for seg in list(existing) + list(fresh):
        if str(seg.get("rw_type")) in ROAD_TYPES:
            road_names.add(_nkey(seg.get("full_street_name")))
    have = {str(seg.get("physicalid")) for seg in existing}
    out = list(existing)
    added = 0
    for seg in fresh:
        pid = str(seg.get("physicalid"))
        if pid in have or not _keep_centerline(seg, road_names):
            continue
        # The committed Village extract stays as it was. New ids are the
        # Lower Manhattan streets (and cross streets just outside that box).
        if existing and not _hits_box(seg, lower_corners, CENTERLINE_BUFFER):
            continue
        out.append(seg)
        have.add(pid)
        added += 1
    return out, added


def _load(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def main():
    os.makedirs(DATA, exist_ok=True)
    fresh_signs = []
    fresh_cl = []
    for area in AREAS:
        print("signs", area["id"])
        got = fetch_signs(area["corners"])
        print(" area", area["id"], "signs", len(got))
        fresh_signs.extend(got)
        print("centerline", area["id"])
        cl = fetch_centerline(area["corners"])
        print(" area", area["id"], "centerline", len(cl))
        fresh_cl.extend(cl)
    signs = merge_signs(_load(SIGNS_OUT), fresh_signs)
    lower = next(a["corners"] for a in AREAS if a["id"] == "lower")
    centerline, added = merge_centerline(_load(CENTERLINE_OUT), fresh_cl, lower)
    with open(SIGNS_OUT, "w") as f:
        json.dump(signs, f)
    with open(CENTERLINE_OUT, "w") as f:
        json.dump(centerline, f)
    pulled = datetime.date.today().strftime("%b %d, %Y").replace(" 0", " ")
    with open(PULLED_OUT, "w") as f:
        f.write(pulled + "\n")
    print("wrote", SIGNS_OUT, len(signs))
    print("wrote", CENTERLINE_OUT, len(centerline), "added", added)
    print("wrote", PULLED_OUT, pulled)


if __name__ == "__main__":
    main()
