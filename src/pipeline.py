"""Production entry points for inventory, annual assembly, independent readback and reporting."""
import argparse
import importlib.metadata
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from common import C, CONFIG_HASH, DAY, ROOT, date, date_range, hours, save_json, sha, utcnow
from acquire import periods
from dataset import restore_month, save_inventory
from aggregate import calculate, profile
from workbooks import build_tables
from excel_stream import write_workbook
from validate_final import validate, seal

INVENTORY=ROOT/"staging/inventory"
SUPPORT=ROOT/"staging/support"
FILENAME="CAISO_Solar_Weighted_LMP_{}.xlsx"

def bounds(year):
    return date(year,1,1),min(date(year+1,1,1),date.fromisoformat(C["end_exclusive"]))

def restore(year=None):
    for start,_ in periods():
        if year and start.year!=year:continue
        print("Restoring verified input",start.strftime("%Y-%m"),flush=True)
        restore_month(start.strftime("%Y-%m"))

def build_inventory():
    first=date.fromisoformat(C["start"]);end=date.fromisoformat(C["end_exclusive"])
    table=save_inventory(date_range(first,end),INVENTORY)
    from recovery import run,load_recovery
    added=run(table,first,end,INVENTORY)
    load_recovery.cache_clear()
    if added:table=save_inventory(date_range(first,end),INVENTORY)
    save_json(INVENTORY/"inventory.json",dict(nodes=len(table),start=str(first),end_exclusive=str(end),config_sha256=CONFIG_HASH,
        sha256=sha(INVENTORY/"inventory.parquet"),dates=(end-first).days,generated=utcnow()))

def read_inventory():
    import json
    m=json.loads((INVENTORY/"inventory.json").read_text())
    if m["sha256"]!=sha(INVENTORY/"inventory.parquet") or m["config_sha256"]!=CONFIG_HASH:raise ValueError("inventory integrity")
    return pd.read_parquet(INVENTORY/"inventory.parquet")

def build(first,end,inv,stage,dest,report,test=False):
    from dataset import stage_month
    stage.mkdir(parents=True,exist_ok=True);dest.mkdir(parents=True,exist_ok=True);report.mkdir(parents=True,exist_ok=True)
    idx=pd.DatetimeIndex(list(hours(first,end)));year=first.year
    months=[]
    for lo,hi in periods():
        if lo>=end or hi<=first:continue
        stage_month(max(first,lo),min(hi,end),inv,stage)
        months.append(lo.strftime("%Y-%m"))
    from gaps import assess
    from study import audit_model,SPEC_HASH
    solar_audit=audit_model(idx,profile(year,idx),report)
    gap_audit=assess(inv,idx,stage,months,report)
    save_json(stage/"quality.json",dict(solar=solar_audit,gaps=gap_audit))
    calculate(inv,idx,stage,months,test)
    sheets=build_tables(inv,idx,stage,months,test)
    for sheet in sheets:
        if sheet.name in ["Node_Summary","Monthly_Summary","Matched_Period","Hub_Period_Summary","Daily_Source_QA","Data_Issues"]:
            import pyarrow as pa
            import pyarrow.parquet as pq
            writer=None
            try:
                for block in sheet.frames():
                    table=pa.Table.from_pandas(block,preserve_index=False)
                    if writer is None:
                        schema=pa.schema([pa.field(f.name,(pa.int64() if f.name=="calendar_month_days" else pa.string()) if pa.types.is_null(f.type) else f.type) for f in table.schema])
                        writer=pq.ParquetWriter(report/(sheet.name+".parquet"),schema,compression="zstd")
                    writer.write_table(table.cast(schema))
            finally:
                if writer is not None:writer.close()
    path=stage/("candidate-"+str(year)+".xlsx")
    write_workbook(path,sheets,int((~inv.reference_flag).sum()))
    print("Reopening the written candidate",path.stat().st_size,flush=True)
    check=validate(path,inv,idx,test);seal(path,check)
    daily=pd.read_parquet(report/"Daily_Source_QA.parquet")
    check.update(analysis_specification_sha256=SPEC_HASH,gap_audit=gap_audit,solar_audit=solar_audit,year=year,period_first=str(first),period_last=str(end-DAY),study_inventory_nodes=len(inv),source_days=len(daily),
        observed_first_day=daily.loc[daily.valid_node_hours>0,"delivery_date"].min(),observed_last_day=daily.loc[daily.valid_node_hours>0,"delivery_date"].max(),
        source_first_retrieved_utc=daily.retrieved_utc.min(),source_last_retrieved_utc=daily.retrieved_utc.max(),
        missing_market_intervals=[v for s in daily.marketwide_missing_utc for v in s.split("|") if v],
        code_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        github_run_id=os.environ.get("GITHUB_RUN_ID"),github_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        packages={p:importlib.metadata.version(p) for p in ("pandas","numpy","pyarrow","openpyxl","XlsxWriter")},
        profile_sha256=sha(ROOT/"profiles"/f"Solar_Profile_{year}.csv.gz"))
    output=dest/(("INTERNAL_TEST_" if test else "")+FILENAME.format(year))
    check["filename"]=output.name
    save_json(report/"readback.json",check)
    os.replace(path,output)
    print("Validated",output.name,check["bytes"],check["sha256"],flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage",choices=["restore","inventory","build","readback","integration","diagnostics","documentation"])
    p.add_argument("--year",type=int,choices=[2024,2025,2026])
    p.add_argument("--file",type=Path);a=p.parse_args()
    if a.stage=="restore":restore(a.year);return
    if a.stage=="inventory":build_inventory();return
    if a.stage=="documentation":
        from release_report import make_report
        make_report();return
    if a.stage=="diagnostics":
        from release_report import diagnostics
        diagnostics();return
    if a.stage=="integration":
        first=date(2024,1,1);end=first+2*DAY;stage=ROOT/"staging/integration-test"
        inv=save_inventory(date_range(first,end),stage)
        build(first,end,inv,stage,stage,stage/"support",True);return
    if not a.year:p.error("--year is required")
    first,end=bounds(a.year);inv=read_inventory();stage=ROOT/"staging"/str(a.year)
    if a.stage=="build":build(first,end,inv,stage,ROOT/"output",SUPPORT/str(a.year));return
    f=a.file or ROOT/"output"/FILENAME.format(a.year)
    r=validate(f,inv,pd.DatetimeIndex(list(hours(first,end))))
    if r["qa"]["Final written-file readback"]!="PASS":raise ValueError("unsealed workbook")
    r.update(sha256=sha(f),bytes=f.stat().st_size);save_json(SUPPORT/str(a.year)/"independent-readback.json",r)
    print(f.name,r["status"],r["sha256"])
if __name__=="__main__":main()
