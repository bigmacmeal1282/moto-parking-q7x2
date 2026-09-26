"""Mobile smoke test for the map and the My bike tab. Screenshots go to /tmp."""
import asyncio
import json
import os

from playwright.async_api import async_playwright

URL = os.environ.get("MOTO_URL", "http://127.0.0.1:8123/")
OUT = os.environ.get("MOTO_SHOT", "/tmp/moto-my-bike.png")
BIKE = "5th-ave|w|w-8th-st|washington-sq-n"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        ctx = await browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
            geolocation={"latitude": 40.7308, "longitude": -73.9973},
            permissions=["geolocation"],
        )
        await ctx.add_init_script("localStorage.setItem('motoParking.bike.v1', %s);" % json.dumps(BIKE))
        page = await ctx.new_page()
        logs = []
        page.on("pageerror", lambda e: logs.append("PAGEERROR " + str(e)))
        page.on("console", lambda m: logs.append(m.type + ": " + m.text) if m.type == "error" else None)
        await page.goto(URL, wait_until="load")
        await page.wait_for_function("window.MOTO && DATA.length > 500")
        report = {}
        report["blocks"] = await page.evaluate("DATA.length")
        report["center"] = await page.evaluate("[map.getCenter().lat.toFixed(4), map.getCenter().lng.toFixed(4)]")
        await page.click("#tabBike")
        await page.wait_for_selector("#suggestions")
        await page.wait_for_timeout(400)
        text = await page.inner_text("#sheet")
        report["has_move_by"] = "Move by " in text and "from now" in text
        report["has_suggestions"] = "min walk" in text and "Good until" in text
        report["has_weekly"] = "weekly plan" in text.lower() and "once a week" in text.lower()
        report["has_asp"] = "ASP calendar" in text and "@NYCASP" in text
        report["saved"] = await page.evaluate("MOTO.getBike()")
        # Tap the first suggestion and park there.
        await page.click("#sheet .row")
        await page.wait_for_selector("#sheet .park")
        report["park_label"] = await page.inner_text("#sheet .park")
        new_id = await page.get_attribute("#sheet .park", "data-id")
        await page.click("#sheet .park")
        await page.wait_for_timeout(300)
        report["after_park"] = await page.evaluate("MOTO.getBike()")
        report["park_changed"] = report["after_park"] == new_id and new_id != BIKE
        report["stored"] = await page.evaluate("localStorage.getItem('motoParking.bike.v1')")
        # Countdown uses New York time, not the VM zone.
        forced = await page.evaluate("""() => {
          window.__NY_NOW = 6*1440 + 16*60 + 32; // Saturday 4:32pm
          const f = MOTO.BYID['5th-ave|w|w-8th-st|washington-sq-n'];
          const headline = MOTO.describeSpot(f, MOTO.nyNow()).headline;
          window.__NY_NOW = undefined;
          return headline;
        }""")
        report["forced_headline"] = forced
        # Unknown rules are not guessed.
        unknown = await page.evaluate("""() => {
          const f = Object.assign({}, DATA.find(x => x.cat==='green'), {ok:0, id:'x'});
          return MOTO.describeSpot(f, MOTO.nyNow()).headline;
        }""")
        report["unknown"] = unknown
        # Map popup still has the original labels.
        await page.click("#tabMap")
        await page.wait_for_timeout(300)
        size = await page.evaluate("[map.getSize().x, map.getSize().y]")
        target = await page.evaluate("""(pt) => {
          const b = map.getBounds(); let best=null;
          for (const f of DATA) {
            if (!['green','yellow','meter'].includes(f.cat)) continue;
            const a=f.c[0], z=f.c[f.c.length-1];
            const m=[(a[0]+z[0])/2,(a[1]+z[1])/2];
            if (!b.contains(m)) continue;
            const p=map.latLngToContainerPoint(m);
            const d=Math.hypot(p.x-pt[0], p.y-pt[1]);
            if (!best || d<best.d) best={d, x:p.x, y:p.y};
          }
          return best;
        }""", [size[0]/2, size[1]*0.55])
        await page.touchscreen.tap(target["x"], target["y"])
        await page.wait_for_timeout(600)
        pop = await page.evaluate("(document.querySelector('.leaflet-popup-content')||{}).innerText||''")
        report["popup_ok"] = all(s in pop for s in ["Free right now", "You must move by", "Posted rules", "New York time"])
        # Back to the bike tab for the screenshot, with the original spot and the list in view.
        await page.evaluate("""(id) => { MOTO.setBike(id, false); }""", BIKE)
        await page.click("#tabBike")
        await page.wait_for_timeout(500)
        sug = await page.query_selector("#suggestions")
        await sug.scroll_into_view_if_needed()
        await page.wait_for_timeout(200)
        # Keep the countdown and the list in one frame: scroll the sheet to the top.
        await page.evaluate("document.getElementById('sheet').scrollTop = 0")
        await page.wait_for_timeout(200)
        box = await page.evaluate("""() => {
          const s = document.getElementById('suggestions').getBoundingClientRect();
          const sheet = document.getElementById('sheet').getBoundingClientRect();
          const row = document.querySelector('#sheet .row');
          const r = row ? row.getBoundingClientRect() : null;
          return {sugTop: s.top, sugInSheet: s.top < sheet.bottom, rowTop: r && r.top, rowBottom: r && r.bottom, sheetBottom: sheet.bottom, vh: window.innerHeight};
        }""")
        report["layout"] = box
        visible = await page.evaluate("""() => {
          const sheet=document.getElementById('sheet').getBoundingClientRect();
          return [...document.querySelectorAll('#sheet .row')].filter(r=>{
            const b=r.getBoundingClientRect();
            return b.top>=sheet.top-2 && b.bottom<=sheet.bottom+2;
          }).length;
        }""")
        report["rows_fully_visible"] = visible
        await page.screenshot(path=OUT, full_page=False)
        await page.click("#sheet [data-act=clear]")
        await page.wait_for_timeout(200)
        report["cleared"] = await page.evaluate("MOTO.getBike()===null && !localStorage.getItem('motoParking.bike.v1')")
        await page.click("#sheet [data-act=loc]")
        await page.wait_for_timeout(800)
        report["snapped"] = await page.evaluate("MOTO.getBike()")
        report["console"] = logs
        report["shot"] = OUT
        print(json.dumps(report, indent=2))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
