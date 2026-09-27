# Moto Parking

Static map of motorcycle street-parking rules for two Manhattan neighborhoods, built from NYC DOT sign records: Greenwich Village around Washington Square, and Lower Manhattan (Battery Park City, the southern edge of Tribeca, and the west side of the Financial District). It installs on an iPhone home screen, and a service worker caches the app so it opens offline.

GitHub Pages serves this repository from the root of `main`.

Block sides are green (free except street cleaning), yellow (free nights and weekends), blue (metered), or red (no parking or standing). Tap a side for the posted rules. Village and Lower Manhattan jump the map between the two areas. Recenter returns to Washington Square Park (40.7308, -73.9973).

The My bike tab saves the side where the motorcycle is parked (tap the map, or snap from the phone's location). The spot is stored in local storage. The tab counts down, in New York time, to the next restriction and lists nearby legal sides, using the saved spot as the starting point in either area. A metered side is free until meter hours start, then only a short paid stay (usually 1–2 hours), not all week. Pay-by-cell sides whose hours are missing say to check the muni-meter. A side is badged once-a-week only when street cleaning falls on a single weekday and nothing else forces a midweek move. If a sign cannot be parsed confidently, the tab says to check the signs.

NYC suspends alternate side parking on some holidays. The app links to the [official ASP calendar](https://www.nyc.gov/site/finance/vehicles/alternate-side-parking.page) and [@NYCASP](https://x.com/NYCASP) instead of hard-coding those days.

## Rebuild

```bash
pip install -r tools/requirements.txt
python tools/fetch_signs.py      # optional; refreshes data/raw_signs.json from NYC Open Data
python tools/build_features.py   # signs + centerline -> data/features.json
python tools/build_site.py       # writes index.html, manifest.webmanifest, sw.js
python tools/make_icons.py       # optional; regenerates the home-screen icons
python tools/test_sign_rules.py
```

`data/raw_signs.json` is the NYC Open Data extract (dataset `nfid-uabd`). `data/centerline.json` is the street centerline for the same areas. The Village box is roughly Houston Street to 14th Street, between 6th Avenue and Avenue A. The Lower Manhattan box is roughly lat 40.7050 to 40.7210 and lon -74.0200 to -74.0050. Those figures are area corners only. DOT sign records are old work orders; the sign on the pole wins.
