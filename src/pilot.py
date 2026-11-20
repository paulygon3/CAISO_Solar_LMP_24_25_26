"""Read back all six pilot days, compare independent hub retrievals, size the export."""
import collections
import gc
import itertools
import json
import math
import shutil
import time as clock
import zipfile
import pandas as pd
import numpy as np
import xlsxwriter
import openpyxl
from common import *

def manifests(report):
    return [json.loads(f.read_text())|{"path":ROOT/"cache"/(f.stem+".zip")} for f in sorted((ROOT/"manifests").glob(report+"_*.json"))]

def raw(path):
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            yield pd.read_csv(z.open(n),dtype=str,keep_default_na=False)

def total_and_checks(path,day):
    totals=[];checks=[];codes=[]
    expected={x for x in hours(day,day+DAY)}
    for part in raw(path):
        exact=int(part.duplicated().sum())
        a=part.drop_duplicates()
        start=pd.to_datetime(a.INTERVALSTARTTIME_GMT,utc=True)
        ends=pd.to_datetime(a.INTERVALENDTIME_GMT,utc=True)
        if not (ends-start==pd.Timedelta(hours=1)).all() or set(start)-expected:raise ValueError("bad interval")
        if set(a.MARKET_RUN_ID)!={"DAM"} or set(a.OPR_DT)!={day.isoformat()}:raise ValueError("market/date mismatch")
        if (a.NODE_ID=="").any() or (a.NODE=="").any():raise ValueError("missing identity")
        columns=["NODE_ID","INTERVALSTARTTIME_GMT","LMP_TYPE","MARKET_RUN_ID"]
        # An unverified revision identifier cannot resolve conflicting prices.
        duplicated=a.duplicated(columns,keep=False)
        conflicts=a.loc[duplicated,columns].drop_duplicates()
        if len(conflicts):raise ValueError("source keys require revision review: "+str(len(conflicts)))
        price=pd.to_numeric(a.MW.replace("",np.nan),errors="raise")
        if np.isinf(price).any():raise ValueError("nonfinite price")
        codes+=list(a.LMP_TYPE.unique())
        checks.append(dict(component_rows=len(a),exact_duplicate_rows=exact,conflict_keys=len(conflicts),
                           types=sorted(a.LMP_TYPE.unique()),different_name_id_rows=int(a.NODE.ne(a.NODE_ID).sum())))
        is_total=a.LMP_TYPE.eq("LMP")
        if is_total.any():
            totals.append(pd.DataFrame({"id":a.NODE_ID[is_total],"time":start[is_total], "value":price[is_total]}))
    full=pd.concat(totals,ignore_index=True)
    if full.duplicated(["id","time"]).any():raise ValueError("overlap between files")
    if set(full.time)!=expected:raise ValueError("all-market hour missing")
    return full,checks,sorted(set(codes))

def mapping(day,ids):
    frames=[]
    for m in manifests("ATL_PNODE_MAP"):
        frames+=list(raw(m["path"]))
    members=pd.concat(frames).drop_duplicates()
    lo=pd.to_datetime(members.EFF_START_DT_GMT,utc=True)
    hi=pd.to_datetime(members.EFF_END_DT_GMT,utc=True)
    effective=members[(lo<=midnight(day))&(hi>=midnight(day+DAY)-timedelta(seconds=1))]
    ih={v:k for k,v in C["basis_hubs"].items()}
    ev=collections.defaultdict(set)
    for node,hub in effective[["PNODE_ID","APNODE_ID"]].itertuples(index=False,name=None):
        if hub in ih:ev[node].add(ih[hub])
    for h,z in ih.items():ev[h].add(z)
    results=[];zones={}
    for node in ids:
        opts=ev[node]
        state="DIRECT" if len(opts)==1 else ("CONFLICTING" if opts else "UNRESOLVED")
        z=next(iter(opts)) if len(opts)==1 else None
        if z:zones[node]=z
        results.append([node,z,state,"named reference hub" if node in ih else "dated CAISO trading-hub membership" if opts else "no matching dated membership in pilot"])
    return zones,pd.DataFrame(results,columns=["node_id","solar_zone","mapping_status","evidence"])

