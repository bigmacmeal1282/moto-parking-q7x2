"""Parse NYC DOT parking-sign descriptions into weekly time windows.

Sign text comes from NYC Open Data dataset nfid-uabd (field sign_description).
A parse is confident or it is marked unknown — we do not invent a schedule.
"""
import re

DAYN = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
DN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
WEEK = 10080

DAYRE = (
    r"(?:SUNDAY|MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|"
    r"SUN|MON|TUES|TUE|WED|THURS|THUR|THU|FRI|SAT)"
)
TIMEP = r"(?:\d{1,2}(?::\d{2})?\s*(?:AM|PM)|MIDNIGHT|NOON)"
MONTHRE = (
    r"(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|"
    r"OCTOBER|NOVEMBER|DECEMBER|JAN|FEB|MAR|APR|JUN|JUL|AUG|SEP|OCT|NOV|DEC|MAY)"
)

TOKRE = re.compile(
    r"(?P<except>EXCEPT\s+" + DAYRE + r"|EXEPT\s+SUNDAY|EXEPT\s+SUN\b)"
    r"|(?P<all>ALL\s+DAYS)"
    r"|(?P<school>SCHOOL\s+DAYS)"
    r"|(?P<drange>" + DAYRE + r"\s*(?:-|THRU|THROUGH|TO)\s*" + DAYRE + r")"
    r"|(?P<day>" + DAYRE + r")\b"
    r"|(?P<time>" + TIMEP + r"\s*(?:-|TO)\s*" + TIMEP + r")",
    re.I,
)
SEASONRE = re.compile(
    MONTHRE + r"\w*(?:\s+\d{1,2})?\s*-\s*" + MONTHRE + r"\w*(?:\s+\d{1,2})?",
    re.I,
)
LEFTOVER_DAY = re.compile(
    r"\b(?:MON|TUE|WED|THU|FRI|SAT|SUN|NOON|MIDNIGHT|WEEKDAY|WEEKEND)[A-Z]*\b",
    re.I,
)
LEFTOVER_TIME = re.compile(r"\d{1,2}(?::\d{2})?\s*(?:AM|PM)\b", re.I)

MONTHNUM = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def canon_day(s):
    s = s.upper()
    if s.startswith("THU"):
        return 4
    if s.startswith("TUE"):
        return 2
    if s.startswith("SU"):
        return 0
    if s.startswith("MO"):
        return 1
    if s.startswith("WE"):
        return 3
    if s.startswith("FR"):
        return 5
    if s.startswith("SA"):
        return 6
    raise ValueError(s)


def tmin(s, end=False):
    s = re.sub(r"\s+", "", s.upper())
    if s == "MIDNIGHT":
        return 1440 if end else 0
    if s == "NOON":
        return 720
    m = re.match(r"(\d{1,2})(?::(\d{2}))?(AM|PM)", s)
    if not m:
        raise ValueError(s)
    h = int(m.group(1)) % 12
    mi = int(m.group(2) or 0)
    if m.group(3) == "PM":
        h += 12
    val = h * 60 + mi
    if end and val == 0:
        return 1440
    return val


def fmt_t(m):
    if m in (0, 1440):
        return "midnight"
    if m == 720:
        return "noon"
    h, mi = divmod(m, 60)
    ap = "AM" if h < 12 else "PM"
    h = h % 12 or 12
    return f"{h}{(':%02d' % mi) if mi else ''}{ap}"


def fmt_days(ds):
    ds = sorted(ds)
    if ds == list(range(7)):
        return "Every day"
    if ds == [1, 2, 3, 4, 5]:
        return "Mon-Fri"
    if ds == [1, 2, 3, 4, 5, 6]:
        return "Mon-Sat"
    return ", ".join(DN[d] for d in ds)


def _day_set_from(m):
    g = m.lastgroup
    if g == "except":
        word = re.search(DAYRE, m.group("except"), re.I)
        excluded = canon_day(word.group(0)) if word else 0
        return set(range(7)) - {excluded}
    if g == "all":
        return set(range(7))
    if g == "school":
        return set(range(1, 6))
    if g == "drange":
        a, b = re.findall(DAYRE, m.group("drange"), re.I)[:2]
        a, b = canon_day(a), canon_day(b)
        days = set()
        i = a
        while True:
            days.add(i)
            if i == b or len(days) > 7:
                break
            i = (i + 1) % 7
        return days
    return {canon_day(m.group("day"))}


