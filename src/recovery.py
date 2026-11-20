"""Check internally missing total-price positions with a second, named-node official retrieval."""
import json
from collections import deque
import shutil
import zipfile
from datetime import timedelta
from pathlib import Path
import numpy as np
import pandas as pd

from common import C, CONFIG_HASH, DAY, HOUR, ROOT, date, date_range, hours, midnight, save_json, sha
from oasis import query
from metrics import canonical

ANCHOR=C["basis_hubs"]["NP15"]
INVENTORY=ROOT/"staging/inventory"

def missing_requests(inventory,first,end):
    good=inventory.historical_first_utc.notna()&inventory.historical_last_utc.notna()
    inv=inventory[good]
    fst=inv.historical_first_utc.astype("datetime64[s, UTC]").astype("int64").to_numpy()
    lst=inv.historical_last_utc.astype("datetime64[s, UTC]").astype("int64").to_numpy()+3600
    for start in date_range(first,end):
        if start!=first and start.day not in (1,29):continue
        hi=min(end,start+timedelta(days=28),(start.replace(day=28)+4*DAY).replace(day=1))
        a=int(midnight(start).timestamp());b=int(midnight(hi).timestamp())
        expected=np.maximum(0,np.minimum(lst,b)-np.maximum(fst,a))//3600
        counts=pd.Series(0,index=inv.index,dtype="int64")
        for d in date_range(start,hi):
            raw=pd.read_parquet(ROOT/"canonical"/f"{d}.parquet",columns=["node_id","LMP"])
            counts=counts.add(raw.groupby("node_id").LMP.count(),fill_value=0).reindex(inv.index,fill_value=0)
        ids=sorted(inv.index[counts.to_numpy()<expected])
        if ids:yield start,hi,ids

def named_data(path,lo,hi,ids):
    frames=[]
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():frames.append(pd.read_csv(z.open(member),dtype=str,keep_default_na=False))
    raw=pd.concat(frames,ignore_index=True);clean,conflicts,_=canonical(raw)
    if len(conflicts):raise ValueError("named retrieval has unresolved duplicates "+path.name)
    if set(clean.NODE_ID)-set(ids) or set(clean.MARKET_RUN_ID)!={"DAM"}:raise ValueError("named retrieval scope")
    t=pd.to_datetime(clean.INTERVALSTARTTIME_GMT,utc=True);end_t=pd.to_datetime(clean.INTERVALENDTIME_GMT,utc=True)
    if not t.isin(list(hours(lo,hi))).all() or not (end_t-t==HOUR).all():raise ValueError("named retrieval time range")
    clean=clean.assign(utc_start=t,price=pd.to_numeric(clean.MW.replace("",np.nan),errors="raise"))
    anchor=clean[clean.NODE_ID.eq(ANCHOR)&clean.LMP_TYPE.eq("LMP")&clean.price.notna()]
    if len(anchor)!=len(list(hours(lo,hi))) or not anchor.utc_start.is_unique:raise ValueError("named retrieval fails the positive hub control")
    true=clean.pivot(index=["NODE_ID","utc_start"],columns="LMP_TYPE",values="price")
    true.index.names=["node_id","utc_start"]
    names=clean[["NODE_ID","NODE"]].drop_duplicates()
    if names.NODE_ID.duplicated().any():raise ValueError("ambiguous node names in named retrieval")
    true["node_name"]=true.index.get_level_values(0).map(names.set_index("NODE_ID").NODE)
    return true

