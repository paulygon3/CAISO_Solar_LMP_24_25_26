"""Public OASIS daily and reference requests. No AWS calls."""
import argparse
import csv
import io
import random
import time as clock
import zipfile
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import xml.etree.ElementTree as ET
from common import *

REFERENCE = {
    "ATL_PNODE_MAP": (1, {"pnode_id": "ALL"}, {"APNODE_ID", "PNODE_ID"}),
    "ATL_PNODE": (1, {"pnode_id": "ALL", "pnode_type": "ALL"}, {"PNODE_ID"}),
    "ATL_APNODE": (1, {"apnode_id": "ALL", "apnode_type": "ALL"}, {"APNODE_ID"}),
    "ATL_TAC_AREA_MAP": (1, {}, {"PNODE_ID"}),
    "ATL_HUB": (1, {}, {"APNODE_ID"}),
}
PRICE_COLS = {"NODE", "NODE_ID", "MW", "INTERVALSTARTTIME_GMT", "INTERVALENDTIME_GMT", "OPR_DT", "OPR_HR", "MARKET_RUN_ID", "LMP_TYPE"}
last = 0.0

def validate(path, required):
    schema = {}
    with zipfile.ZipFile(path) as z:
        if not z.namelist():
            raise ValueError("empty ZIP")
        for name in z.namelist():
            if name.lower().endswith(".xml"):
                root = ET.fromstring(z.read(name))
                raise ValueError("OASIS XML payload: " + " ".join(root.itertext()).strip()[:500])
            if not name.lower().endswith(".csv"):
                raise ValueError("unexpected ZIP member " + name)
            with z.open(name) as f:
                head = f.readline().decode("utf-8-sig").rstrip("\r\n")
                cols = next(csv.reader([head]))
                if not required.issubset(cols):
                    raise ValueError("unexpected headers " + repr(cols))
                # OASIS CSV exports here are physical-line records. Data parsing rechecks grain.
                lines = 0
                tail = b""
                while chunk := f.read(1024 * 1024):
                    lines += chunk.count(b"\n")
                    tail = chunk[-1:]
                count = lines + int(bool(tail) and tail != b"\n")
                if count == 0:
                    raise ValueError("empty CSV " + name)
                schema[name] = {"columns": cols, "records": count}
    return schema

def query(day, report, nodes=None, refresh=False, end=None):
    global last
    end = end or day + DAY
    price = report == C["report"]
    ver, extra, req = (C["version"], {"market_run_id": C["market"]}, PRICE_COLS) if price else REFERENCE[report]
    args = dict(startdatetime=midnight(day).strftime("%Y%m%dT%H:%M-0000"),
                enddatetime=midnight(end).strftime("%Y%m%dT%H:%M-0000"),
                resultformat=6, queryname=report, version=ver, **extra)
    if price:
        args.update({"node": ",".join(nodes)} if nodes else {"grp_type":"ALL"})
    sig = hashlib.sha256(json.dumps(args,sort_keys=True).encode()).hexdigest()[:12]
    stem = f"{report}_{day}_{sig}"
    path = ROOT / "cache" / (stem+".zip")
    meta = ROOT / "manifests" / (stem+".json")
    if not refresh and meta.exists() and path.exists():
        m = json.loads(meta.read_text())
        if m["params"] == args and m["endpoint"] == C["oasis"] and m["sha256"] == sha(path) and m["config_hash"] == CONFIG_HASH and validate(path,req) == m["schema"]:
            record({"stage":"retrieve","key":stem,"status":"CACHED"})
            return path
    for attempt in range(1,4):
        clock.sleep(max(0,last+C["seconds_between_requests"]-clock.monotonic()))
        last=clock.monotonic()
        try:
            with urlopen(Request(C["oasis"]+"?"+urlencode(args)),timeout=95) as response:
                payload = response.read()
            info = validate(io.BytesIO(payload),req)
            atomic(path,payload)
            save_json(meta,dict(status="VERIFIED_ARCHIVE",endpoint=C["oasis"],params=args,
                retrieved=utcnow(),config_hash=CONFIG_HASH,sha256=sha(path),size=len(payload),schema=info))
            record({"stage":"retrieve","key":stem,"attempt":attempt,"status":"OK"})
            print("verified",stem,len(payload),flush=True)
            return path
        except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as e:
            record({"stage":"retrieve","key":stem,"attempt":attempt,"params":args,"endpoint":C["oasis"],"error":str(e),"status":"FAILED"})
            if attempt == 3:raise
            pause=5*2**(attempt-1)+random.uniform(0.1,1)
            if isinstance(e, HTTPError) and (e.headers.get("Retry-After") or "").isdigit():
                pause=max(pause,int(e.headers["Retry-After"]))
            clock.sleep(pause)

def run():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["pilot","download","reference"])
    p.add_argument("--start",type=date.fromisoformat,default=date.fromisoformat(C["start"]))
    p.add_argument("--end-exclusive",type=date.fromisoformat,default=date.fromisoformat(C["end_exclusive"]))
    p.add_argument("--refresh",action="store_true")
    a=p.parse_args()
    failures=[]
    if a.mode=="reference":
        requests=[(date.fromisoformat(C["site_evidence_date"]),s,None) for s in REFERENCE]
    elif a.mode=="pilot":
        requests=[(date.fromisoformat(d),C["report"],None) for d in C["pilot_dates"]]
        requests += [(date.fromisoformat(d),C["report"],list(C["basis_hubs"].values())) for d in C["pilot_dates"]]
    else:
        requests=((day,C["report"],None) for day in date_range(a.start,a.end_exclusive))
    for day,report,nodes in requests:
        try: query(day,report,nodes,refresh=a.refresh)
        except Exception as e:
            print("FAILED", day,report,str(e),flush=True)
            failures.append([str(day),report,str(e)])
    if failures:raise SystemExit(1)

if __name__=="__main__":
    run()