def parse_clauses(core):
    """Group day and time tokens into clauses.

    Days that follow a time (``8AM-9:30AM MON & THURS``) share that time.
    A day that follows a finished day-then-time clause starts a new clause
    (``MONDAY-FRIDAY 6PM-10PM SATURDAY 8AM-10PM``).
    """
    clauses = []
    cur = {"days": set(), "times": [], "days_first": None, "school": False}

    def flush():
        nonlocal cur
        if cur["days"] or cur["times"] or cur["school"]:
            clauses.append(cur)
        cur = {"days": set(), "times": [], "days_first": None, "school": False}

    for m in TOKRE.finditer(core):
        if m.lastgroup == "time":
            a, b = re.findall(TIMEP, m.group("time"), re.I)
            if cur["times"] and cur["days"] and cur["days_first"] is False:
                flush()
            cur["times"].append((tmin(a), tmin(b, True)))
            if cur["days_first"] is None:
                cur["days_first"] = bool(cur["days"])
        else:
            days = _day_set_from(m)
            if cur["times"] and cur["days"] and cur["days_first"] is True:
                flush()
            cur["days"] |= days
            if m.lastgroup == "school":
                cur["school"] = True
            if cur["days_first"] is None and not cur["times"]:
                cur["days_first"] = True
    flush()
    return clauses


def windows_from_clauses(clauses):
    """Return (windows, all_day_without_time, time_without_days)."""
    windows = []
    bare_days = False
    bare_times = False
    for cl in clauses:
        days = set(cl["days"])
        times = list(cl["times"])
        if not days and not times:
            continue
        if times and not days:
            bare_times = True
            continue
        if days and not times:
            bare_days = True
            continue
        for s, e in times:
            windows.append({"d": sorted(days), "s": s, "e": e})
    return windows, bare_days, bare_times


def merge_iv(iv):
    iv = sorted(iv)
    out = []
    for a, b in iv:
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def windows_to_iv(windows):
    iv = []
    for w in windows:
        for d in w["d"]:
            s, e = w["s"], w["e"]
            base = d * 1440
            if e > s:
                iv.append([base + s, base + e])
            elif e < s:
                iv.append([base + s, base + 1440])
                nd = (d + 1) % 7
                iv.append([nd * 1440, nd * 1440 + e])
    return merge_iv(iv)


def touched_days(window):
    days = set(window["d"])
    if window["e"] < window["s"]:
        days |= {(d + 1) % 7 for d in window["d"]}
    return days


def _month_num(token):
    return MONTHNUM[token.upper()[:3]]


def parse_season(core):
    m = SEASONRE.search(core)
    if not m:
        return None, core
    parts = re.findall(MONTHRE, m.group(0), re.I)
    if len(parts) < 2:
        return None, core
    return [_month_num(parts[0]), _month_num(parts[1])], core.replace(m.group(0), " ")


def _leftover_schedule(core):
    stripped = TOKRE.sub(" ", core)
    return bool(LEFTOVER_DAY.search(stripped) or LEFTOVER_TIME.search(stripped))


ALWAYS_PHRASES = (
    "BUS STOP", "BUS LAYOVER", "ACCESS-A-RIDE", "FIRE ZONE", "HOTEL LOADING", "TAXI STAND", "TAXI HAILING",
)


