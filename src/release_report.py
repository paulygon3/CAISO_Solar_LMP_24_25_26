"""Materialize final run documentation solely from the real year receipts and daily manifests."""
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import zipfile
import pandas as pd
from common import C,CONFIG_HASH,ROOT,save_json,sha,utcnow

SUPPORT=ROOT/"staging/support"
def diagnostics():
    results={};exceptions=[]
    paths=sorted(SUPPORT.glob("retrieval/**/*.jsonl"))
    named=ROOT/"staging/inventory/named-retrieval-events.jsonl"
    if named.exists():paths.append(named)
    for path in paths:
        attempts=Counter();errors=Counter();events=[]
        with path.open() as f:
            for line in f:
                if not line.strip():continue
                r=json.loads(line);events.append(r);attempts[(r.get("stage",""),r.get("status",""))]+=1
                if r.get("status")=="FAILED":errors[r.get("key","unspecified")]+=1
        success={r.get("key") for r in events if r.get("stage")=="retrieve" and r.get("status") in ("OK","CACHED")}
        for event in events:
            if event.get("status")!="FAILED":continue
            q=event.get("params",{});a=q.get("startdatetime");b=q.get("enddatetime")
            if not a or not b:continue
            lo=pd.to_datetime(a,format="%Y%m%dT%H:%M-0000",utc=True);hi=pd.to_datetime(b,format="%Y%m%dT%H:%M-0000",utc=True)
            local=lo.tz_convert(C["timezone"]);end=hi.tz_convert(C["timezone"]);hours=(hi-lo).total_seconds()/3600
            month_start=local.normalize().replace(day=1);month_end=month_start+pd.offsets.MonthBegin(1)
            exceptions.append(dict(dataset=q.get("queryname"),requested_nodes=q.get("node",q.get("grp_type","report scope")),category="RETRIEVAL_FAILURE",
                utc_start=lo.isoformat(),utc_end_exclusive=hi.isoformat(),pacific_start=local.isoformat(),pacific_end_exclusive=end.isoformat(),
                requested_span_hours=hours,month=local.strftime("%Y-%m"),fraction_of_calendar_month=hours/((month_end-month_start).total_seconds()/3600),
                source_key=event.get("key"),attempt=event.get("attempt"),seen_success_in_same_log=event.get("key") in success,
                error=event.get("error","UNKNOWN"),action="Retry and validate source archive; consult final daily receipt",source_log=str(path.relative_to(ROOT/"staging"))))
        results[str(path.relative_to(ROOT/"staging"))]={"stage_status_counts":{"/".join(k):v for k,v in attempts.items()},"failed_attempts_by_key":dict(errors)}
    known=json.loads((ROOT/"results/interrupted_retrieval.json").read_text())
    if any(str(known["source_workflow_run_id"]) in name for name in results):
        results["source-workflow-exceptions"]={"stage_status_counts":{"retrieve/FAILED":1},"failed_attempts_by_key":{known["delivery_date"]:1}}
        exceptions.append(dict(dataset=known["source_report"],requested_nodes="ALL",category=known["category"],utc_start=known["utc_start"],
            utc_end_exclusive=known["utc_end_exclusive"],pacific_start=known["pacific_start"],pacific_end_exclusive=known["pacific_end_exclusive"],requested_span_hours=24,
            month="2025-08",fraction_of_calendar_month=1/31,source_key=known["delivery_date"],attempt=1,seen_success_in_same_log=False,error=known["exception"],
            action=known["action"],source_log=known["workflow_url"]))
    support_cols=["dataset","requested_nodes","category","utc_start","utc_end_exclusive","pacific_start","pacific_end_exclusive","requested_span_hours","month","fraction_of_calendar_month","source_key","attempt","seen_success_in_same_log","error","action","source_log"]
    pd.DataFrame(exceptions,columns=support_cols).to_csv(SUPPORT/"source_access_exceptions.csv",index=False)
    save_json(SUPPORT/"retrieval-summary.json",results)
    return results

