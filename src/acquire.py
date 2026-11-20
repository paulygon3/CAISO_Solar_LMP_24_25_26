"""Acquire one calendar month, publishing complete, checksummed source batches on request."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from common import C, CONFIG_HASH, ROOT, DAY, date, date_range, save_json, sha, utcnow
from oasis import query
from process_daily import process

def periods():
    start=date.fromisoformat(C["start"])
    limit=date.fromisoformat(C["end_exclusive"])
    while start<limit:
        end=min((start.replace(day=28)+4*DAY).replace(day=1),limit)
        yield start,end
        start=end

def gh(*args):
    return subprocess.check_output(["gh",*map(str,args)],text=True)

def acquire(start,end):
    raw=[];reference=[]
    # Only the producer contacts OASIS. Canonicalization may overlap the next download.
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending=None
        for day in date_range(start,end):
            path=query(day,C["report"])
            raw.append(path)
            if pending is not None: pending.result()
            pending=worker.submit(process,ROOT/"manifests"/(path.stem+".json"))
        if pending is not None:pending.result()
    for first in (start,start+28*DAY):
        if first>=end:continue
        for name in ["ATL_PNODE_MAP","ATL_PNODE","ATL_APNODE","ATL_HUB","ATL_TAC_AREA_MAP"]:
            reference.append(query(first,name,end=min(first+28*DAY,end)))
    return raw,reference

def package(dest,paths):
    tmp=dest.with_suffix(".partial")
    files=sorted(set(paths))
    with zipfile.ZipFile(tmp,"w",allowZip64=True) as z:
        for p in files:
            z.write(p,p.relative_to(ROOT),compress_type=zipfile.ZIP_STORED if p.suffix in (".zip",".parquet") else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(tmp) as z:
        if z.testzip():raise ValueError("CRC failure: "+str(tmp))
    tmp.replace(dest)
    return {"name":dest.name,"bytes":dest.stat().st_size,"sha256":sha(dest),"members":len(files)}

def release_inventory(tag):
    records=json.loads(gh("release","view",tag,"--json","assets"))
    return {a["name"]:a for a in records["assets"]}

def upload(tag,files):
    assets=release_inventory(tag)
    for p in files:
        if p.name in assets:
            # A recovered partial publication must match the actual uploaded bytes.
            with tempfile.TemporaryDirectory(dir=p.parent) as d:
                gh("release","download",tag,"-p",p.name,"-D",d)
                if sha(Path(d)/p.name)!=sha(p):raise RuntimeError("existing immutable asset differs: "+p.name)
        else:
            gh("release","upload",tag,p)
    observed=release_inventory(tag)
    if any(observed.get(p.name,{}).get("size")!=p.stat().st_size for p in files):
        raise RuntimeError("release assets missing or truncated")

def run():
    parser=argparse.ArgumentParser()
    parser.add_argument("--month",help="YYYY-MM; omit for the entire configured range")
    parser.add_argument("--release",help="Existing release tag for immutable source artifacts")
    parser.add_argument("--cleanup",action="store_true",help="Remove staged files only after publication is verified")
    a=parser.parse_args()
    if a.cleanup and not a.release:parser.error("--cleanup requires --release")
    collection=ROOT/"staging"/"packages";collection.mkdir(parents=True,exist_ok=True)
    for start,end in periods():
        month=start.strftime("%Y-%m")
        if a.month and month!=a.month:continue
        stamp=collection/(month+"-manifest.json")
        if a.release:
            inventory=release_inventory(a.release)
            if stamp.name in inventory:
                gh("release","download",a.release,"-p",stamp.name,"-D",collection,"--clobber")
                m=json.loads(stamp.read_text())
                if m["config_sha256"]!=CONFIG_HASH or m["start"]!=str(start) or m["end_exclusive"]!=str(end):
                    raise RuntimeError("incompatible published month "+month)
                if any(inventory.get(v["name"],{}).get("size")!=v["bytes"] for v in m["assets"]):
                    raise RuntimeError("incomplete published month "+month)
                print("Previously published",month,flush=True);continue
        raw,refs=acquire(start,end)
        mfiles=[ROOT/"manifests"/(p.stem+".json") for p in raw+refs]
        daily=[ROOT/"canonical"/(str(d)+".parquet") for d in date_range(start,end)]
        diagnostics=[ROOT/"manifests"/("canonical_"+str(d)+".json") for d in date_range(start,end)]
        quarantine=[ROOT/"quarantine"/p.name for p in daily if (ROOT/"quarantine"/p.name).exists()]
        prices=collection/(month+"-oasis.zip")
        data=collection/(month+"-analysis.zip")
        parts=[package(prices,raw),package(data,refs+mfiles+daily+diagnostics+quarantine)]
        save_json(stamp,dict(month=month,start=str(start),end_exclusive=str(end),config_sha256=CONFIG_HASH,
            packaged_utc=utcnow(),daily_archives=len(raw),assets=parts))
        if a.release:
            upload(a.release,[prices,data,stamp])
        if a.cleanup:
            for p in raw+refs+mfiles+daily+diagnostics+quarantine+[prices,data]:p.unlink(missing_ok=True)
        print("Verified month",month,parts,flush=True)
if __name__=="__main__":run()