def run(inventory,first,end,dest):
    dest.mkdir(parents=True,exist_ok=True);normalized=[];requests=[];cfg=CONFIG_HASH
    with zipfile.ZipFile(dest/"named_recovery_sources.zip","w",zipfile.ZIP_STORED,allowZip64=True) as sources:
        for lo,hi,nodes in missing_requests(inventory,first,end):
            print("Checking gaps against named price requests",lo,hi,len(nodes),flush=True)
            select=set(nodes)|{ANCHOR};base=[]
            for d in date_range(lo,hi):
                p=pd.read_parquet(ROOT/"canonical"/f"{d}.parquet",filters=[("node_id","in",list(select))])
                base.append(p)
            base=pd.concat(base,ignore_index=True).set_index(["node_id","utc_start"]).sort_index()
            pending=deque(nodes[j:j+48] for j in range(0,len(nodes),48))
            while pending:
                group=pending.popleft()
                ids=list(dict.fromkeys([ANCHOR,*group]))
                path=query(lo,C["report"],nodes=ids,end=hi);mf=ROOT/"manifests"/(path.stem+".json")
                raw=named_data(path,lo,hi,ids)
                known=base[base.index.get_level_values("node_id").isin(ids)&base.LMP.notna()].LMP
                named=raw.LMP.reindex(known.index)
                if named.isna().any():
                    if len(group)<=1:raise ValueError("named request omits a published positive-control price "+path.name)
                    cut=len(group)//2;pending.appendleft(group[cut:]);pending.appendleft(group[:cut])
                    continue
                old=base.reindex(raw.index)
                for col in set(old)&set(raw)-{"node_name"}:
                    pair=old[col].notna()&raw[col].notna()
                    if not np.allclose(old.loc[pair,col],raw.loc[pair,col],atol=1e-10,rtol=0):raise ValueError("published named and all-location values differ "+path.name+" "+col)
                add=raw[raw.LMP.notna()&old.LMP.isna()].reset_index()
                if len(add):
                    # Conflict quarantine has precedence over an ambiguous alternate record.
                    days=set(add.utc_start.dt.tz_convert(C["timezone"]).dt.date)
                    blocked=[]
                    for d in days:
                        qp=ROOT/"quarantine"/f"{d}.parquet"
                        if qp.exists():
                            q=pd.read_parquet(qp);q=q[q.LMP_TYPE.eq("LMP")]
                            blocked.extend(zip(q.NODE_ID,pd.to_datetime(q.INTERVALSTARTTIME_GMT,utc=True)))
                    add=add.loc[~pd.MultiIndex.from_frame(add[["node_id","utc_start"]]).isin(blocked)].copy()
                    add["source_sha256"]=sha(path);normalized.append(add)
                sources.write(path,"cache/"+path.name);sources.write(mf,"manifests/"+mf.name)
                requests.append(dict(start=str(lo),end_exclusive=str(hi),ids=ids,named_valid_prices=int(raw.LMP.notna().sum()),
                    all_location_positive_prices_rechecked=len(known),additional_published_prices=len(add),source_sha256=sha(path),source_manifest=mf.name))
    out=pd.concat(normalized,ignore_index=True) if normalized else pd.DataFrame(columns=["node_id","utc_start","node_name","LMP","source_sha256"])
    if out.duplicated(["node_id","utc_start"]).any():raise ValueError("duplicate recovered source key")
    out.to_parquet(dest/"recovered_prices.parquet",index=False,compression="zstd")
    save_json(dest/"price_recovery.json",dict(config_sha256=cfg,internal_missing_named_requests=len(requests),recovered_published_prices=len(out),requests=requests,
        recovery_sha256=sha(dest/"recovered_prices.parquet"),raw_named_sha256=sha(dest/"named_recovery_sources.zip")))
    return len(out)

def load_day(day,columns=None,folder=INVENTORY):
    path=ROOT/"canonical"/f"{day}.parquet"
    frame=pd.read_parquet(path,columns=columns)
    metadata=folder/"price_recovery.json"
    if not metadata.exists():return frame
    m=load_recovery(folder)
    if day not in m:return frame
    original=frame.set_index(["node_id","utc_start"]);additional=m[day].drop(columns="source_sha256").set_index(["node_id","utc_start"])
    for k in additional:
        if k not in original:original[k]=np.nan
    original=original.combine_first(additional)
    out=original.reset_index()
    return out[columns] if columns else out

from functools import lru_cache
@lru_cache(maxsize=2)
def load_recovery(folder):
    m=json.loads((folder/"price_recovery.json").read_text());path=folder/"recovered_prices.parquet"
    if m["config_sha256"]!=CONFIG_HASH or sha(path)!=m["recovery_sha256"]:raise ValueError("recovery provenance")
    if sha(folder/"named_recovery_sources.zip")!=m["raw_named_sha256"]:raise ValueError("named source archive digest")
    if not m["recovered_published_prices"]:return {}
    f=pd.read_parquet(path)
    return dict(tuple(f.groupby(f.utc_start.dt.tz_convert(C["timezone"]).dt.date,sort=False)))

def day_recovered(day):
    return len(load_recovery(INVENTORY).get(day,())) if (INVENTORY/"price_recovery.json").exists() else 0
