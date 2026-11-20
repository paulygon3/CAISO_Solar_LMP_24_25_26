"""Vectorized node-period estimates. All arrays share the complete UTC hour by historical-ID scaffold."""
import json
import numpy as np
import pandas as pd
from common import *
from dataset import BATCH
from reference import ZONES,BASE_FIELDS

def ratio(numerator,denominator):
    n,d=np.broadcast_arrays(numerator,denominator)
    return np.divide(n,d,out=np.full(d.shape,np.nan),where=d>0)

def tier(percent):
    return np.select([percent>=C["thresholds"]["pass_pct"],percent>=C["thresholds"]["display_pct"],np.isfinite(percent)],["PASS","WARN","FAIL"],default="NO_ESTIMATE")

def weights(codes,solar):
    ok=codes>=0
    values=solar[np.arange(len(solar))[:,None],np.maximum(codes,0)%3]
    return np.where(ok,values,np.nan)

def profile(year,idx):
    f=pd.read_csv(ROOT/"profiles"/f"Solar_Profile_{year}.csv.gz")
    f.index=pd.to_datetime(f.utc_interval_start,utc=True)
    if not f.index.is_unique or not idx.isin(f.index).all():raise ValueError("solar calendar join")
    f=f.loc[idx]
    for z in ZONES:
        if f[z+"_weight_hours"].isna().any() or not np.allclose(f[z+"_output_mw"],100*f[z+"_weight"]):raise ValueError("solar units or profile gap")
    return f