def benchmark(day,full):
    stamp=sorted(full.time.unique()); ids=sorted(full.id.unique())
    mat=full.pivot(index="time",columns="id",values="value").reindex(index=stamp,columns=ids)
    zones,table=mapping(day,ids)
    table.to_csv(ROOT/"manifests"/"pilot_node_mapping.csv.gz",index=False)
    profile=pd.read_csv(ROOT/"profiles"/f"Solar_Profile_{day.year}.csv.gz").set_index("utc_interval_start")
    profile.index=pd.to_datetime(profile.index,utc=True)
    clock0=clock.monotonic()
    dest=ROOT/"benchmark"/"one_day.xlsx"
    dest.parent.mkdir(exist_ok=True)
    with xlsxwriter.Workbook(dest, {"constant_memory":True,"strings_to_formulas":False,"strings_to_urls":False}) as book:
        for i in range(0,len(ids),1000):
            batch=ids[i:i+1000]; part=mat[batch]
            for weighted in [False,True]:
                sheet=book.add_worksheet(("Weighted_" if weighted else "Raw_")+str(i//1000+1))
                sheet.write_row(0,0,["UTC start"]+batch);sheet.freeze_panes(1,1)
                for row,(ts,prices) in enumerate(part.iterrows(),1):
                    sheet.write_string(row,0,ts.isoformat())
                    weights={z:profile.at[ts,z+"_weight_hours"] for z in C["sites"]} if weighted else {}
                    for col,(node,v) in enumerate(prices.items(),1):
                        if pd.notna(v) and (not weighted or node in zones):
                            sheet.write_number(row,col,v*weights[zones[node]] if weighted else v)
    with zipfile.ZipFile(dest) as z:
        if z.testzip():raise ValueError("benchmark ZIP failed CRC")
        sheet_xml=sum(i.file_size for i in z.infolist() if i.filename.startswith("xl/worksheets/sheet"))
    elapsed=clock.monotonic()-clock0
    book=openpyxl.load_workbook(dest,read_only=True)
    for i in range(0,len(ids),1000):
        batch=ids[i:i+1000]
        for weighted in (False,True):
            sh=book[("Weighted_" if weighted else "Raw_")+str(i//1000+1)]
            if tuple(next(sh.values))!=("UTC start",*batch):raise ValueError("header mismatch")
            for j,row in enumerate(itertools.islice(sh.values,1,None)):
                ts=stamp[j]
                for node,v in zip(batch,row[1:],strict=True):
                    orig=mat.at[ts,node]
                    want=None if pd.isna(orig) or (weighted and node not in zones) else orig*(profile.at[ts,zones[node]+"_weight_hours"] if weighted else 1)
                    if want is None:
                        if v is not None:raise ValueError("unexpected cell")
                    elif not math.isclose(want,v,rel_tol=1e-13,abs_tol=1e-12):raise ValueError("matrix mismatch")
    book.close()
    return dict(date=str(day),ids=len(ids),location_hours=len(full),mapping_counts=table.mapping_status.value_counts().to_dict(),
                mapped_by_zone=table.solar_zone.value_counts().to_dict(),batch=1000,worksheet_count=2*math.ceil(len(ids)/1000),
                bytes=dest.stat().st_size,sheet_xml_bytes=sheet_xml,write_and_crc_seconds=elapsed,readback="all pilot raw/weighted cells",
                workbook_sha256=sha(dest),free_disk_bytes=shutil.disk_usage(ROOT).free)

def run():
    entries=manifests("PRC_LMP")
    rows=[]
    for s in C["pilot_dates"]:
        day=date.fromisoformat(s)
        matches=[m for m in entries if m["params"]["startdatetime"].startswith(day.strftime("%Y%m%d")) and m["params"]["enddatetime"].startswith((day+DAY).strftime("%Y%m%d"))]
        allq,= [m for m in matches if m["params"].get("grp_type")=="ALL"]
        hubs,= [m for m in matches if m["params"].get("node")==",".join(C["basis_hubs"].values())]
        full,codes,types=total_and_checks(allq["path"],day)
        h,_,_=total_and_checks(hubs["path"],day)
        pairs=full[full.id.isin(C["basis_hubs"].values())].merge(h,on=["id","time"],how="outer",validate="one_to_one",indicator=True)
        if not (pairs._merge.eq("both").all() and pairs.value_x.equals(pairs.value_y)):raise ValueError("independent hub query discrepancy")
        counts=full.dropna().groupby("id").time.nunique()
        rows.append(dict(date=s,nodes=full.id.nunique(),hours=full.time.nunique(),valid_total_prices=int(full.value.count()),negative=int(full.value.lt(0).sum()),
                codes=types,partial_nodes=int((counts<len(list(hours(day,day+DAY)))).sum()),independent_hub_pairs=len(pairs),zip_bytes=allq["size"],archive_check=codes))
        if s=="2025-01-15":save_json(ROOT/"manifests/benchmark.json",benchmark(day,full))
        print(rows[-1],flush=True)
        gc.collect()
    save_json(ROOT/"manifests/pilot-qa.json",rows)
if __name__=="__main__":run()
