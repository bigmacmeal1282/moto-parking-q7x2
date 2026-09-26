"""Write the GitHub Pages site at the repo root from data/features.json."""
import datetime
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")


def pulled_label():
    stamp = os.path.join(DATA, "PULLED.txt")
    if os.path.exists(stamp):
        return open(stamp).read().strip()
    return datetime.date.fromtimestamp(os.path.getmtime(os.path.join(DATA, "features.json"))).strftime("%b %d, %Y").replace(" 0", " ")


def main():
    feats = json.load(open(os.path.join(DATA, "features.json")))
    for f in feats:
        f["c"] = [[round(a, 5), round(b, 5)] for a, b in f["c"]]
        if f.get("m"):
            f["m"] = [round(f["m"][0], 5), round(f["m"][1], 5)]
    data = json.dumps(feats, separators=(",", ":"))
    pulled = pulled_label()
    html = open(os.path.join(TOOLS, "site_template.html")).read().replace("__DATA__", data).replace("__DATE__", pulled)
    open(os.path.join(ROOT, "index.html"), "w").write(html)
    manifest = {
        "name": "Moto Parking",
        "short_name": "Parking",
        "description": "Motorcycle street parking rules from NYC DOT sign records.",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#161b22",
        "theme_color": "#161b22",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": "apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
        ],
    }
    open(os.path.join(ROOT, "manifest.webmanifest"), "w").write(json.dumps(manifest, indent=2) + "\n")
    precache = [
        "./", "index.html", "manifest.webmanifest", "apple-touch-icon.png", "icon-192.png",
        "icon-512.png", "icon-maskable-512.png", "favicon-32.png",
        "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css",
        "vendor/leaflet/images/layers.png", "vendor/leaflet/images/layers-2x.png",
        "vendor/leaflet/images/marker-icon.png", "vendor/leaflet/images/marker-icon-2x.png",
        "vendor/leaflet/images/marker-shadow.png",
    ]
    h = hashlib.sha256()
    for p in precache[1:]:
        h.update(open(os.path.join(ROOT, p), "rb").read())
    version = h.hexdigest()[:10]
    sw = open(os.path.join(TOOLS, "sw_template.js")).read().replace("__VERSION__", version).replace("__PRECACHE__", json.dumps(precache, indent=2))
    open(os.path.join(ROOT, "sw.js"), "w").write(sw)
    print("built", len(html), "bytes, pulled", pulled, "sw version", version)


if __name__ == "__main__":
    main()
