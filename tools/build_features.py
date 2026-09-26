import collections
import json
import math
import os
import re
import sys

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import linemerge, unary_union, substring, nearest_points

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sign_rules import parse_sign as classify_sign, summarize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

to_sp = Transformer.from_crs("EPSG:4326","EPSG:2263",always_xy=True)
to_ll = Transformer.from_crs("EPSG:2263","EPSG:4326",always_xy=True)

# ---------- area polygon (Houston-14th, 6th Ave-Ave A), with a small buffer
AREA_LL = [(-74.0045,40.7285),(-73.9972,40.7390),(-73.9798,40.7318),(-73.9862,40.7212)]
AREA = Polygon([to_sp.transform(*c) for c in AREA_LL])

# ---------- street name normalization
TOK = {"EAST":"E","WEST":"W","NORTH":"N","SOUTH":"S","STREET":"ST","AVENUE":"AVE","PLACE":"PL","SQUARE":"SQ",
       "LANE":"LN","ALLEY":"ALY","FIRST":"1","SECOND":"2","THIRD":"3","FOURTH":"4","FIFTH":"5","SIXTH":"6","SEVENTH":"7"}
ALIAS = {"6AVE":"AVEOFTHEAMERICAS","AVEOFAMERICAS":"AVEOFTHEAMERICAS","SAINTMARKSPL":"STMARKSPL","LAGUARDIAPL":"LAGUARDIAPL","MACDOUGALST":"MACDOUGALST","NDPERLMANPL":"NATHANDPERLMANPL"}
def nkey(s):
    s = re.sub(r"\s+"," ",(s or "").upper().strip())
    k = "".join(TOK.get(t,t) for t in s.split(" "))
    return ALIAS.get(k,k)
def pretty(s):
    s = re.sub(r"\s+"," ",(s or "").strip()).title()
    s = re.sub(r"\b(\d+) Street\b", lambda m: m.group(1)+{1:"st",2:"nd",3:"rd"}.get(int(m.group(1))%10 if int(m.group(1)) not in (11,12,13) else 0,"th")+" St", s)
    s = re.sub(r"\b(\d+) Avenue\b", lambda m: m.group(1)+{1:"st",2:"nd",3:"rd"}.get(int(m.group(1))%10,"th")+" Ave", s)
    s = s.replace(" Street"," St").replace(" Avenue"," Ave").replace("Avenue ","Ave ").replace(" Place"," Pl").replace(" Square"," Sq")
    for w,o in [("First","1st"),("Second","2nd"),("Third","3rd"),("Fourth","4th"),("Fifth","5th"),("Sixth","6th"),("Seventh","7th")]:
        s = re.sub(r"\b"+w+r" Ave\b", o+" Ave", s)
    s = s.replace("East ","E ").replace("West ","W ").replace("St Marks","St Marks")
    for a,b in [("Ave Of The Americas","6th Ave"),("Ave Of Americas","6th Ave"),("Mac Dougal","MacDougal"),("Macdougal","MacDougal"),
                ("La Guardia","LaGuardia"),("Laguardia","LaGuardia"),("Saint Marks","St Marks"),("Sq East","Sq E"),("Sq West","Sq W"),
                ("Sq North","Sq N"),("Sq South","Sq S"),("N D Perlman","Nathan D Perlman"),("Minetta Lane","Minetta Ln")]:
        s = s.replace(a,b)
    return s

# ---------- load signs
raw=json.load(open(os.path.join(DATA, "raw_signs.json")))
groups=collections.defaultdict(list)
for r in raw:
    if not r.get("sign_x_coord") or not r.get("to_street") or not r.get("from_street"): continue
    side=r.get("side_of_street")
    if side not in ("N","S","E","W"): continue
    x,y=float(r["sign_x_coord"]),float(r["sign_y_coord"])
    a,b=sorted([nkey(r["from_street"]),nkey(r["to_street"])])
    key=(nkey(r["on_street"]),a,b,side)
    groups[key].append((x,y,r))

# ---------- centerline
cl=json.load(open(os.path.join(DATA, "centerline.json")))
lines=collections.defaultdict(list)
for c in cl:
    k=nkey(c.get("full_street_name"))
    for part in c["the_geom"]["coordinates"]:
        lines[k].append(LineString([to_sp.transform(*p) for p in part]))
def _lm(v):
    u=unary_union(v)
    return u if u.geom_type=="LineString" else linemerge(u)
merged={k:_lm(v) for k,v in lines.items()}
def comps(g): return list(g.geoms) if hasattr(g,"geoms") else [g]

