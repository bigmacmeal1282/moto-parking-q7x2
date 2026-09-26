"""Unit tests for sign parsing, using real NYC DOT sign strings."""
import json
import os
import re
import unittest

from sign_rules import parse_sign, summarize, touched_days

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw_signs.json")


def load_descs():
    rows = json.load(open(DATA))
    return sorted({r["sign_description"] for r in rows})


DESCS = load_descs()


def find(fragment):
    frag = fragment.upper()
    hits = [d for d in DESCS if frag in d.upper()]
    if not hits:
        raise AssertionError("sign string not in raw_signs.json: " + fragment)
    return hits[0]


def named_days(desc):
    """Weekdays explicitly written on the sign, before the supersedes clause."""
    head = desc.upper().split("SUPERSEDE")[0]
    if re.search(r"EXCEPT\s+SUN", head) or re.search(r"EXEPT\s+SUN", head):
        return set(range(1, 7))
    if "ALL DAYS" in head:
        return set(range(7))
    if "SCHOOL DAYS" in head:
        return set(range(1, 6))
    found = []
    for m in re.finditer(
        r"MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY|MON|TUES|TUE|WED|THURS|THUR|THU|FRI|SAT|SUN",
        head,
    ):
        w = m.group(0)
        if w.startswith("THU"):
            found.append(4)
        elif w.startswith("TUE"):
            found.append(2)
        elif w.startswith("SU"):
            found.append(0)
        elif w.startswith("MO"):
            found.append(1)
        elif w.startswith("WE"):
            found.append(3)
        elif w.startswith("FR"):
            found.append(5)
        elif w.startswith("SA"):
            found.append(6)
    # MONDAY-FRIDAY style ranges: expand if the text has DAY-DAY.
    ranges = re.findall(
        r"(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)\s*-\s*(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)",
        head,
    )
    if ranges:
        order = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]
        days = set()
        for a, b in ranges:
            i, j = order.index(a), order.index(b)
            k = i
            while True:
                days.add(k)
                if k == j or len(days) > 7:
                    break
                k = (k + 1) % 7
        return days
    return set(found)


