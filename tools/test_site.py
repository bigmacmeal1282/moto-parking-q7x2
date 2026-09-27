"""Mobile smoke test for the map and the My bike tab. Screenshots go to /tmp."""
import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

URL = os.environ.get("MOTO_URL", "http://127.0.0.1:8123/")
OUT = os.environ.get("MOTO_SHOT", "/tmp/moto-my-bike.png")
WEEKLY_OUT = os.environ.get("MOTO_WEEKLY_SHOT", "/tmp/moto-weekly-plan.png")
LOWER_OUT = os.environ.get("MOTO_LOWER_SHOT", "/tmp/moto-lower.png")
BIKE = "5th-ave|w|w-8th-st|washington-sq-n"
METER9 = "5th-ave|e|e-12th-st|e-11th-st"
UNKNOWN = "bowery|w|bleecker-st|e-houston-st"
WEEKLY_LINE = "No once-a-week sides in this area; best is about 3 to 4 days (Mon/Thu cleaning)."


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
        report["has_weekly_line"] = WEEKLY_LINE in text
        report["has_asp"] = "ASP calendar" in text and "@NYCASP" in text
        report["rules"] = await page.evaluate(
            """({meterId, unknownId}) => {
              const SAT = 6*1440 + 16*60 + 32;
              const SUN8 = 20*60;
              const meter = MOTO.BYID[meterId];
              const unknown = MOTO.BYID[unknownId];
              const bike = MOTO.BYID['5th-ave|w|w-8th-st|washington-sq-n'];
              const satMeter = MOTO.stayFrom(meter, SAT);
              const sunMeter = MOTO.stayFrom(meter, SUN8);
              const sunBike = MOTO.stayFrom(bike, SUN8);
              const unknownStay = MOTO.stayFrom(unknown, SAT);
              const unknownSpot = MOTO.describeSpot(unknown, SAT);
              const prevRank = rankAt;
              const prevBike = MOTO.getBike();
              rankAt = 'now';
              const sunRows = MOTO.rankSuggestions(SUN8).rows.map(s => ({
                id: s.f.id, cat: s.f.cat, stay: s.stay, metered: s.metered, kind: s.kind, capped: s.capped
              }));
              rankAt = 'move';
              const moveRows = MOTO.rankSuggestions(SAT).rows.map(s => ({
                id: s.f.id, cat: s.f.cat, stay: s.stay, metered: s.metered, kind: s.kind, capped: s.capped
              }));
              rankAt = prevRank;
              const unknownMeter = f => f.r.some(r => r.t==='meter' && (!r.iv || !r.iv.length));
              const unknownCount = DATA.filter(unknownMeter).length;
              const villageUnknown = DATA.filter(f => f.m[0] > 40.7218 && unknownMeter(f)).length;
              function meterBeatsShorterFree(rows){
                for (let i=0;i<rows.length;i++){
                  if (!rows[i].metered) continue;
                  for (let j=i+1;j<rows.length;j++){
                    if (!rows[j].metered && rows[i].stay <= rows[j].stay) return false;
                  }
                }
                return true;
              }
              return {
                satMeter, sunMeter, sunBike, unknownStay,
                unknownHeadline: unknownSpot.headline,
                unknownDetail: unknownSpot.detail,
                unknownFree: unknownSpot.freeStay,
                sunRows, moveRows,
                sunOrder: meterBeatsShorterFree(sunRows),
                moveOrder: meterBeatsShorterFree(moveRows),
                unknownCount, villageUnknown,
                sunGood: (function(){ const w=sunMeter; return w.goodAt; })()
              };
            }""",
            {"meterId": METER9, "unknownId": UNKNOWN},
        )
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
        # Lower Manhattan: jump, popup, and suggestions around a bike saved there.
        await page.click("#tabMap")
        await page.wait_for_timeout(200)
        await page.evaluate("map.closePopup(); true")
        await page.click("#areas [data-area=lower]")
        await page.wait_for_timeout(500)
        report["lower_view"] = await page.evaluate("""() => {
          const c = map.getCenter();
          const zoom = document.querySelector('.leaflet-control-zoom').getBoundingClientRect();
          const buttons = [...document.querySelectorAll('#areas button')].map(b => {
            const r = b.getBoundingClientRect();
            return {area: b.dataset.area, on: b.classList.contains('on'), top: r.top, left: r.left, right: r.right, bottom: r.bottom, h: r.height};
          });
          return {
            lat: c.lat, lng: c.lng, zoom: map.getZoom(),
            blocks: DATA.filter(f => f.m[0] < 40.7215).length,
            village: DATA.filter(f => f.m[0] > 40.7218).length,
            buttons, vw: window.innerWidth, vh: window.innerHeight, zoomBottom: zoom.bottom
          };
        }""")
        size = await page.evaluate("[map.getSize().x, map.getSize().y]")
        lower_target = await page.evaluate("""(pt) => {
          const b = map.getBounds(); let best=null;
          for (const f of DATA) {
            if (!['green','yellow','meter'].includes(f.cat)) continue;
            if (f.m[0] > 40.7215) continue;
            const a=f.c[0], z=f.c[f.c.length-1];
            const m=[(a[0]+z[0])/2,(a[1]+z[1])/2];
            if (!b.contains(m)) continue;
            const p=map.latLngToContainerPoint(m);
            const d=Math.hypot(p.x-pt[0], p.y-pt[1]);
            if (!best || d<best.d) best={d, x:p.x, y:p.y, id:f.id};
          }
          return best;
        }""", [size[0]*0.42, size[1]*0.55])
        report["lower_target"] = lower_target
        if lower_target:
            await page.touchscreen.tap(lower_target["x"], lower_target["y"])
            await page.wait_for_timeout(600)
        lower_pop = await page.evaluate("(document.querySelector('.leaflet-popup-content')||{}).innerText||''")
        report["lower_popup_ok"] = all(s in lower_pop for s in ["Free right now", "You must move by", "Posted rules", "New York time"])
        report["lower_popup"] = lower_pop[:240]
        await page.screenshot(path=LOWER_OUT, full_page=False)
        report["lower_bike"] = await page.evaluate("""() => {
          map.closePopup();
          const cand = DATA.filter(f => f.m[0] > 40.710 && f.m[0] < 40.716 && f.m[1] < -74.012 && f.m[1] > -74.017 && f.ok && f.cat !== 'red');
          const bike = cand.find(f => f.cat === 'green') || cand[0];
          MOTO.setBike(bike.id, false);
          rankAt = 'now';
          const ranked = MOTO.rankSuggestions(MOTO.nyNow());
          const stretches = MOTO.cleaningStretches();
          return {
            id: bike.id,
            label: ranked.origin.label,
            n: ranked.rows.length,
            walks: ranked.rows.map(s => s.walk),
            lats: ranked.rows.map(s => +s.f.m[0].toFixed(5)),
            anchor: MOTO.planAnchor().label,
            stretchLats: stretches.map(s => +s.f.m[0].toFixed(5)),
            sheet: document.getElementById('sheet').innerText.slice(0, 500)
          };
        }""")
        # Back to the bike tab for the screenshot, with the original spot and the list in view.
        # Saturday 4:32pm is inside typical meter hours, so a legal week-long reading would be wrong.
        await page.evaluate("""(id) => {
          window.__NY_NOW = 6*1440 + 16*60 + 32;
          rankAt = 'move';
          MOTO.setBike(id, false);
        }""", BIKE)
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
        sheet_text = await page.inner_text("#sheet")
        report["shot_has_weekly_line"] = WEEKLY_LINE in sheet_text
        report["shot_no_7day"] = "7-day limit" not in sheet_text
        report["shot_top"] = await page.evaluate("""() => {
          const sug = document.getElementById('suggestions');
          const weekly = document.getElementById('weekly');
          const list = [];
          let el = sug.nextElementSibling;
          while (el && el !== weekly) {
            if (el.classList && el.classList.contains('row')) list.push(el.innerText.replace(/\\s+/g, ' ').trim());
            el = el.nextElementSibling;
          }
          return list.slice(0, 4);
        }""")
        await page.screenshot(path=OUT, full_page=False)
        weekly = await page.query_selector("#weekly")
        await weekly.scroll_into_view_if_needed()
        await page.wait_for_timeout(200)
        await page.screenshot(path=WEEKLY_OUT, full_page=False)
        window_now = await page.evaluate("window.__NY_NOW = undefined; true")
        report["clock_restored"] = window_now
        await page.click("#sheet [data-act=clear]")
        await page.wait_for_timeout(200)
        report["cleared"] = await page.evaluate("MOTO.getBike()===null && !localStorage.getItem('motoParking.bike.v1')")
        await page.click("#sheet [data-act=loc]")
        await page.wait_for_timeout(800)
        report["snapped"] = await page.evaluate("MOTO.getBike()")
        report["console"] = logs
        report["shot"] = OUT
        report["weekly_shot"] = WEEKLY_OUT
        report["lower_shot"] = LOWER_OUT
        # Wider view of the new area, with a popup, for the map check.
        desk = await browser.new_context(viewport={"width": 1100, "height": 800})
        dpage = await desk.new_page()
        dlogs = []
        dpage.on("pageerror", lambda e: dlogs.append(str(e)))
        await dpage.goto(URL, wait_until="load")
        await dpage.wait_for_function("window.MOTO && DATA.length > 1000")
        await dpage.click("#areas [data-area=lower]")
        await dpage.wait_for_timeout(700)
        dsize = await dpage.evaluate("[map.getSize().x, map.getSize().y]")
        dtarget = await dpage.evaluate("""(pt) => {
          const b = map.getBounds(); let best=null;
          for (const f of DATA) {
            if (!['green','yellow','meter'].includes(f.cat) || f.m[0] > 40.7215) continue;
            const a=f.c[0], z=f.c[f.c.length-1];
            const m=[(a[0]+z[0])/2,(a[1]+z[1])/2];
            if (!b.contains(m)) continue;
            const p=map.latLngToContainerPoint(m);
            const d=Math.hypot(p.x-pt[0], p.y-pt[1]);
            if (!best || d<best.d) best={d, x:p.x, y:p.y};
          }
          return best;
        }""", [dsize[0]*0.48, dsize[1]*0.52])
        if dtarget:
            await dpage.mouse.click(dtarget["x"], dtarget["y"])
            await dpage.wait_for_timeout(500)
        report["desk_popup"] = await dpage.evaluate("(document.querySelector('.leaflet-popup-content')||{}).innerText||''")
        await dpage.screenshot(path=LOWER_OUT.replace(".png", "-wide.png"), full_page=False)
        report["desk_errors"] = dlogs
        await desk.close()
        print(json.dumps(report, indent=2))
        await browser.close()
        errors = []
        rules = report["rules"]
        if rules["satMeter"]["kind"] != "paid" or rules["satMeter"]["freeStay"] != 0:
            errors.append("saturday afternoon meter should be a short paid stay, not a free week")
        if rules["satMeter"].get("paidStay") != 120:
            errors.append("2-hour meter paid stay should be 120 minutes, got %s" % rules["satMeter"])
        if rules["sunMeter"]["kind"] != "then-meter" or rules["sunMeter"]["freeStay"] != 780:
            errors.append("sunday evening 9am meter should be free until Monday 9am (780 min), got %s" % rules["sunMeter"])
        if rules["sunBike"]["freeStay"] >= rules["sunMeter"]["freeStay"]:
            errors.append("the 9am meter should outlast the Monday 8:30am cleaning side on Sunday evening")
        if not rules["sunOrder"] or not rules["moveOrder"]:
            errors.append("a meter outranked a free side with an equal or longer free stay")
        if any(r["metered"] and r["capped"] for r in rules["sunRows"] + rules["moveRows"]):
            errors.append("a metered suggestion was labeled with the 7-day cap")
        if any(r["metered"] for r in rules["moveRows"]):
            errors.append("at Monday move time, meters (which start within the hour) should not outrank free sides")
        if rules["moveRows"] and rules["moveRows"][0]["metered"]:
            errors.append("top suggestion at move time is metered")
        if rules["villageUnknown"] != 12:
            errors.append("expected 12 Village pay-by-cell sides, got %s" % rules["villageUnknown"])
        if rules["unknownCount"] != 58:
            errors.append("expected 58 pay-by-cell sides in both areas, got %s" % rules["unknownCount"])
        if rules["unknownFree"] != 0 or "muni-meter" not in (rules["unknownDetail"] or "").lower():
            errors.append("unknown meter hours should not count as a free week: %s" % rules)
        if "7-day" in (rules["unknownHeadline"] or "") or "7-day" in (rules["unknownDetail"] or ""):
            errors.append("unknown meter copy still mentions a 7-day stay")
        if not report["has_weekly_line"] or not report["shot_has_weekly_line"]:
            errors.append("weekly plan is missing the once-a-week sentence")
        if not report["shot_no_7day"]:
            errors.append("visible sheet still says 7-day limit")
        if not report["shot_top"] or any("7-day" in row or "Metered" in row for row in report["shot_top"]):
            errors.append("top suggestions should be free sides, got %s" % report["shot_top"])
        if any("then meter" not in row and "Metered" in row for row in report["shot_top"]):
            errors.append(report["shot_top"])
        if report["forced_headline"] != "Move by Mon 8:30am, 1d 16h from now":
            errors.append("headline changed: %s" % report["forced_headline"])
        if report["unknown"] != "Unknown, check signs":
            errors.append(report["unknown"])
        if not report["popup_ok"] or not report["park_changed"] or not report["cleared"]:
            errors.append("interaction check failed")
        view = report.get("lower_view") or {}
        if view.get("village") != 575 or view.get("blocks") != 625:
            errors.append("area counts changed: %s" % view)
        if abs(view.get("lat", 0) - 40.713) > 0.004 or abs(view.get("lng", 0) + 74.0125) > 0.004:
            errors.append("Lower Manhattan view missed the box: %s" % view)
        buttons = view.get("buttons") or []
        if len(buttons) != 2 or not any(b.get("area") == "lower" and b.get("on") for b in buttons):
            errors.append("area buttons: %s" % buttons)
        for b in buttons:
            if b["top"] < 0 or b["left"] < 0 or b["right"] > view.get("vw", 0) + 1 or b["h"] < 32:
                errors.append("area button outside the mobile viewport: %s" % b)
            if b["top"] < view.get("zoomBottom", 0) and b["left"] < 60:
                errors.append("area button overlaps zoom: %s" % b)
        if not report.get("lower_popup_ok"):
            errors.append("lower popup failed: %s" % report.get("lower_popup"))
        bike = report.get("lower_bike") or {}
        if bike.get("label") != "your bike" or bike.get("anchor") != "your bike":
            errors.append("suggestions did not follow the saved bike: %s" % bike)
        if not bike.get("n") or any(w > 15 for w in bike.get("walks") or []):
            errors.append("lower suggestions out of range: %s" % bike)
        if any(lat > 40.722 for lat in (bike.get("lats") or []) + (bike.get("stretchLats") or [])):
            errors.append("lower plan reached the Village: %s" % bike)
        if "your bike" not in (bike.get("sheet") or ""):
            errors.append("weekly plan copy is not anchored on the bike")
        if report["console"]:
            errors.append(report["console"])
        if report.get("desk_errors"):
            errors.append(report["desk_errors"])
        if not all(s in (report.get("desk_popup") or "") for s in ["Free right now", "Posted rules"]):
            errors.append("desktop lower popup failed")
        if errors:
            print("FAILED", json.dumps(errors, indent=2), file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
