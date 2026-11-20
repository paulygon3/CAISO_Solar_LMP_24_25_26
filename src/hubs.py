"""Compute full-window reference-hub results only after every named-hub request is accounted for."""
from common import *
from metrics import canonical,describe
from history_references import windows
import warnings
import zipfile
import pandas as pd
import numpy as np
from pathlib import Path

def summaries():
    scheduled={(day.strftime("%Y%m%d"),end.strftime("%Y%m%d")) for day,end in windows()}
    manifests=[]
    intervals=set()
    for f in sorted((ROOT/"manifests").glob("PRC_LMP_*.json")):
        m=json.loads(f.read_text())
        if m["params"].get("node") != ",".join(C["basis_hubs"].values()):continue
        if (m["params"]["startdatetime"][:8],m["params"]["enddatetime"][:8]) not in scheduled:
            continue
        manifests.append((f,m))
        lo=datetime.strptime(m["params"]["startdatetime"],"%Y%m%dT%H:%M-0000").replace(tzinfo=UTC)
        hi=datetime.strptime(m["params"]["enddatetime"],"%Y%m%dT%H:%M-0000").replace(tzinfo=UTC)
        while lo<hi:
            if lo in intervals:raise ValueError("overlapping requests")
            intervals.add(lo);lo+=HOUR
    expected=list(hours(date.fromisoformat(C["start"]),date.fromisoformat(C["end_exclusive"])))
    if set(expected)!=intervals:raise ValueError(f"{len(set(expected)-intervals)} remaining unrequested hub hours")
    tables=[]
    for f,m in manifests:
        path=ROOT/"cache"/(f.stem+".zip")
        if sha(path)!=m["sha256"]:raise ValueError("archive checksum failure")
        with zipfile.ZipFile(path) as z:
            for member in z.namelist():
                a=pd.read_csv(z.open(member),dtype=str,keep_default_na=False)
                if set(a.MARKET_RUN_ID)!={"DAM"} or not set(a.NODE_ID)<=set(C["basis_hubs"].values()):raise ValueError("unexpected market/node")
                tables.append(a)
    rows=pd.concat(tables,ignore_index=True)
    clean,quarantine,exact=canonical(rows)
    if len(quarantine):
        quarantine.to_csv(ROOT/"manifests/hub_quarantine.csv.gz",index=False)
    clean["time"]=pd.to_datetime(clean.INTERVALSTARTTIME_GMT,utc=True)
    end=pd.to_datetime(clean.INTERVALENDTIME_GMT,utc=True)
    if not (end-clean.time==pd.Timedelta(hours=1)).all() or set(clean.time)-intervals:raise ValueError("unexpected hub interval")
    clean["value"]=pd.to_numeric(clean.MW.replace("",np.nan),errors="raise")
    wide=clean.pivot(index="time",columns=["NODE_ID","LMP_TYPE"],values="value").reindex(expected)
    by_zone={z:wide[h,"LMP"] for z,h in C["basis_hubs"].items()}
    matches={}
    for day in C["pilot_dates"]:
        path=ROOT/"canonical"/(day+".parquet")
        if not path.is_file():raise ValueError("canonical pilot day required: "+day)
        pilot=pd.read_parquet(path,columns=["utc_start","node_id","LMP"])
        pilot=pilot[pilot.node_id.isin(C["basis_hubs"].values())]
        validation=pilot.pivot(index="utc_start",columns="node_id",values="LMP")
        for node in C["basis_hubs"].values():
            if not np.allclose(validation[node],wide[node,"LMP"].loc[validation.index],rtol=0,atol=0,equal_nan=True):
                raise ValueError("independent history/pilot discrepancy")
        matches[day]=int(validation.notna().sum().sum())
    save_json(ROOT/"manifests/hub-history-pilot-comparison.json",dict(exact_total_price_matches=matches,total=sum(matches.values())))
    expected_idx=wide.index.tz_convert(PACIFIC)
    out=[]; reconciled=[]
    for year in [2024,2025,2026]:
        glob=expected_idx.year==year
        local=expected_idx[glob]
        prof=pd.read_csv(ROOT/"profiles"/f"Solar_Profile_{year}.csv.gz")
        prof.index=pd.to_datetime(prof.utc_interval_start,utc=True)
        if not prof.index.equals(wide.index[glob]):raise ValueError("profile alignment")
        through=(local.month<11)|((local.month==11)&(local.day<=18))
        definitions={"FULL_YEAR" if year<2026 else "YTD":np.ones(len(local),bool),"MATCHED_JAN01_NOV18":through}
        if year==2024:definitions["MATCHED_EXCL_FEB29"]=through&~((local.month==2)&(local.day==29))
        definitions.update({f"{year}-{month:02}":local.month==month for month in sorted(set(local.month))})
        for label,mask in definitions.items():
            indices=prof.index[mask]
            support=clean[clean.time.isin(indices)]
            published=sorted(set(support.LMP_TYPE)-{"LMP"})
            for zone,node in C["basis_hubs"].items():
                price=by_zone[zone].reindex(indices)
                components={k:wide[node,k].reindex(indices) for k in published if (node,k) in wide}
                hub_comp={z:s.reindex(indices) for z,s in by_zone.items()}
                res=describe(price,prof[zone+"_weight_hours"].reindex(indices),hub_comp,components,"DIRECT",True)
                out.append(dict(node_id=node,node_name=node,solar_zone=zone,period=label,year=year,
                    period_start=str(local[mask][0].date()),period_end=str(local[mask][-1].date()),
                    published_component_codes="|".join(published),**res))
    frame=pd.DataFrame(out)
    for (year,node),s in frame.groupby(["year","node_id"]):
        months=s[s.period.str.match(r"^\d{4}-\d{2}$")]
        main=s[s.period.isin(["FULL_YEAR","YTD"])].iloc[0]
        cols=["valid_price_hours","expected_hours","weighted_numerator","matched_weight_hours","negative_weight_hours","full_period_weight_hours"]
        for col in cols:
            if not np.isclose(main[col],months[col].sum()):raise ValueError(f"{year} {node} {col} differs from monthly sum")
        reconciled.append({"year":int(year),"node":node,"checked":cols})
    dst=ROOT/"results"/"verified_hub_periods.csv";dst.parent.mkdir(exist_ok=True)
    atomic(dst,frame.to_csv(index=False).encode())
    read=pd.read_csv(dst)
    if len(read)!=len(frame) or read.duplicated(["node_id","period","year"]).any():raise ValueError("hub output readback failed")
    save_json(ROOT/"manifests/hubs.json",dict(market="DAM",queried_hours=len(intervals),valid_hub_lmps={z:int(s.notna().sum()) for z,s in by_zone.items()},
        source_archives=len(manifests),exact_duplicates=exact,quarantined_rows=len(quarantine),
        reconciliation=reconciled,period_rows=len(read),csv_sha256=sha(dst)))
    print(read[read.period.str.startswith("MATCHED_JAN")][["year","solar_zone","solar_weighted_lmp_usd_per_mwh","solar_coverage_pct"]].to_string(index=False))
if __name__=="__main__":summaries()