def cross_point(comp, crosskey, c):
    if crosskey not in merged: return None
    g=merged[crosskey]
    inter=comp.intersection(g)
    pts=[p for p in (inter.geoms if hasattr(inter,"geoms") else [inter]) if not inter.is_empty and p.geom_type=="Point"]
    if pts:
        p=min(pts,key=lambda p:p.distance(c))
        if p.distance(c)<1500: return p
    a,b=nearest_points(comp,g)
    if a.distance(b)<80 and a.distance(c)<1500: return a
    return None

stats=collections.Counter()
def block_geom(key, pts):
    on,a,b,side=key
    P=[Point(x,y) for x,y,_ in pts]
    c=Point(sum(p.x for p in P)/len(P), sum(p.y for p in P)/len(P))
    line=None
    if on in merged:
        comp=min(comps(merged[on]), key=lambda g:g.distance(c))
        if comp.distance(c)<150:
            p1=cross_point(comp,a,c); p2=cross_point(comp,b,c)
            if p1 is not None and p2 is not None:
                d1,d2=sorted([comp.project(p1),comp.project(p2)])
                if 60<d2-d1<2500:
                    cand=substring(comp,d1,d2)
                    if max(p.distance(cand) for p in P)<150: line=cand; stats["geom_centerline"]+=1
            if line is None:
                # use projected sign extent on centerline
                ds=[comp.project(p) for p in P]
                d1,d2=min(ds)-30,max(ds)+30
                d1=max(d1,0); d2=min(d2,comp.length)
                if d2-d1>40: line=substring(comp,d1,d2); stats["geom_signextent_on_centerline"]+=1
    if line is None:
        stats["geom_signs_only"]+=1
        if len(P)<2: return None
        xs=[p.x for p in P]; ys=[p.y for p in P]
        mx,my=sum(xs)/len(xs),sum(ys)/len(ys)
        sxx=sum((x-mx)**2 for x in xs); syy=sum((y-my)**2 for y in ys); sxy=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
        ang=0.5*math.atan2(2*sxy,sxx-syy); ux,uy=math.cos(ang),math.sin(ang)
        t=[(x-mx)*ux+(y-my)*uy for x,y in zip(xs,ys)]
        if max(t)-min(t)<30: return None
        return LineString([(mx+ux*(min(t)-15),my+uy*(min(t)-15)),(mx+ux*(max(t)+15),my+uy*(max(t)+15))])
    # trim ends, offset toward sign side
    L=line.length
    trim=min(28,L*0.12)
    line=substring(line,trim,L-trim)
    # which side are the signs on? use side_of_street compass vs line direction
    (x0,y0),(x1,y1)=line.coords[0],line.coords[-1]
    dx,dy=x1-x0,y1-y0
    # left normal = (-dy,dx)
    want={"N":(0,1),"S":(0,-1),"E":(1,0),"W":(-1,0)}[side]
    # rotate compass to Manhattan grid? use actual sign centroid instead when available
    lx,ly=-dy,dx
    sc=sum(((p.x-x0)*lx+(p.y-y0)*ly) for p in P)
    cmp_ = want[0]*lx+want[1]*ly
    left = sc>0 if abs(sc)/len(P)/math.hypot(lx,ly)>4 else cmp_>0
    off=line.offset_curve(20 if left else -20)
    if off.is_empty: return line
    if off.geom_type!="LineString": off=max(off.geoms,key=lambda g:g.length)
    return off

