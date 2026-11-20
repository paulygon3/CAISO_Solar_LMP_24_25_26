"""Build a compact run-length gap register and descriptive missingness audit before calculating estimates."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd
from common import C, ROOT, PACIFIC, HOUR, date, save_json, sha
from aggregate import profile
from dataset import BATCH,compress_history
from reference import ZONES
from study import SPEC,SPEC_HASH

def runs(mask):
    edges=np.flatnonzero(np.diff(np.r_[False,mask,False]))
    return zip(edges[::2],edges[1::2])

def regime(day):
    return "EDAM_LAUNCH_ONWARD" if day>="2026-05-01" else "BEFORE_EDAM_LAUNCH"

def hour_grid(index):
    local=index.tz_convert(PACIFIC);n=len(index)
    return pd.DataFrame(dict(utc=index,pacific=[t.isoformat() for t in local],delivery_date=local.strftime("%Y-%m-%d"),month=local.strftime("%Y-%m"),
        local_hour=local.hour,market_regime=[regime(t) for t in local.strftime("%Y-%m-%d")],universe=np.zeros(n,int),observed=np.zeros(n,int),
        internal_eligible=np.zeros(n,int),internal_missing=np.zeros(n,int),missing_known_weight_hours=np.zeros(n,float),missing_unknown_weight_hours=np.zeros(n,int)))

def period_names(t,year):
    labels=["FULL_YEAR" if year<2026 else "YTD"]
    if (t.month,t.day)<=(11,18):
        labels.append("MATCHED_JAN01_NOV18")
        if year==2024 and (t.month,t.day)!=(2,29):labels.append("MATCHED_EXCL_FEB29")
    return "|".join(labels)

def source_quarantines(days):
    records={}
    for d in days:
        file=ROOT/"quarantine"/(str(d)+".parquet")
        if file.exists():
            f=pd.read_parquet(file)
            if len(f):
                for key,t,v in f[["NODE_ID","INTERVALSTARTTIME_GMT","LMP_TYPE"]].drop_duplicates().itertuples(index=False):
                    records.setdefault((key,pd.Timestamp(t)),set()).add(v)
    return records

def assess(inventory,index,stage,months,folder):
    folder.mkdir(parents=True,exist_ok=True)
    local=index.tz_convert(PACIFIC);days=pd.unique(local.date)
    dates=np.asarray(local.strftime("%Y-%m-%d"));month_keys=np.asarray(local.strftime("%Y-%m"))
    study_periods=[period_names(t,local[0].year) for t in local]
    starts=list(np.flatnonzero(np.r_[True,month_keys[1:]!=month_keys[:-1]]))
    calendar_cuts=np.flatnonzero(np.r_[True,np.array(study_periods[1:])!=np.array(study_periods[:-1])])
    hist=compress_history(pd.concat([pd.read_parquet(stage/m/"history.parquet") for m in months],ignore_index=True))
    histories={node:g for node,g in hist.groupby("node_id",sort=False)}
    grid=hour_grid(index);grid["universe"]=len(inventory)
    zone_weights=profile(local[0].year,index)[[z+"_weight_hours" for z in ZONES]].to_numpy()
    conflicts=source_quarantines(days)
    # Counts for every hour use the historical first/last observations, including years beyond this workbook.
    stamps=index.as_unit("s").asi8
    period_n={m:int(sum(month_keys==m)) for m in months}
    horizon=len(index);month_starts=sorted(set(starts+list(calendar_cuts)+[horizon]))
    year=local[0].year;gap_rows=[];metadata_rows=[];component_evidence=[];group_coverage=[]
    endstamp=index[-1]+HOUR
    def ts(i):return index[i] if i<horizon else endstamp
    def record(node,kind,lo,hi,a,b,known,unknown,m):
        start=ts(a);end=ts(b);month=month_keys[a]
        return dict(node_id=node,category=kind,gap_run_id=f"{node}/{kind}/{ts(lo).isoformat()}",run_start_utc=ts(lo),run_end_utc_exclusive=ts(hi),
            run_consecutive_hours=int(hi-lo),start_utc=start,end_utc_exclusive=end,pacific_start=start.tz_convert(PACIFIC).isoformat(),
            pacific_end_exclusive=end.tz_convert(PACIFIC).isoformat(),month=month,periods=study_periods[a],segment_hours=int(b-a),
            fraction_of_expected_month_hours=(b-a)/period_n[month],fraction_of_requested_year_hours=(b-a)/horizon,
            known_solar_weight_hours=known,unknown_solar_weight_hours=unknown,solar_zone=m.solar_zone or "UNKNOWN",node_classification=m.node_classification,
            market_classification=m.market_classification,snapshot_area=inventory.at[node,"snapshot_area"],mapping_method=m.zone_mapping_method,
            market_regime=regime(dates[a]),source_report="PRC_LMP DAM / dated ATLAS",source_condition="SOURCE_UNAVAILABLE_ON_VERIFIED_CANONICAL_SCAFFOLD",cause="UNKNOWN",action="Preserve absent price; exclude it from observed-price support",
            specification_sha256=SPEC_HASH)
    for start in range(0,len(inventory),BATCH):
        bi=start//BATCH;ids=inventory.index[start:start+BATCH];plist=[];codes=[];components={}
        for mi,month in enumerate(months):
            with np.load(stage/month/f"batch-{bi:03d}.npz") as data:
                price=data["LMP"];plist.append(price);codes.append(data["mapping"])
                # Document each published component's support by delivery date, market and dated zone/BAA evidence.
                for code in data.files:
                    if code in ("LMP","mapping"):continue
                    components[(mi,code)]=np.isfinite(data[code])
        prices=np.concatenate(plist);mapping=np.concatenate(codes);valid=np.isfinite(prices)
        grid["observed"]+=valid.sum(1)
        for mi,month in enumerate(months):
            lo=starts[mi];hi=starts[mi+1] if mi+1<len(starts) else horizon
            cuts={lo,hi}
            cuts.update((lo+np.flatnonzero(dates[lo+1:hi]!=dates[lo:hi-1])+1).tolist())
            slicehist=hist[(hist.node_id.isin(ids))&(hist.effective_from_utc<ts(hi))&(hist.effective_until_utc_exclusive>ts(lo))]
            cuts.update(int(i) for i in index.searchsorted(slicehist.effective_from_utc.unique()) if lo<i<hi)
            cuts=sorted(cuts)
            for a,b in zip(cuts,cuts[1:]):
                active=slicehist[(slicehist.effective_from_utc<=ts(a))&(slicehist.effective_until_utc_exclusive>ts(a))].set_index("node_id").reindex(ids)
                market=active.market_classification.fillna("UNKNOWN");zone=active.solar_zone.replace("","UNKNOWN").fillna("UNKNOWN")
                snapshot=inventory.loc[ids,"snapshot_area"].fillna("UNKNOWN")
                grouping=pd.DataFrame(dict(market=market,snapshot_area=snapshot,zone=zone,node_type=active.node_classification.fillna("UNKNOWN")))
                t=grouping.copy();t["observed"]=valid[a:b].sum(0);t["expected"]=b-a
                t=t.groupby(list(grouping),sort=False).sum().reset_index();t["delivery_date"]=dates[a];group_coverage.append(t)
                g=grouping[["market","snapshot_area"]].copy();g["lmp_valid_node_hours"]=valid[a:b].sum(0)
                for (j,code),cmask in components.items():
                    if j==mi:g[code+"_available_on_lmp_support"]=(cmask[a-lo:b-lo]&valid[a:b]).sum(0)
                g=g.groupby(["market","snapshot_area"],sort=False).sum().reset_index()
                g["delivery_date"]=dates[a];component_evidence.append(g)
        for j,node in enumerate(ids):
            h=histories[node];f=inventory.loc[node]
            missing=~valid[:,j];c=mapping[:,j];known=c>=0
            weight=np.where(known,zone_weights[np.arange(horizon),np.maximum(c,0)%3],0)
            exposure=np.r_[0.,np.cumsum(weight)];unknown=np.r_[0,(~known).cumsum()]
            first=f.historical_first_utc;last=f.historical_last_utc
            if pd.notna(first):
                inside=(stamps>=int(first.timestamp()))&(stamps<=int(last.timestamp()))
                grid.loc[:,"internal_eligible"]+=inside.astype(int);grid.loc[:,"internal_missing"]+=(inside&missing).astype(int)
            grid.loc[:,"missing_known_weight_hours"]+=weight*missing;grid.loc[:,"missing_unknown_weight_hours"]+=(~known&missing).astype(int)
            begin=index.searchsorted(h.effective_from_utc);end=index.searchsorted(h.effective_until_utc_exclusive)
            info=list(h.itertuples(index=False));extra=sorted(set(month_starts+begin.tolist()+end.tolist()))
            def segments_in(lo,hi):
                edges=[lo]+[v for v in extra if lo<v<hi]+[hi]
                for a,b in zip(edges,edges[1:]):
                    yield a,b,info[np.searchsorted(begin,a,side="right")-1]
            for lo,hi in runs(missing):
                kind="NO_VALID_PRICE_IN_STUDY" if pd.isna(first) else "PRE_OBSERVATION" if ts(hi)<=first else "POST_OBSERVATION" if ts(lo)>last else "INTERNAL_PRICE_GAP"
                for a,b,m in segments_in(lo,hi):
                    gap_rows.append(record(node,kind,lo,hi,a,b,float(exposure[b]-exposure[a]),int(unknown[b]-unknown[a]),m))
            for a,b,m in zip(begin,end,info):
                kinds=[]
                if m.zone_mapping_status in ("UNRESOLVED","CONFLICTING","OUTSIDE_THREE_ZONE_SCOPE"):
                    kinds.append({"UNRESOLVED":"ZONE_UNRESOLVED","CONFLICTING":"ZONE_CONFLICT","OUTSIDE_THREE_ZONE_SCOPE":"OUTSIDE_SCOPE"}[m.zone_mapping_status])
                if m.metadata_match_status=="UNMATCHED":kinds.append("METADATA_UNMATCHED")
                for kind in kinds:
                    for i,k,meta in segments_in(a,b):
                        item=record(node,kind,a,b,i,k,None,int(k-i),meta)
                        item.update(source_condition="DATED_REFERENCE_CLASSIFICATION",action="Retain historical ID and raw price; use only supported dated classifications",cause=meta.zone_mapping_method if kind!="METADATA_UNMATCHED" else "UNKNOWN")
                        metadata_rows.append(item)
        # Keep source-support detail bounded by aggregating repeated batch contributions.
        if bi%8==7 or start+BATCH>=len(inventory):
            detail=pd.concat(component_evidence,ignore_index=True);keys=["delivery_date","market","snapshot_area"]
            component_evidence=[detail.groupby(keys,as_index=False).sum(min_count=1)]
            detail=pd.concat(group_coverage,ignore_index=True);keys=["delivery_date","market","snapshot_area","zone","node_type"]
            group_coverage=[detail.groupby(keys,as_index=False).sum()]
        if bi%10==0:print("Assessed missingness in node batch",bi,flush=True)
    for name,frames in [("component_source_support",component_evidence),("gap_composition",group_coverage)]:
        f=pd.concat(frames,ignore_index=True)
        f["market_regime"]=f.delivery_date.map(regime);f["market_product"]="DAM_PRC_LMP"
        f.to_parquet(folder/(name+".parquet"),index=False,compression="zstd")
    columns=list(record(inventory.index[0],"",0,1,0,1,0.,0,next(histories[inventory.index[0]].itertuples(index=False))))
    for name,rows in [("price_gap_register",gap_rows),("mapping_gap_register",metadata_rows)]:
        f=pd.DataFrame(rows,columns=columns);f.to_parquet(folder/(name+".parquet"),index=False,compression="zstd")
    grid["marketwide_missing"]=grid.observed==0
    grid["widespread_internal"]=(grid.internal_missing>=SPEC["widespread_min_internal_nodes"]) & (grid.internal_missing>=SPEC["widespread_min_internal_share"]*grid.internal_eligible.clip(lower=1))
    grid["missing_node_hours"]=len(inventory)-grid.observed
    grid.to_parquet(folder/"hourly_gap_scope.parquet",index=False,compression="zstd")
    special=[]
    for col,kind in [("marketwide_missing","MARKETWIDE_GAP"),("widespread_internal","WIDESPREAD_INTERNAL_GAP")]:
        for lo,hi in runs(grid[col].to_numpy()):
            for a,b in zip(sorted({lo,hi,*[x for x in month_starts if lo<x<hi]})[:-1],sorted({lo,hi,*[x for x in month_starts if lo<x<hi]})[1:]):
                end=ts(b);start=ts(a);special.append(dict(dataset="DAM PRC_LMP",category=kind,start_utc=start,end_utc_exclusive=end,
                    pacific_start=start.tz_convert(PACIFIC).isoformat(),pacific_end_exclusive=end.tz_convert(PACIFIC).isoformat(),month=month_keys[a],periods=study_periods[a],consecutive_hours=int(hi-lo),segment_hours=int(b-a),
                    fraction_expected_month_hours=(b-a)/period_n[month_keys[a]],cause="UNKNOWN",action="Inspect simultaneous missing published observations and relevant source batch",missing_node_hours=int(grid.missing_node_hours.iloc[a:b].sum()),
                    known_solar_weight_hours=float(grid.missing_known_weight_hours.iloc[a:b].sum()),unknown_weight_node_hours=int(grid.missing_unknown_weight_hours.iloc[a:b].sum())))
    save_json(folder/"widespread_gaps.json",special_to_json(special))
    source_exceptions=[dict(node_id=k,timestamp=t.isoformat(),components=sorted(v),category="SOURCE_CONFLICT",action="Quarantine differing published rows") for (k,t),v in conflicts.items()]
    save_json(folder/"conflicting_keys.json",source_exceptions)
    log=pd.DataFrame(gap_rows,columns=columns)
    gap_sum=int(log.segment_hours.sum()) if len(log) else 0
    if gap_sum!=int(np.sum(grid.missing_node_hours)):raise ValueError("gap register does not reconcile to full scaffold")
    stats=dict(expected_node_hours=horizon*len(inventory),observed_node_hours=int(grid.observed.sum()),missing_node_hours=gap_sum,
        missing_by_class={k:int(v) for k,v in log.groupby("category").segment_hours.sum().items()},widespread_hours=int(grid.widespread_internal.sum()),
        marketwide_missing_hours=int(grid.marketwide_missing.sum()),price_gap_segments=len(log),mapping_gap_segments=len(metadata_rows),source_conflicts=len(conflicts),
        classification_version=SPEC_HASH)
    save_json(folder/"gap_summary.json",stats)
    return stats

def special_to_json(rows):
    return [{k:(v.isoformat() if hasattr(v,"isoformat") else v) for k,v in row.items()} for row in rows]
