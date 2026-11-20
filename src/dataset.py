"""Restore published inputs, construct the historical union, and stage month-sized price panels."""
import argparse
import io
import json
import os
import shutil
import tempfile
import zipfile
import numpy as np
import pandas as pd
from common import *
from acquire import periods,gh
from recovery import load_day,day_recovered
from reference import ZONES,BASE_FIELDS,segments,contour

BATCH=512
TAG="market-inputs-v1"
REPO="paulygon3/CAISO_Solar_LMP_24_25_26"

def get_asset(tag,name,folder):
    folder.mkdir(parents=True,exist_ok=True)
    gh("release","download",tag,"--repo",REPO,"-p",name,"-D",folder,"--clobber")
    return folder/name

def restore_month(month):
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        tmp=Path(tmp)
        for registry,label in [(month+"-manifest.json",month+"-analysis.zip"),(month+"-zones.json",month+"-zones.zip")]:
            m=json.loads(get_asset(TAG,registry,tmp).read_text())
            if m["config_sha256"]!=CONFIG_HASH:raise ValueError("incompatible config for "+month)
            info=next(a for a in m["assets"] if a["name"]==label) if "assets" in m else m["asset"]
            packed=get_asset(TAG,label,tmp)
            if packed.stat().st_size!=info["bytes"] or sha(packed)!=info["sha256"]:raise ValueError("bad input asset "+label)
            with zipfile.ZipFile(packed) as z:
                for n in z.namelist():
                    path=Path(n)
                    if len(path.parts)!=2 or path.parts[0] not in {"canonical","manifests","cache","quarantine"}:raise ValueError("invalid package member")
                    out=ROOT/path;out.parent.mkdir(exist_ok=True)
                    with z.open(n) as a,out.with_suffix(".restore").open("wb") as b:shutil.copyfileobj(a,b)
                    os.replace(out.with_suffix(".restore"),out)
            save_json(ROOT/"manifests"/registry,m)
            packed.unlink()

def inventory(days):
    history=None;totals=[]
    for day in days:
        path=ROOT/"canonical"/(str(day)+".parquet")
        m=json.loads((ROOT/"manifests"/("canonical_"+str(day)+".json")).read_text())
        if sha(path)!=m["sha256"]:raise ValueError("canonical hash "+str(day))
        a=load_day(day,columns=["node_id","node_name","utc_start","LMP"])
        if a.duplicated(["node_id","utc_start"]).any():raise ValueError("duplicate canonical key "+str(day))
        names=a[["node_id","node_name"]].drop_duplicates().set_index("node_id")
        good=a[a.LMP.notna()].sort_values("utc_start")
        g=good.groupby("node_id",sort=False).utc_start
        stat=g.agg(first="min",last="max",observations="count").reindex(names.index)
        stat["internal_gap_hours"]=(g.diff().dt.total_seconds()/3600-1).groupby(good.node_id).max().reindex(stat.index).fillna(0)
        stat["node_name"]=names.node_name
        if history is None:history=stat
        else:
            aligned=history.join(stat,lsuffix="_old",rsuffix="_new",how="outer")
            across=(aligned.first_new-aligned.last_old).dt.total_seconds()/3600-1
            history=pd.DataFrame(index=aligned.index)
            history["node_name"]=aligned.node_name_new.combine_first(aligned.node_name_old)
            history["first"]=aligned.first_old.combine_first(aligned.first_new)
            history["last"]=aligned.last_new.combine_first(aligned.last_old)
            history["observations"]=aligned.observations_old.fillna(0)+aligned.observations_new.fillna(0)
            history["internal_gap_hours"]=pd.concat([aligned.internal_gap_hours_old,aligned.internal_gap_hours_new,across],axis=1).max(axis=1)
        totals.append({"day":str(day),"distinct_priced_locations":int(good.node_id.nunique()),"valid_prices":int(len(good)),
                       "observed_market_hours":int(good.utc_start.nunique()),"new_ids":len(names.index) if len(totals)==0 else int((aligned.node_name_old.isna()&aligned.node_name_new.notna()).sum())})
    if history is None:raise ValueError("empty inventory")
    missing=set(C["basis_hubs"].values())-set(history.index)
    if missing:raise ValueError("missing specified hubs "+str(missing))
    order=sorted(set(history.index)-set(C["basis_hubs"].values()))+sorted(C["basis_hubs"].values())
    history=history.reindex(order).rename(columns={"first":"historical_first_utc","last":"historical_last_utc","observations":"historical_valid_prices","internal_gap_hours":"historical_longest_internal_gap_hours"})
    history=history.join(contour(),how="left",validate="one_to_one")
    history["reference_flag"]=history.index.isin(C["basis_hubs"].values())
    history["pdrp_name_flag"]=history.index.str.contains("PDRP",regex=False,case=False)
    return history,pd.DataFrame(totals)