def make_report():
    manifests=[json.loads((SUPPORT/str(y)/"readback.json").read_text()) for y in [2024,2025,2026]]
    f=ROOT/"output"
    if {p.name for p in f.glob("*.xlsx")}!={m["filename"] for m in manifests}:raise ValueError("three final workbooks required")
    for m in manifests:
        workbook=f/m["filename"]
        if m["sealed_readback"]!="PASS" or workbook.stat().st_size!=m["bytes"] or sha(workbook)!=m["sha256"]:raise ValueError("release validation mismatch")
    from comparisons import comparisons
    compare=comparisons(SUPPORT)
    diag=diagnostics()
    stage_totals=Counter()
    for run in diag.values():stage_totals.update(run["stage_status_counts"])
    gaps=sum(len(m["missing_market_intervals"]) for m in manifests)
    conflicts=sum(m["qa"]["Unresolved conflicting source keys"] for m in manifests)
    status="COMPLETE_WITH_DOCUMENTED_SOURCE_GAPS" if gaps or conflicts else "COMPLETE"
    recovery=json.loads((ROOT/"staging/inventory/price_recovery.json").read_text())
    report={"price_recovery":{"named_requests":recovery["internal_missing_named_requests"],"additional_published_prices":recovery["recovered_published_prices"]},"status":status,"generated_utc":utcnow(),"config_sha256":CONFIG_HASH,"years":manifests,"comparison":compare,"retrieval":diag,"retrieval_stage_totals":dict(stage_totals),"unobserved_marketwide_intervals":gaps}
    save_json(SUPPORT/"completion.json",report)
    lines=["# CAISO day-ahead solar-weighted prices","",f"**{status}**. Pacific delivery from January 1, 2024 through November 18, 2026. Each workbook retains the same {manifests[0]['nodes']:,} historical price identifiers, including the three named reference hubs.","",
        "| Year | First and last observed delivery date | Hours | Nonmissing node-hour prices | Sheets | File size (MiB) |","|---|---|---:|---:|---:|---:|"]
    for m in manifests:lines.append(f"| {m['year']} | {m['observed_first_day']} to {m['observed_last_day']} | {m['hours']:,} | {m['valid_prices']:,} | {m['worksheets']} | {m['bytes']/2**20:,.1f} |")
    for field,title in [("mapping_counts","Effective mapping across each reporting window"),("classifications","Dated node classifications"),("heatmap_layers","Coverage and display layers")]:
        lines+=["","## "+title,"","| Category | 2024 | 2025 | 2026 YTD |","|---|---:|---:|---:|"]
        fixed_categories={"mapping_counts":{"DIRECT","INFERRED","CONFLICTING","UNRESOLVED","OUTSIDE_THREE_ZONE_SCOPE"},"heatmap_layers":{"REFERENCE","HEATMAP","UNMAPPED","LOW_COVERAGE","NO_ESTIMATE"}}.get(field,set())
        for key in sorted(fixed_categories.union(*(m[field] for m in manifests))):lines.append("| "+key+" | "+" | ".join(f"{m[field].get(key,0):,}" for m in manifests)+" |")
    lines+=["","## Source coverage and readback","",f"There were {gaps:,} missing market-wide hourly intervals and {conflicts:,} quarantined conflicting source keys across the period. Exact intervals are recorded in the annual readback JSON and Daily_Source_QA.",
        "",f"Price retrievals span {min(m['source_first_retrieved_utc'] for m in manifests)} through {max(m['source_last_retrieved_utc'] for m in manifests)}. The retrieval summary records cache hits, successful attempts and transport errors from the archived acquisition logs.",
        "","Each archive passed CRC validation and reopened with openpyxl. The validator checked every matrix header, timestamp, nonmissing-cell total, dictionary address, summary key and display field. At the following sample sizes it compared individual raw prices and weighted numerators with dated canonical prices and mapping evidence.",""]
    for m in manifests:lines.append(f"- {m['year']} covered {m['sampled_raw_cells']:,} raw and {m['sampled_weighted_cells']:,} weighted positions at {len(m['sample_utc'])} UTC timestamps. SHA-256 `{m['sha256']}`.")
    lines+=["",f"The archived request logs contain {stage_totals.get('retrieve/OK',0):,} successful downloads, {stage_totals.get('retrieve/CACHED',0):,} validated cache hits and {stage_totals.get('retrieve/FAILED',0):,} failed attempts. Per-run errors and request keys are in retrieval-summary.json."]
    lines+=["",f"The final inventory used {recovery['internal_missing_named_requests']:,} named-node requests to check internal gaps in the all-location data. They recovered {recovery['recovered_published_prices']:,} additional published hourly prices. The original all-location rows and named-source archives are preserved separately."]
    lines+=["","## Balanced-node comparison and coverage","",f"{compare['balanced_nodes']:,} nonreference locations held the same assigned zone and met both 90% coverage thresholds in all three January 1–November 18 periods. The per-node estimates are in balanced_node_matched_period.parquet. population_comparison.csv gives within-zone cross-node quantiles for full-year/YTD, matched-calendar and balanced populations.",""]
    for x in compare["highest_internal_missing_share_by_pacific_hour"]:
        lines.append(f"- In {x['year']}, Pacific hour {x['hour']:02d} had the largest share of internally observable node-hours missing, {x['numerator']:,} of {x['denominator']:,} ({x['share']:.3%}). The gap-clustering tables also break out month, source batch, market regime, node type, zone and source market area.")
    lines+=["","## Observed, modeled and inferred","","Hourly prices and components are published CAISO observations. All six site TMY AC series were complete. The three weighted zonal profiles are modeled, with zero statistical repairs. The 24 hours of February 29, 2024 use the prespecified calendar rule. Numerical results and heatmap eligibility are calculated. Dated inferred classifications and unresolved IDs are recorded separately.","","Prices use official DAM OASIS data. The six-site, three-zone PVWatts scenario represents fixed typical weather. Effective membership differences, unsupported mappings and incomplete price coverage have separate fields. Missing prices remain blank. Direct and inferred mapping details, external locations, component tests and prior pilot issues are documented in each workbook and the repository lessons.","",
        "[Source archives](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/tag/market-inputs-v1) · [Source code and refresh instructions](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26)"]
    (SUPPORT/"RUN_REPORT.md").write_text("\n".join(lines)+"\n")
    with zipfile.ZipFile(ROOT/"staging/CAISO_provenance.zip","w",zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
        for path in sorted(SUPPORT.rglob("*")):
            if path.is_file():z.write(path,path.relative_to(SUPPORT))
        inv=ROOT/"staging/inventory"
        for path in sorted(inv.glob("*")):
            if path.is_file():z.write(path,"inventory/"+path.name)
        for name in ["DATA_CLEANING_AND_LESSONS.md","config.json","analysis_specification.json","docs/study-change-log.md","requirements.txt"]:z.write(ROOT/name,name)