def parse_sign(desc):
    """Parse one sign description.

    Returns None when the record is not a curb regulation (panels, arrows,
    idling notices). Otherwise a dict with type, anytime flag, week-minute
    intervals, structured windows, display text, and ok (confident).
    """
    d = (desc or "").upper()
    meter_hint = ("PAY-BY-CELL" in d) or ("PARKNYC" in d) or ("PAY-BY-APP" in d)
    if meter_hint and not any(k in d for k in ("NO PARK", "NO STAND", "NO STOP", "HMP", "HOUR PARK", "BROOM")):
        return {"t": "meterhint", "any": False, "iv": [], "w": [], "txt": "", "ok": True, "mo": None}

    if "TEMPORARY CONSTRUCTION" in d:
        return None
    if any(k in d for k in (
        "NOT IN EFFECT", "PANEL", "ROUTE", "DELINEATOR", "DESCRIPTION NOT AVAILABLE",
        "INFORMATION", "IDLING", "CURB LINE", "ONE WAY", "CARSHARE SIGN", "RIDER",
        "W/ 3 O'CLOCK",
    )) and not d.startswith("NO STANDING") and not d.startswith("BUS STOP"):
        return None

    core = re.sub(r"\((?:SUPERSED|REVISED|REQUIRES|PRIVATE|PUBLIC|TEXT|FOR |USE AS)[^)]*\)?", "", d)
    core = re.sub(r"SUPERSED.*$", "", core)
    core = re.sub(r"<?-+>|<-+", "", core)
    season, core = parse_season(core)
    # Schedule tokens are outside the symbol parentheticals.
    sched = re.sub(r"\([^)]*\)", " ", core)
    anytime_word = "ANYTIME" in sched
    others_ns = ("OTHER TIMES NO STANDING" in core) or ("OTHERS NO STANDING" in core)

    if "BROOM" in d or "SANITATION" in d:
        t = "clean"
    elif "BUS STOP" in d or "ACCESS-A-RIDE" in d or "BUS LAYOVER" in d:
        t = "nostand"
    elif re.search(r"\b\d+\s*(HMP|MMP)\b", core) or re.search(r"\b\d+\s*HOUR PARKING\b", core):
        t = "restrict" if "COMMERCIAL" in core else "meter"
    elif "NO STOPPING" in core:
        t = "nostand"
    elif "NO STANDING" in core and not any(k in core for k in ("TRUCK", "TAXI", "LOADING ONLY")):
        t = "nostand"
    elif "NO PARKING" in core:
        t = "nopark"
    elif any(k in core for k in (
        "TRUCK", "TAXI", "AVO", "AUTHORIZED", "DOCTOR", "AMBULANCE", "AMBULETTE",
        "LOADING", "FARMERS", "NYP LICENSE", "CARSHARE PARKING", "FIRE ZONE",
    )):
        if "ANGLE PARKING" in core:
            return None
        t = "restrict"
    elif "ANGLE PARKING" in core:
        return None
    else:
        return None

    clauses = parse_clauses(sched)
    notes = []
    if any(cl["school"] for cl in clauses):
        notes.append("school days only")
    windows, bare_days, bare_times = windows_from_clauses(clauses)
    time_tokens = len(re.findall(TIMEP + r"\s*(?:-|TO)\s*" + TIMEP, sched, re.I))
    # "EXCEPT SUNDAY" with no clock is all day on the named days, not a guess.
    if bare_days and not time_tokens and not bare_times:
        windows = [
            {"d": sorted(cl["days"]), "s": 0, "e": 1440}
            for cl in clauses if cl["days"] and not cl["times"]
        ]
        bare_days = False
    parsed_times = sum(len(cl["times"]) for cl in clauses)
    confident = True
    if time_tokens != parsed_times or _leftover_schedule(sched):
        confident = False
    if bare_times or (bare_days and time_tokens):
        confident = False
    if windows and any(w["s"] == w["e"] for w in windows):
        confident = False

    if t == "clean":
        base = "No parking, street cleaning"
    elif t == "nopark":
        base = "No parking"
    elif t == "nostand":
        if "NO STOPPING" in core:
            base = "No stopping"
        elif "BUS" in d and "LAYOVER" in d:
            base = "No standing (MTA bus layover)"
        elif "BUS" in d:
            base = "No standing (bus stop)"
        else:
            base = "No standing"
    elif t == "meter":
        m = re.search(r"(\d+)\s*(HMP|MMP|HOUR PARKING)", core)
        if m:
            n, unit = m.group(1), m.group(2)
            if unit == "HOUR PARKING":
                base = f"{n}-hour parking limit"
            else:
                base = f"Metered, {n}-{'min' if unit == 'MMP' else 'hour'} limit"
        else:
            base = "Metered"
    else:
        if "COMMERCIAL" in core:
            what = "Commercial vehicles only"
        elif "TRUCK LOADING" in core:
            what = "Truck loading only"
        elif "FARMERS" in core:
            what = "Farmers market only"
        elif "TAXI" in core:
            what = "Taxi stand"
        elif "AVO" in core or "AUTHORIZED" in core or "LICENSE PLATES" in core:
            what = "Authorized vehicles only"
        elif "LOADING" in core:
            what = "Loading zone"
        elif "AMBUL" in core:
            what = "Ambulance only"
        elif "FIRE ZONE" in core:
            what = "Fire zone, no standing"
        elif "CARSHARE" in core:
            what = "Carshare only"
        else:
            what = "Restricted"
        if others_ns:
            base = what + ", no standing other times"
        else:
            base = what + " (no parking for you)"

    anytime = False
    if others_ns:
        anytime = True
    elif anytime_word:
        anytime = True
    elif not windows and not bare_times:
        # No clock times. NYC signs with no hours are anytime (bus stops,
        # fire zones, "NO STANDING ANYTIME" already caught, bare "NO STANDING").
        if any(p in d for p in ALWAYS_PHRASES) or not time_tokens:
            anytime = True
        else:
            confident = False

    if t == "meter" and not windows and not anytime_word:
        # A meter plaque with no hours is real, but we will not invent them.
        if not windows:
            confident = False
            anytime = False

    if "BUS STOP" in d or "ACCESS-A-RIDE" in d:
        if "LAYOVER" not in d and not windows:
            anytime = True
    if windows and not time_tokens and not anytime and windows_to_iv(windows) == [[0, WEEK]]:
        anytime = True

    if not confident:
        txt = f"{base}: unknown, check signs"
        windows = []
        iv = []
        anytime = False
    elif anytime and not others_ns:
        txt = f"{base}: anytime"
        windows = []
        iv = [[0, WEEK]]
    elif others_ns:
        txt = f"{base}: anytime for private vehicles"
        windows = []
        iv = [[0, WEEK]]
    elif windows:
        txt = f"{base}: {_fmt_when(windows)}"
        iv = windows_to_iv(windows)
    else:
        txt = f"{base}: unknown, check signs"
        confident = False
        iv = []

    if season and confident:
        txt += f" ({_season_label(season)} only)"
    if notes and confident:
        txt += f" ({', '.join(sorted(set(notes)))})"
    return {
        "t": t,
        "any": bool(anytime) and confident,
        "iv": iv,
        "w": windows if confident and not anytime else [],
        "txt": txt,
        "ok": bool(confident),
        "mo": season,
    }