def save_inventory(days,folder):
    folder.mkdir(parents=True,exist_ok=True)
    hist,counts=inventory(days)
    hist.to_parquet(folder/"inventory.parquet")
    counts.to_csv(folder/"daily_counts.csv",index=False)
    return hist

def compress_history(frame):
    frame=frame.sort_values(["node_id","effective_from_utc"]).reset_index(drop=True)
    keys=["node_id",*BASE_FIELDS]
    fingerprint=pd.util.hash_pandas_object(frame[keys],index=False)
    boundary=fingerprint.ne(fingerprint.shift()) | frame.effective_from_utc.ne(frame.effective_until_utc_exclusive.shift())
    groups=boundary.cumsum()
    keep=frame.loc[boundary].copy()
    keep["effective_until_utc_exclusive"]=frame.groupby(groups,sort=False).effective_until_utc_exclusive.last().to_numpy()
    return keep

def write_array(archive,key,values):
    buf=io.BytesIO();np.save(buf,values,allow_pickle=False);archive.writestr(key+".npy",buf.getbuffer())

def stage_month(first,last,inventory,stage):
    month=first.strftime("%Y-%m");out=stage/month;out.mkdir(parents=True,exist_ok=True)
    idx=pd.DatetimeIndex(list(hours(first,last)));ids=inventory.index
    fields={"LMP"}
    for d in date_range(first,last):
        m=json.loads((ROOT/"manifests"/("canonical_"+str(d)+".json")).read_text())
        fields.update(m["distinct_components"])
    panels={f:np.full((len(idx),len(ids)),np.nan,dtype=np.float64) for f in sorted(fields)}
    diagnostics=[]
    for d in date_range(first,last):
        a=load_day(d)
        hh=idx.get_indexer(a.utc_start);ii=ids.get_indexer(a.node_id)
        if min(hh.min(),ii.min())<0 or a.duplicated(["node_id","utc_start"]).any():raise ValueError(f"unexpected panel keys {d}")
        for field in fields.intersection(a.columns):panels[field][hh,ii]=a[field]
        m=json.loads((ROOT/"manifests"/("canonical_"+str(d)+".json")).read_text());diagnostics.append(m)
        if int(np.isfinite(a.LMP).sum())!=m["valid_lmp_hours"]+day_recovered(d):raise ValueError("LMP count discrepancy")
    resolution=np.full((len(idx),len(ids)),-1,dtype=np.int8)
    tables=[]
    for lo,hi,meta in segments(idx,ids):
        if not meta.index.equals(ids):raise ValueError("mapping changed universe/order")
        codes=meta.solar_zone.map({z:i for i,z in enumerate(ZONES)}).fillna(-1).to_numpy(np.int8)
        codes[meta.zone_mapping_status.eq("INFERRED")]+=3
        codes[meta.zone_mapping_status.eq("CONFLICTING")]=-2
        codes[meta.zone_mapping_status.eq("OUTSIDE_THREE_ZONE_SCOPE")]=-3
        resolution[lo:hi]=codes
        tables.append(meta.reset_index().assign(effective_from_utc=idx[lo],effective_until_utc_exclusive=idx[hi-1]+HOUR))
    timeline=compress_history(pd.concat(tables,ignore_index=True))
    timeline.to_parquet(out/"history.parquet",index=False,compression="zstd")
    for i in range(0,len(ids),BATCH):
        dest=out/f"batch-{i//BATCH:03d}.npz"
        with zipfile.ZipFile(dest.with_suffix(".part"),"w",compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
            for k,panel in panels.items():write_array(z,k,np.ascontiguousarray(panel[:,i:i+BATCH]))
            write_array(z,"mapping",np.ascontiguousarray(resolution[:,i:i+BATCH]))
        os.replace(dest.with_suffix(".part"),dest)
    save_json(out/"stage.json",dict(start=str(first),end=str(last),hours=len(idx),nodes=len(ids),fields=sorted(fields),observed=sum(m["valid_lmp_hours"]+day_recovered(date.fromisoformat(m["date"])) for m in diagnostics),
        exact_duplicates=sum(m["exact_duplicates"] for m in diagnostics),conflicting_keys=sum(m["conflicting_keys"] for m in diagnostics),
        component_exceptions=sum(m["component_exception_count"] or 0 for m in diagnostics),scope="Fetched source data"))
    print("Staged",month,len(idx),len(ids),flush=True)
