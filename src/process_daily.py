"""Canonicalize completed all-location batches and preserve source failures and conflicts."""
from common import *
from metrics import canonical
import argparse
import tempfile
import zipfile
import pandas as pd
import numpy as np

def process(mf):
    m=json.loads(mf.read_text())
    if m["params"].get("grp_type")!="ALL":return
    src=ROOT/"cache"/(mf.stem+".zip")
    if sha(src)!=m["sha256"]:raise ValueError("raw integrity mismatch "+mf.stem)
    day=date.fromisoformat(m["params"]["startdatetime"][:8])
    target=ROOT/"canonical"/(str(day)+".parquet")
    meta=ROOT/"manifests"/("canonical_"+str(day)+".json")
    signature=hashlib.sha256((sha(Path(__file__))+sha(ROOT/"src/metrics.py")+CONFIG_HASH).encode()).hexdigest()
    if target.exists() and meta.exists():
        old=json.loads(meta.read_text())
        if old["source_sha256"]==sha(src) and old["processing_version"]==signature and sha(target)==old["sha256"]:
            record(dict(stage="canonical",status="CACHED",date=str(day)));return
    exact=0
    pieces=[];quarantine=[];versions={}
    raw_keys=["NODE_ID","INTERVALSTARTTIME_GMT","MARKET_RUN_ID","LMP_TYPE"]
    with zipfile.ZipFile(src) as z:
        for n in z.namelist():
            rows=pd.read_csv(z.open(n),dtype=str,keep_default_na=False)
            cleaned,conflicts,ndup=canonical(rows)
            exact+=ndup
            if len(conflicts):quarantine.append(conflicts.assign(source_member=n))
            # Every raw source field, including unsupported new fields, is retained in the hashed ZIP.
            cleaned=cleaned[raw_keys+["NODE","INTERVALENDTIME_GMT","OPR_DT","OPR_HR","OPR_INTERVAL","XML_DATA_ITEM","GRP_TYPE","MW"]].copy()
            cleaned["source_member"]=n
            pieces.append(cleaned)
            versions[n]=dict(rows=len(rows),component_items=rows[["LMP_TYPE","XML_DATA_ITEM"]].drop_duplicates().values.tolist())
    raw=pd.concat(pieces,ignore_index=True)
    # Treat cross-member collisions conservatively until publication precedence can be verified.
    overlap=raw.duplicated(raw_keys,keep=False)
    if overlap.any():
        quarantine.append(raw[overlap]);raw=raw[~overlap]
    quarantined_keys=pd.DataFrame()
    if quarantine:
        q=pd.concat(quarantine,ignore_index=True)
        quarantined_keys=q[raw_keys].drop_duplicates()
        raw=raw.merge(quarantined_keys.assign(quarantined=1),how="left",on=raw_keys,validate="many_to_one")
        raw=raw[raw.quarantined.isna()].drop(columns="quarantined")
        dest=ROOT/"quarantine";dest.mkdir(exist_ok=True)
        q.to_parquet(dest/(str(day)+".parquet"),index=False)
    if set(raw.MARKET_RUN_ID)!={"DAM"} or set(raw.OPR_DT)!={str(day)}:raise ValueError("unexpected market/date")
    raw["utc_start"]=pd.to_datetime(raw.INTERVALSTARTTIME_GMT,utc=True)
    if not ((pd.to_datetime(raw.INTERVALENDTIME_GMT,utc=True)-raw.utc_start)==HOUR).all():raise ValueError("interval duration")
    expected=set(hours(day,day+DAY))
    if set(raw.utc_start)-expected:raise ValueError("out-of-period observations")
    if raw.NODE_ID.eq("").any():raise ValueError("empty node identifier")
    numeric=pd.to_numeric(raw.MW.replace("",np.nan),errors="raise")
    if np.isinf(numeric).any():raise ValueError("infinite price")
    raw["usd_per_mwh"]=numeric
    keys=["utc_start","NODE_ID"]
    idnames=raw[["NODE_ID","NODE"]].drop_duplicates()
    if idnames.NODE_ID.duplicated().any():raise ValueError("one ID with competing names within trade day")
    wide=raw.pivot(index=keys,columns="LMP_TYPE",values="usd_per_mwh").sort_index()
    if "LMP" not in wide:raise ValueError("no total LMP component")
    fields=sorted(set(wide.columns)-{"LMP"})
    # Publication of each component type is discovered from the particular trade date.
    known={"MCE","MCC","MCL","MGHG"}
    complete=wide.LMP.notna() & wide[fields].notna().all(axis=1)
    residual=wide.loc[complete,"LMP"]-wide.loc[complete,fields].sum(axis=1) if fields and set(fields)<=known else None
    # Five decimal places per component: half unit of last place for every term, including total.
    # Source strings can carry differing precisions. Treat this as a numerical review threshold only.
    tol=0.00005
    out=wide.reset_index().rename(columns={"NODE_ID":"node_id"})
    out=out.merge(idnames.rename(columns={"NODE_ID":"node_id","NODE":"node_name"}),on="node_id",validate="many_to_one",how="left")
    if len(out)!=len(wide):raise ValueError("identity join cardinality")
    order=["node_id","node_name","utc_start","LMP",*fields];out=out[order]
    target.parent.mkdir(exist_ok=True)
    tmp=target.with_suffix(".part")
    out.to_parquet(tmp,index=False,compression="zstd")
    written=pd.read_parquet(tmp)
    if not out.equals(written):raise ValueError("canonical parquet readback")
    os.replace(tmp,target)
    info=dict(date=str(day),processing_version=signature,source_sha256=m["sha256"],sha256=sha(target),bytes=target.stat().st_size,
        canonical_node_hours=len(out),valid_lmp_hours=int(out.LMP.count()),priced_nodes=int(out.loc[out.LMP.notna(),"node_id"].nunique()),
        distinct_components=fields,crc_validated_at_retrieval=True,source_members=versions,exact_duplicates=exact,conflicting_keys=len(quarantined_keys),
        expected_hours=len(expected),unobserved_marketwide_lmp_hours=[t.isoformat() for t in sorted(expected-set(out.loc[out.LMP.notna(),"utc_start"]))],
        missing_components_on_lmp_support={f:int((out.LMP.notna()&out[f].isna()).sum()) for f in fields},
        complete_component_rows=int(complete.sum()),review_tolerance_usd_per_mwh=tol,component_exception_count=int((residual.abs()>tol+1e-10).sum()) if residual is not None else None,
        max_abs_component_difference=float(residual.abs().max()) if residual is not None and len(residual) else None)
    save_json(meta,info)
    print(day,len(out),info["bytes"],flush=True)
if __name__=="__main__":
    for mf in sorted((ROOT/"manifests").glob("PRC_LMP*.json")):process(mf)