class ParseRealSigns(unittest.TestCase):
    def test_broom_mon_thu_two_days(self):
        desc = find("NO PARKING (SANITATION BROOM SYMBOL) MONDAY THURSDAY 8AM-9:30AM")
        r = parse_sign(desc)
        self.assertEqual(r["t"], "clean")
        self.assertTrue(r["ok"])
        self.assertFalse(r["any"])
        self.assertEqual(r["w"], [{"d": [1, 4], "s": 8 * 60, "e": 9 * 60 + 30}])
        self.assertIn("Mon, Thu 8AM to 9:30AM", r["txt"])

    def test_ampersand_days_share_the_time(self):
        # The only "MON & THURS" broom in the extract. A earlier bug treated
        # Thursday as all day because the time came first.
        desc = find("11AM TO 12:30PM MON & THURS")
        r = parse_sign(desc)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["t"], "clean")
        self.assertEqual(len(r["w"]), 1)
        self.assertEqual(r["w"][0]["d"], [1, 4])
        self.assertEqual(r["w"][0]["s"], 11 * 60)
        self.assertEqual(r["w"][0]["e"], 12 * 60 + 30)
        self.assertFalse(any(w["s"] == 0 and w["e"] == 1440 for w in r["w"]))

    def test_except_sunday_broom(self):
        desc = find("NO PARKING (SANITATION BROOM SYMBOL) 8AM-8:30AM EXCEPT SUNDAY")
        r = parse_sign(desc)
        self.assertTrue(r["ok"])
        self.assertEqual(r["w"], [{"d": [1, 2, 3, 4, 5, 6], "s": 8 * 60, "e": 8 * 60 + 30}])
        self.assertIn("Mon-Sat", r["txt"])

    def test_meter_two_clauses(self):
        desc = find("2 HMP MONDAY-FRIDAY 6PM-10PM SATURDAY 8AM-10PM")
        r = parse_sign(desc)
        self.assertTrue(r["ok"])
        self.assertEqual(r["t"], "meter")
        self.assertEqual(r["w"][0], {"d": [1, 2, 3, 4, 5], "s": 18 * 60, "e": 22 * 60})
        self.assertEqual(r["w"][1], {"d": [6], "s": 8 * 60, "e": 22 * 60})
        self.assertIn("Mon-Fri 6PM to 10PM", r["txt"])
        self.assertIn("Sat 8AM to 10PM", r["txt"])

    def test_two_time_ranges_same_days(self):
        desc = find("2 HMP MONDAY-FRIDAY 8:30AM-3PM 8PM-10PM SATURDAY 8:30AM-10PM")
        r = parse_sign(desc)
        self.assertTrue(r["ok"], r["txt"])
        self.assertEqual(
            [(w["d"], w["s"], w["e"]) for w in r["w"]],
            [
                ([1, 2, 3, 4, 5], 8 * 60 + 30, 15 * 60),
                ([1, 2, 3, 4, 5], 20 * 60, 22 * 60),
                ([6], 8 * 60 + 30, 22 * 60),
            ],
        )

    def test_cross_midnight(self):
        desc = find("MOON & STARS (SYMBOLS) NO STANDING 10PM-6AM ALL DAYS")
        r = parse_sign(desc)
        self.assertTrue(r["ok"])
        self.assertEqual(r["t"], "nostand")
        self.assertEqual(r["w"], [{"d": [0, 1, 2, 3, 4, 5, 6], "s": 22 * 60, "e": 6 * 60}])
        self.assertEqual(touched_days(r["w"][0]), set(range(7)))
        # Monday 1:00am is inside the window that started Sunday night.
        self.assertTrue(any(a <= 60 < b or (a > b and (60 >= a or 60 < b)) for a, b in r["iv"]))

    def test_midnight_to_morning_named_days(self):
        desc = find("NO PARKING (SANITATION BROOM SYMBOL) MOON & STARS (SYMBOLS) MONDAY WEDNESDAY FRIDAY MIDNIGHT-3AM")
        r = parse_sign(desc)
        self.assertTrue(r["ok"])
        self.assertEqual(r["w"], [{"d": [1, 3, 5], "s": 0, "e": 3 * 60}])

    def test_anytime_no_standing(self):
        desc = find("NO STANDING ANYTIME")
        r = parse_sign(desc)
        self.assertTrue(r["ok"])
        self.assertTrue(r["any"])
        self.assertEqual(r["iv"], [[0, 10080]])
        self.assertEqual(r["w"], [])

    def test_fri_sun_wraps(self):
        desc = find("NO STANDING FRI-SUN MIDNIGHT-6AM")
        r = parse_sign(desc)
        self.assertTrue(r["ok"])
        self.assertEqual(r["w"][0]["d"], [0, 5, 6])
        self.assertEqual(r["w"][0]["s"], 0)
        self.assertEqual(r["w"][0]["e"], 6 * 60)

    def test_seasonal_thursday(self):
        desc = find("NO STANDING APRIL-OCTOBER THURSDAY 4PM-9PM")
        r = parse_sign(desc)
        self.assertTrue(r["ok"])
        self.assertEqual(r["mo"], [4, 10])
        self.assertEqual(r["w"], [{"d": [4], "s": 16 * 60, "e": 21 * 60}])

    def test_unknown_when_days_do_not_parse(self):
        r = parse_sign("NO PARKING 8AM-9AM ON ALTERNATE BLAHDAYS")
        self.assertIsNotNone(r)
        self.assertFalse(r["ok"])
        self.assertEqual(r["w"], [])
        self.assertEqual(r["iv"], [])
        self.assertIn("unknown, check signs", r["txt"])

    def test_ignores_pay_by_cell_locator(self):
        desc = find("PAY-BY-CELL LOCATOR NUMBER")
        self.assertEqual(parse_sign(desc)["t"], "meterhint")

    def test_ignores_bus_panel(self):
        desc = find("LOCAL MTA BUS DESTINATION PANEL")
        self.assertIsNone(parse_sign(desc))

    def test_every_broom_sign_in_the_extract(self):
        brooms = [d for d in DESCS if "BROOM" in d.upper() or "SANITATIO" in d.upper() and "NO PARKING" in d.upper()]
        self.assertGreater(len(brooms), 20)
        for desc in brooms:
            r = parse_sign(desc)
            self.assertIsNotNone(r, desc)
            self.assertTrue(r["ok"], (desc, r["txt"] if r else None))
            self.assertEqual(r["t"], "clean", desc)
            got = set()
            for w in r["w"]:
                got |= set(w["d"])
            self.assertEqual(got, named_days(desc), desc)

    def test_twice_weekly_cleaning_is_not_once_a_week(self):
        r = parse_sign(find("NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 9AM-10:30AM"))
        ok, once, plan = summarize([r], "green")
        self.assertEqual((ok, once, plan), (1, 0, 0))

    def test_single_cleaning_day_is_once_a_week(self):
        # Same plaque format as the extract, with one weekday.
        r = parse_sign("NO PARKING (SANITATION BROOM SYMBOL) TUESDAY 8AM-9:30AM <->")
        self.assertTrue(r["ok"])
        self.assertEqual(r["w"][0]["d"], [2])
        ok, once, plan = summarize([r], "green")
        self.assertEqual((ok, once, plan), (1, 1, 1))

    def test_meter_plus_one_cleaning_day_still_once(self):
        clean = parse_sign("NO PARKING (SANITATION BROOM SYMBOL) MONDAY 9AM-10:30AM <->")
        meter = parse_sign(find("2 HMP 9AM-7PM EXCEPT SUNDAY"))
        ok, once, plan = summarize([clean, meter], "meter")
        self.assertEqual((ok, once, plan), (1, 1, 1))

    def test_cross_midnight_cleaning_is_not_one_day(self):
        r = parse_sign("NO PARKING (SANITATION BROOM SYMBOL) MONDAY 10PM-6AM <->")
        self.assertTrue(r["ok"])
        self.assertEqual(touched_days(r["w"][0]), {1, 2})
        ok, once, plan = summarize([r], "green")
        self.assertEqual(once, 0)


if __name__ == "__main__":
    unittest.main()