SOUTH={"PRINCEST","STANTONST","SPRINGST","RIVINGTONST","BROOMEST","GRANDST","KENMAREST","DELANCEYST","CLEVELANDPL"}
RANK={"red":0,"green":1,"yellow":2,"meter":3}
features=[]; skipped=collections.Counter()
for key,pts in groups.items():
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    cen=Point(sum(xs)/len(xs),sum(ys)/len(ys))
    if not AREA.contains(cen): skipped["outside"]+=1; continue
    def num(k):
        m=re.fullmatch(r"[EW](\d+)ST",k); return int(m.group(1)) if m else None
    if any((num(k) or 0)>14 for k in key[:3]) or any(k in SOUTH for k in key[:3]): skipped["outside"]+=1; continue
    rules=[]; seen=set(); meterhint=False; raw_descs=set()
    for x,y,r in pts:
        cs=classify_sign(r["sign_description"])
        if cs is None: continue
        if cs["t"]=="meterhint": meterhint=True; continue
        k=(cs["txt"])
        if k in seen: continue
        seen.add(k); rules.append(cs)
    timed=[r for r in rules if not r["any"]]
    anyt=[r for r in rules if r["any"]]
    has_meter=any(r["t"]=="meter" for r in rules) or meterhint
    if has_meter: cat="meter"
    elif any(r["t"] in ("nopark","nostand","restrict") for r in timed): cat="yellow"
    elif any(r["t"]=="clean" for r in timed): cat="green"
    elif anyt: cat="red"
    else: skipped["no_regulations"]+=1; continue
    if meterhint and not any(r["t"]=="meter" for r in rules):
        rules.append({"t":"meter","any":False,"iv":[],"w":[],"ok":False,"mo":None,
                      "txt":"Pay-by-cell meter zone (hours not in DOT data, check the muni-meter)"})
    g=block_geom(key,pts)
    if g is None: skipped["no_geometry"]+=1; continue
    coords=[[round(to_ll.transform(x,y)[1],6),round(to_ll.transform(x,y)[0],6)] for x,y in g.coords]
    if len(coords)>12: 
        g2=g.simplify(3); coords=[[round(to_ll.transform(x,y)[1],6),round(to_ll.transform(x,y)[0],6)] for x,y in g2.coords]
    r0=pts[0][2]
    on=pretty(r0["on_street"])
    fa,fb=pretty(r0["from_street"]),pretty(r0["to_street"])
    # order rules: anytime last, by type
    order={"nostand":0,"nopark":1,"restrict":2,"clean":3,"meter":4}
    rules.sort(key=lambda r:(r["any"],order.get(r["t"], 9)))
    ok, once, plan = summarize(rules, cat)
    out_rules=[]
    for r in rules:
        item={"t":r["t"],"a":1 if r["any"] else 0,"iv":r["iv"],"x":r["txt"]}
        if r.get("w"): item["w"]=r["w"]
        if r.get("mo"): item["mo"]=r["mo"]
        if not r.get("ok", False): item["ok"]=0
        out_rules.append(item)
    def slug(s):
        return re.sub(r"[^a-z0-9]+","-",(s or "").lower()).strip("-")
    fid=f"{slug(on)}|{key[3].lower()}|{slug(fa)}|{slug(fb)}"
    mid=[round(sum(p[0] for p in coords)/len(coords),6), round(sum(p[1] for p in coords)/len(coords),6)]
    features.append({"id":fid,"on":on,"side":key[3],"a":fa,"b":fb,"cat":cat,"ok":ok,"once":once,"plan":plan,
                     "m":mid,"c":coords,"r":out_rules,"n":len(pts)})

ids=[f["id"] for f in features]
if len(ids)!=len(set(ids)):
    dup=[i for i in ids if ids.count(i)>1]
    raise SystemExit("duplicate ids: "+str(set(dup)))

def hav(a,b):
    import math as _m
    R=6371000
    p1,p2=_m.radians(a[0]),_m.radians(b[0])
    dp=_m.radians(b[0]-a[0]); dl=_m.radians(b[1]-a[1])
    h=_m.sin(dp/2)**2+_m.cos(p1)*_m.cos(p2)*_m.sin(dl/2)**2
    return 2*R*_m.asin(_m.sqrt(h))
WSP=(40.7308,-73.9973)
def near(f, minutes):
    return hav(WSP, f["m"]) <= minutes*80
once=[f for f in features if f["once"]]
plan=[f for f in features if f["plan"]]
once_near=[f for f in once if near(f,12)]
plan_near=[f for f in plan if near(f,12)]
clean=sum(1 for f in features if f["ok"])
meter_unknown=sum(1 for f in features if any(r["t"]=="meter" and not r["iv"] for r in f["r"]))
print("features",len(features))
print("categories", dict(collections.Counter(f["cat"] for f in features)))
print("parse_ok", clean, "of", len(features))
print("meter_hours_unknown", meter_unknown)
print("once_a_week", len(once), "within_12min_of_washington_square", len(once_near))
print("weekly_plan", len(plan), "within_12min", len(plan_near))
for f in once_near[:12]:
    print("  once", f["on"], f["side"], f["a"], "-", f["b"], f["cat"])
for f in plan_near[:12]:
    print("  plan", f["on"], f["side"], f["a"], "-", f["b"])
print("skipped", dict(skipped))
print("geom", dict(stats))
json.dump(features, open(os.path.join(DATA, "features.json"), "w"), separators=(",", ":"))
print("wrote", os.path.join(DATA, "features.json"))