def summarize_period(prices,codes,w,hub_values,components,applicable,times):
    n,k=prices.shape
    valid=np.isfinite(prices);count=valid.sum(0)
    resolved=codes>=0;all_resolved=resolved.all(0)
    weighted=valid&resolved
    safe_w=np.where(weighted,w,0.)
    safe_p=np.where(valid,prices,0.)
    num=(safe_w*safe_p).sum(0);den=safe_w.sum(0);full=np.nansum(w,axis=0)
    mean=ratio(safe_p.sum(0),count)
    sw=np.where(all_resolved,ratio(num,den),np.nan)
    coverage=np.where(all_resolved,100*ratio(den,full),np.nan)
    mapped=resolved.sum(0)
    # Changing zones are valid if an applicable zone is documented for every hour.
    zone_names=np.array([*ZONES,"VARIES",""],object)
    first_code=np.maximum(codes[0],0)%3
    has_change=((np.maximum(codes,0)%3!=first_code)&resolved).any(0)
    zones=zone_names[np.where(all_resolved,np.where(has_change,3,first_code),4)]
    conflicting=(codes==-2).any(0);outside=(codes==-3).all(0)
    mapping_status=np.select([conflicting,outside,~all_resolved,(codes>=3).any(0)],["CONFLICTING","OUTSIDE_THREE_ZONE_SCOPE","UNRESOLVED","INFERRED"],default="DIRECT")
    problem=np.select([conflicting,outside],["CONFLICTING_ZONE","OUTSIDE_THREE_ZONE_SCOPE"],default="UNRESOLVED_ZONE")
    eligible=np.isfinite(sw)&(coverage>=C["thresholds"]["display_pct"])
    neg=(safe_p<0)&valid;neg_w=np.sum(np.where(neg,safe_w,0),axis=0)
    time_str=np.array([t.isoformat() for t in times],dtype=object)
    minimum=np.min(np.where(valid,prices,np.inf),axis=0);maximum=np.max(np.where(valid,prices,-np.inf),axis=0)
    near=C["thresholds"]["capture_near_zero_usd_mwh"]
    out=dict(solar_zone=zones,zone_mapping_status=mapping_status,expected_hours=np.full(k,n),valid_price_hours=count,missing_price_hours=n-count,
        availability=np.select([count==0,count<n],["NO_OBSERVATIONS","PARTIAL"],default="FULL"),mapped_hours=mapped,
        first_observed_utc=np.where(count,time_str[np.argmax(valid,axis=0)],None),
        last_observed_utc=np.where(count,time_str[n-1-np.argmax(valid[::-1],axis=0)],None),
        valid_price_sum_usd_per_mwh_hours=safe_p.sum(0),time_weighted_lmp_usd_per_mwh=mean,min_lmp_usd_per_mwh=np.where(count,minimum,np.nan),
        max_lmp_usd_per_mwh=np.where(count,maximum,np.nan),negative_price_hours=neg.sum(0),zero_price_hours=((prices==0)&valid).sum(0),
        extreme_price_hours=((np.abs(prices)>=C["thresholds"]["extreme_absolute_usd_mwh"])&valid).sum(0),
        hour_coverage_pct=100*count/n,hour_coverage_status=tier(100*count/n),
        full_period_weight_hours=np.where(all_resolved,full,np.nan),matched_weight_hours=np.where(all_resolved,den,np.nan),
        weighted_numerator=np.where(all_resolved,num,np.nan),known_weight_valid_priced_hours=weighted.sum(0),known_full_weight_hours=full,known_price_matched_weight_hours=den,known_weighted_numerator=num,
        solar_weighted_lmp_usd_per_mwh=sw,solar_coverage_pct=coverage,solar_coverage_status=np.where(all_resolved,tier(coverage),problem),
        coverage_status=np.where(~all_resolved,problem,np.where(~np.isfinite(sw),"NO_ESTIMATE",np.where(eligible,"DISPLAY_ELIGIBLE","LOW_COVERAGE"))),
        heatmap_eligible=eligible,heatmap_lmp_usd_per_mwh=np.where(eligible,sw,np.nan),
        heatmap_layer=np.select([~all_resolved,~np.isfinite(sw),eligible],["UNMAPPED","NO_ESTIMATE","HEATMAP"],default="LOW_COVERAGE"),
        solar_capture_rate=np.where(mean>near,ratio(sw,mean),np.nan),
        capture_status=np.select([count==0,~np.isfinite(sw),np.abs(mean)<=near,mean<0],["NO_VALID_PRICE","NO_ESTIMATE","NEAR_ZERO_DENOMINATOR","NEGATIVE_DENOMINATOR"],default="OK"),
        negative_weight_hours=np.where(all_resolved,neg_w,np.nan),negative_price_solar_share=np.where(all_resolved,ratio(neg_w,den),np.nan))
    complete=valid.copy()
    total_components=np.zeros_like(prices)
    known_definition=np.ones(n,dtype=bool)
    for code,c in components.items():
        why=applicable[code]
        support=valid&np.isfinite(c)
        nvalid=support.sum(0);missing=count-nvalid
        cw=np.where(support&resolved,w,0.)
        cn=(cw*np.where(support,c,0.)).sum(0)
        complete &= (~why[:,None]) | np.isfinite(c)
        total_components+=np.where(why[:,None]&np.isfinite(c),c,0.)
        if code not in {"MCE","MCL","MCC","MGHG"}:known_definition &= ~why
        published=why.any()
        out.update({code+"_valid_hours":nvalid,code+"_missing_on_lmp_valid_hours":missing,
            code+"_published_expected_hours":np.full(k,int(why.sum())),code+"_matched_weight_hours":np.where(all_resolved,cw.sum(0),np.nan),
            code+"_weighted_numerator":np.where(all_resolved,cn,np.nan),
            code+"_weighted_usd_per_mwh":np.where(all_resolved&(missing==0)&published,ratio(cn,den),np.nan),
            code+"_status":np.select([np.full(k,not published),count==0,missing>0],["NOT_PUBLISHED","NO_OBSERVATIONS","MISSING_COMPONENT_INPUTS"],default="INPUTS_COMPLETE")})
    has_components=np.any(np.column_stack(list(applicable.values())),axis=1) if applicable else np.zeros(n,bool)
    complete &= has_components[:,None];testable=complete&known_definition[:,None]
    residual=np.abs(np.where(testable,prices-total_components,0.))
    exceptions=(residual>0.00005+1e-10).sum(0)
    out.update(common_component_valid_hours=complete.sum(0),common_component_weight_hours=np.where(all_resolved,np.where(complete&resolved,w,0.).sum(0),np.nan),
        component_reconciliation_tested_hours=testable.sum(0),component_reconciliation_exceptions=exceptions,
        component_reconciliation_max_abs_usd_per_mwh=np.where(testable.any(0),residual.max(0),np.nan),
        component_reconciliation_status=np.select([exceptions>0,~testable.any(0),testable.sum(0)<count],["RECONCILIATION_EXCEPTION","NOT_TESTED","PARTIAL_SUPPORT"],default="RECONCILED_ON_PUBLISHED_SUPPORT"))
    for col,z in enumerate(ZONES):
        h=hub_values[:,col,None]
        pair=valid&np.isfinite(h)&resolved
        weight=np.where(pair,w,0.);pairden=weight.sum(0)
        pnum=(weight*safe_p).sum(0);hnum=(weight*np.where(np.isfinite(h),h,0.)).sum(0)
        bnum=(weight*(safe_p-np.where(np.isfinite(h),h,0.))).sum(0)
        basis=np.where(all_resolved,ratio(bnum,pairden),np.nan)
        pc=np.where(all_resolved,100*ratio(pairden,full),np.nan)
        pair_ok=np.isfinite(basis)&(pc>=C["thresholds"]["display_pct"])
        pn=np.where(all_resolved,ratio(pnum,pairden),np.nan);ph=np.where(all_resolved,ratio(hnum,pairden),np.nan)
        if not np.allclose(pn-ph,basis,equal_nan=True,rtol=1e-9,atol=1e-8):raise ValueError("pairwise basis identity")
        if (pairden>den+1e-8).any():raise ValueError("pair weight exceeds node weight")
        metrics=dict(common_price_hours=(valid&np.isfinite(h)).sum(0),matched_hours=pair.sum(0),hour_coverage_pct=100*pair.sum(0)/n,
            solar_coverage_pct=pc,weight_hours=np.where(all_resolved,pairden,np.nan),basis_numerator=np.where(all_resolved,bnum,np.nan),
            node_numerator=np.where(all_resolved,pnum,np.nan),hub_numerator=np.where(all_resolved,hnum,np.nan),
            matched_node_usd_per_mwh=pn,matched_hub_usd_per_mwh=ph,basis_usd_per_mwh=basis,
            display_basis_usd_per_mwh=np.where(pair_ok,basis,np.nan),eligible=pair_ok,
            eligibility_reason=np.where(~all_resolved,problem,np.where(pair_ok,"ELIGIBLE",np.where(np.isfinite(basis),"LOW_COVERAGE","NO_MATCHED_WEIGHT"))))
        out.update({z+"_"+name:v for name,v in metrics.items()})
    if (den>full+1e-8).any() or np.any(np.isfinite(coverage)&((coverage<0)|(coverage>100+1e-8))):raise ValueError("solar coverage bounds")
    share=np.where(den>0,1/np.maximum(den,1e-300),0)
    if not np.allclose((safe_w*share).sum(0),np.where(den>0,1,0),atol=1e-9):raise ValueError("normalized hourly weight identity")
    if not np.allclose((safe_p*safe_w*share).sum(0)[np.isfinite(sw)],sw[np.isfinite(sw)],atol=1e-8):raise ValueError("node contribution identity")
    return pd.DataFrame(out)