def _fmt_when(windows):
    groups = []
    for w in windows:
        key = tuple(w["d"])
        if groups and groups[-1][0] == key:
            groups[-1][1].append(w)
        else:
            groups.append((key, [w]))
    parts = []
    for days, ws in groups:
        times = ", ".join(f"{fmt_t(w['s'])} to {fmt_t(w['e'])}" for w in ws)
        parts.append(f"{fmt_days(days)} {times}")
    return "; ".join(parts)


def _season_label(season):
    names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{names[season[0]]}-{names[season[1]]}"


def summarize(rules, cat):
    """Return (ok, once, plan) for a block side.

    once: street cleaning falls on exactly one weekday, and no other
    non-meter rule forces a move on a different weekday.
    plan: that once-a-week side has no prohibition except that cleaning
    (meters are allowed; you pay rather than move).
    """
    ok = True
    for r in rules:
        if r["t"] in ("meter", "meterhint"):
            continue
        if not r.get("ok", False):
            ok = False
    if not ok or cat == "red":
        return int(ok), 0, 0
    days = set()
    clean_days = set()
    types = set()
    for r in rules:
        if r.get("any") or r["t"] in ("meter", "meterhint"):
            continue
        if not r.get("ok", False):
            continue
        if not r.get("w"):
            continue
        types.add(r["t"])
        for w in r["w"]:
            td = touched_days(w)
            days |= td
            if r["t"] == "clean":
                clean_days |= td
    once = len(days) == 1 and len(clean_days) == 1
    plan = once and types == {"clean"}
    return 1, int(once), int(plan)
