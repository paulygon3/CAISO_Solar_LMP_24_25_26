"""Generate fixed multi-site PVWatts profiles. Cache source and UTC calendar outputs."""
import csv
import gzip
import io
import itertools
import math
import time as clock
import zipfile
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from common import *

def sites():
    path = ROOT / "evidence/contour.bin"
    raw = json.loads(path.read_text())
    markers = [m for layer in raw["l"] for m in layer["m"]]
    source_date = date.fromisoformat(C["site_evidence_date"])
    at = midnight(source_date)
    with zipfile.ZipFile(ROOT / "evidence/membership.bin") as z, z.open(z.namelist()[0]) as f:
        members = list(csv.DictReader(io.TextIOWrapper(f)))
    for zone, group in C["sites"].items():
        if not math.isclose(sum(w for _,w in group), 1) or any(w <= 0 for _,w in group):
            raise ValueError("invalid site weights")
        for node, frac in group:
            evidence = [m for m in members if m["PNODE_ID"] == node and datetime.fromisoformat(m["EFF_START_DT_GMT"]) <= at <= datetime.fromisoformat(m["EFF_END_DT_GMT"])]
            if {m["APNODE_ID"] for m in evidence} != {C["basis_hubs"][zone]}:
                raise ValueError(f"missing or conflicting site membership {node}")
            coords = {tuple(m["c"]) for m in markers if m["n"]==node and m["a"]=="CA" and m["p"]=="GEN"}
            if len(coords)!=1:raise ValueError(f"ambiguous or missing map coordinates for {node}")
            (lat,lon),=coords
            yield {"zone":zone, "node":node, "share":frac, "lat":round(lat,6), "lon":round(lon,6),
                   "map_published_time":raw["d"],"membership_records":evidence,
                   "map_sha256":sha(path),"membership_sha256":sha(ROOT/"evidence/membership.bin")}

def model(site):
    node = site["node"]
    args = dict(C["pv"],lat=site["lat"],lon=site["lon"])
    path = ROOT / "cache" / (node+"_PVWatts.json")
    meta = ROOT / "manifests" / (node+"_PVWatts.json")
    def check(data):
        r = json.loads(data)
        if r.get("errors") or r.get("warnings"):raise ValueError(repr(r.get("errors"))+" "+repr(r.get("warnings")))
        for k,v in args.items():
            if str(r["inputs"][k])!=str(v):raise ValueError("model input mismatch "+k)
        station=r["station_info"]
        if "NSRDB" not in station["weather_data_source"] or "tmy" not in station["weather_data_source"].lower() or station["tz"]!=-8:
            raise ValueError("unexpected resource or timezone")
        ac=r["outputs"]["ac"]
        if len(ac)!=8760 or any(not math.isfinite(a) or a<0 or a>100e6*1.000001 for a in ac):
            raise ValueError("invalid hourly AC watts")
        if not math.isclose(sum(ac)/1000,r["outputs"]["ac_annual"],rel_tol=0.00001):
            raise ValueError("hourly watts do not reconcile to annual kWh")
        return r
    cached=False
    if meta.exists() and path.exists():
        m=json.loads(meta.read_text())
        cached=m["args"]==args and m["config_hash"]==CONFIG_HASH and m["sha256"]==sha(path)
    if cached:
        r=check(path.read_bytes())
    else:
        key=os.environ.get("PVWATTS_API_KEY") or os.environ.get("NLR_API_KEY") or os.environ.get("NREL_API_KEY")
        # Use the public documentation's demo key unless a key is configured through a header.
        url=C["pv_url"]+"?"+urlencode(args if key else dict(args,api_key="DEMO_KEY"))
        req=Request(url,headers={"X-Api-Key":key} if key else {})
        for attempt in range(1,4):
            try:
                with urlopen(req,timeout=50) as f: data=f.read()
                if key and key.encode() in data:raise ValueError("response includes credential, caching prohibited")
                r=check(data)
                break
            except Exception as e:
                record({"stage":"solar","site":node,"attempt":attempt,"error_type":type(e).__name__})
                if attempt==3:raise RuntimeError(f"PVWatts failure for {node}: {type(e).__name__}") from None
                clock.sleep(2**attempt)
        atomic(path,data)
        save_json(meta,dict(site=site,endpoint=C["pv_url"],args=args,config_hash=CONFIG_HASH,
              retrieved=utcnow(),sha256=sha(path),station=r["station_info"],model_version=r["version"],ssc=r["ssc_info"],
              ac_annual_kwh=r["outputs"]["ac_annual"],samples=len(r["outputs"]["ac"])))
    return [w/(1e6*C["ac_mw"]) for w in r["outputs"]["ac"]]

def tmy_value(values, stamp):
    standard=stamp.astimezone(timezone(timedelta(hours=-8)))
    def idx(m,d):
        return (date(2001,m,d)-date(2001,1,1)).days*24+standard.hour
    if (standard.month,standard.day)==(2,29):
        return (values[idx(2,28)]+values[idx(3,1)])/2, True
    return values[idx(standard.month,standard.day)],False

def generate():
    profiles={z:[0.0]*8760 for z in C["sites"]}
    for site in sites():
        vals=model(site)
        profiles[site["zone"]]=[a+site["share"]*v for a,v in zip(profiles[site["zone"]],vals,strict=True)]
    for a,b in itertools.combinations(profiles.values(),2):
        if a==b:raise ValueError("returned identical zonal profiles")
    keys=list(profiles)
    fields=["utc_interval_start","utc_interval_end","pacific_start_with_offset","delivery_date","local_start_hour","local_fold","leap_day_synthetic","repair_flag","scenario"]
    fields.extend(f"{z}_{s}" for z in keys for s in ("weight","output_mw","weight_hours"))
    status={}
    for year in [2024,2025,2026]:
        end=min(date(year+1,1,1),date.fromisoformat(C["end_exclusive"]))
        dst=ROOT/"profiles"/f"Solar_Profile_{year}.csv.gz"
        dst.parent.mkdir(parents=True,exist_ok=True)
        tmp=dst.with_suffix(".tmp")
        n=leap=0
        with gzip.open(tmp,"wt",newline="") as f:
            out=csv.writer(f);out.writerow(fields)
            for stamp in hours(date(year,1,1),end):
                local=stamp.astimezone(PACIFIC)
                vals=[tmy_value(profiles[z],stamp) for z in keys]
                synthetic=vals[0][1];leap+=int(synthetic)
                base=[stamp.isoformat(),(stamp+HOUR).isoformat(),local.isoformat(),local.date(),local.hour,local.fold,int(synthetic),0,"TMY_2_SITES_PER_ZONE"]
                out.writerow(base+[v for w,_ in vals for v in (w,w*C["ac_mw"],w)])
                n+=1
        os.replace(tmp,dst)
        status[year]=dict(hours=n,leap_synthetic=leap,repair_hours=0,sha256=sha(dst))
    save_json(ROOT/"manifests/solar.json",status)
    print(status)
if __name__=="__main__": generate()