def period_definitions(index,test=False):
    local=index.tz_convert(PACIFIC);year=local[0].year
    through=(local.month<11)|((local.month==11)&(local.day<=18))
    d={"RUN_WINDOW" if test else ("FULL_YEAR" if year<2026 else "YTD"):np.ones(len(index),bool),"MATCHED_JAN01_NOV18":through}
    if year==2024:d["MATCHED_EXCL_FEB29"]=through&~((local.month==2)&(local.day==29))
    d.update({f"{year}-{m:02}":local.month==m for m in np.unique(local.month)})
    return {k:v for k,v in d.items() if np.any(v)}

def period_metadata(history,idx,ids):
    a=history[(history.effective_from_utc<=idx[-1])&(history.effective_until_utc_exclusive>idx[0])]
    # If the matched-period sensitivity omits leap day, exclude rows supported only on that day.
    positions=idx.searchsorted(a.effective_from_utc)
    active=positions<len(idx)
    if len(idx):active &= idx.take(np.minimum(positions,len(idx)-1)).to_numpy()<a.effective_until_utc_exclusive.to_numpy()
    a=a.loc[active]
    out=pd.DataFrame(index=ids)
    for field in BASE_FIELDS[2:]:
        unique=a[["node_id",field]].drop_duplicates()
        first=unique.drop_duplicates("node_id").set_index("node_id")[field]
        first.loc[unique.loc[unique.node_id.duplicated(),"node_id"].unique()]="VARIES (see Node_Zone_History)"
        out[field]=first.reindex(ids).fillna("UNKNOWN")
    return out

def block_inputs(stage,months,batch,fields):
    panels={f:[] for f in [*fields,"mapping"]}
    for m in months:
        with np.load(stage/m/f"batch-{batch:03d}.npz") as z:
            for f in panels:panels[f].append(z[f] if f in z.files else np.full(z["LMP"].shape,np.nan))
    return {k:np.concatenate(v) for k,v in panels.items()}

