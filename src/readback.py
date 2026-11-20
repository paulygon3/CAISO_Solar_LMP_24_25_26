"""Verify checkpoint outputs without rebuilding. Every profile cell, all one-day benchmark cells."""
from common import *
from solar import sites,tmy_value
import csv
import gzip
import itertools
import math
import zipfile
import openpyxl
import pandas as pd
import numpy as np

def solar_check():
    station_vals={z:[] for z in C["sites"]}
    for s in sites():
        m=json.loads((ROOT/"manifests"/(s["node"]+"_PVWatts.json")).read_text())
        p=ROOT/"cache"/(s["node"]+"_PVWatts.json")
        if sha(p)!=m["sha256"]:raise ValueError("solar input checksum")
        vals=np.array(json.loads(p.read_text())["outputs"]["ac"])/(1e6*C["ac_mw"])
        station_vals[s["zone"]].append((s["share"],vals))
    results={}
    for year in [2024,2025,2026]:
        end=min(date(year+1,1,1),date.fromisoformat(C["end_exclusive"]))
        count=synth=0
        records=[]
        with gzip.open(ROOT/"profiles"/f"Solar_Profile_{year}.csv.gz","rt") as f:
            for stamp,r in zip(hours(date(year,1,1),end),csv.DictReader(f),strict=True):
                if datetime.fromisoformat(r["utc_interval_start"])!=stamp or datetime.fromisoformat(r["utc_interval_end"])!=stamp+HOUR:raise ValueError("UTC coverage")
                if r["pacific_start_with_offset"]!=stamp.astimezone(PACIFIC).isoformat() or r["delivery_date"]!=str(stamp.astimezone(PACIFIC).date()):raise ValueError("delivery time label")
                monthday=stamp.astimezone(timezone(timedelta(hours=-8)))
                synth+=int((monthday.month,monthday.day)==(2,29))
                if int(r["leap_day_synthetic"])!=((monthday.month,monthday.day)==(2,29)) or int(r["repair_flag"])!=0:raise ValueError("unexpected profile flag")
                weights=[]
                for z,locations in station_vals.items():
                    expect=sum(frac*tmy_value(vals,stamp)[0] for frac,vals in locations)
                    for field,want in [("weight",expect),("weight_hours",expect),("output_mw",100*expect)]:
                        if not math.isclose(float(r[z+"_"+field]),want,rel_tol=1e-13,abs_tol=1e-12):raise ValueError("written profile mismatch")
                    weights.append(expect)
                records.append(weights);count+=1
        arr=np.array(records)
        if any(np.allclose(arr[:,a],arr[:,b]) for a,b in itertools.combinations(range(arr.shape[1]),2)):raise ValueError("profiles collapsed")
        results[year]=dict(checked_hours=count,synthetic_hours=synth,weight_cells_checked=count*3,repair_hours=0)
    return results

def matrix_check():
    d=date(2025,1,15);dest=ROOT/"benchmark/one_day.xlsx"
    m=json.loads((ROOT/"manifests/benchmark.json").read_text())
    if m["workbook_sha256"]!=sha(dest):raise ValueError("matrix file hash")
    with zipfile.ZipFile(dest) as z:
        if z.testzip() is not None or any("externalLinks/" in n for n in z.namelist()):raise ValueError("workbook archive or links")
    source=pd.read_parquet(ROOT/"canonical"/(str(d)+".parquet"))
    mat=source.pivot(index="utc_start",columns="node_id",values="LMP")
    mapping=pd.read_csv(ROOT/"manifests/pilot_node_mapping.csv.gz",keep_default_na=False).set_index("node_id")
    prof=pd.read_csv(ROOT/"profiles/Solar_Profile_2025.csv.gz").set_index("utc_interval_start")
    wb=openpyxl.load_workbook(dest,read_only=True)
    ids=sorted(mat.columns);batch=m["batch"];count=0
    for i in range(0,len(ids),batch):
        group=ids[i:i+batch]
        for weighted in (False,True):
            name=("Weighted_" if weighted else "Raw_")+str(i//batch+1)
            ws=wb[name]
            vals=iter(ws.values)
            if next(vals)!=("UTC start",*group):raise ValueError("raw/weighted header mismatch")
            for ts,row in zip(mat.index,vals,strict=True):
                if row[0]!=ts.isoformat():raise ValueError("workbook timestamp")
                p=mat.loc[ts,group].to_numpy(dtype=float)
                if weighted:
                    zone_weights={z:prof.at[row[0],z+"_weight_hours"] for z in C["sites"]}
                    w=mapping.loc[group,"solar_zone"].map(zone_weights).to_numpy(dtype=float)
                    p=p*w
                if not np.allclose(p,np.asarray(row[1:],dtype=float),equal_nan=True,rtol=1e-13,atol=1e-11):raise ValueError("matrix price or numerator")
                count+=len(group)
    wb.close()
    return dict(verified_cells=count,raw_weighted_pairs=count//2,date=str(d),sheets=m["worksheet_count"],status="PASS")
if __name__=="__main__":
    out=dict(solar=solar_check(),benchmark=matrix_check(),annual_workbook_readback="NOT_RUN")
    save_json(ROOT/"manifests/checkpoint-readback.json",out)
    print(json.dumps(out,indent=2))