def calculate(inventory,index,stage,months,test=False):
    hist=pd.concat([pd.read_parquet(stage/m/"history.parquet") for m in months],ignore_index=True)
    from dataset import compress_history
    hist=compress_history(hist);hist.to_parquet(stage/"history.parquet",index=False,compression="zstd")
    multi=period_definitions(index,test);solar=profile(index[0].year,index)
    values=solar[[z+"_weight_hours" for z in ZONES]].to_numpy()
    required=[]
    for d in pd.unique(index.tz_convert(PACIFIC).date):
        m=json.loads((ROOT/"manifests"/("canonical_"+str(d)+".json")).read_text())
        required.extend([m["distinct_components"]]*m["expected_hours"])
    fields=sorted(set().union(*required));app={f:np.array([f in x for x in required]) for f in fields}
    hubs=[]
    for z in ZONES:
        pos=inventory.index.get_loc(C["basis_hubs"][z]);bi,col=divmod(pos,BATCH)
        series=[]
        for month in months:
            with np.load(stage/month/f"batch-{bi:03d}.npz") as p:series.append(p["LMP"][:,col])
        hubs.append(np.concatenate(series))
    h=np.column_stack(hubs)
    hubframe=solar[["utc_interval_start","utc_interval_end","pacific_start_with_offset","delivery_date"]+[z+"_weight_hours" for z in ZONES]].copy()
    for j,z in enumerate(ZONES):hubframe[z+"_hub_lmp_usd_per_mwh"]=h[:,j]
    hubframe.to_parquet(stage/"hubs.parquet",index=False)
    sumdir=stage/"summary";sumdir.mkdir(exist_ok=True)
    for start in range(0,len(inventory),BATCH):
        bi=start//BATCH;ids=inventory.index[start:start+BATCH]
        panels=block_inputs(stage,months,bi,["LMP",*fields])
        p=panels["LMP"];c=panels["mapping"];w=weights(c,values)
        history=hist[hist.node_id.isin(ids)]
        summaries={}
        for label,mask in multi.items():
            t=index[mask];stat=summarize_period(p[mask],c[mask],w[mask],h[mask],
                {f:panels[f][mask] for f in fields},{f:app[f][mask] for f in fields},t)
            stat.index=ids
            meta=period_metadata(history,t,ids)
            local=t.tz_convert(PACIFIC)
            meta.insert(0,"period",label);meta.insert(1,"period_start",str(local[0].date()));meta.insert(2,"period_end",str(local[-1].date()))
            meta["requested_days"]=len(set(local.date));meta["calendar_month_days"]=local[0].days_in_month if label in months else None
            meta["partial_requested_month"]=bool(label in months and len(set(local.date))<local[0].days_in_month)
            joined=inventory.loc[ids,["node_name","reference_flag","pdrp_name_flag","snapshot_area","snapshot_type","price_map_snapshot_time"]].join(meta).join(stat)
            joined.loc[joined.reference_flag,"heatmap_layer"]="REFERENCE"
            joined.insert(1,"scenario","Fixed zonal TMY / equal-capacity two-site composite")
            joined.reset_index().to_parquet(sumdir/f"{label}_{bi:03d}.parquet",index=False,compression="zstd")
            summaries[label]=stat
        main=summaries[next(iter(multi))]
        for col in ["expected_hours","valid_price_hours","negative_price_hours","valid_price_sum_usd_per_mwh_hours","known_full_weight_hours","known_price_matched_weight_hours","known_weighted_numerator","component_reconciliation_exceptions"]:
            total=sum(summaries[m][col] for m in months)
            if not np.allclose(total,main[col],rtol=1e-9,atol=1e-7):raise ValueError(f"monthly reconciliation {bi} {col}")
        for z in ZONES:
            for metric in ["common_price_hours","matched_hours","weight_hours","basis_numerator","node_numerator","hub_numerator"]:
                col=z+"_"+metric
                ok=main[col].notna()
                total=sum(summaries[m][col] for m in months)
                if not np.allclose(total[ok],main.loc[ok,col],rtol=1e-9,atol=1e-7):raise ValueError(f"monthly hub reconciliation {bi} {col}")
        if bi%10==0:print("Aggregated node batch",bi,flush=True)
    return list(multi)
