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
    results={}
    for path in sorted(SUPPORT.glob("retrieval/**/*.jsonl")):
        attempts=Counter();errors=Counter()
        with path.open() as f:
            for line in f:
                if not line.strip():continue
                r=json.loads(line);attempts[(r.get("stage",""),r.get("status",""))]+=1
                if r.get("status")=="FAILED":errors[r.get("key","unspecified")]+=1
        results[str(path.relative_to(SUPPORT))]={"stage_status_counts":{"/".join(k):v for k,v in attempts.items()},"failed_attempts_by_key":dict(errors)}
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
    gaps=sum(len(m["missing_market_intervals"]) for m in manifests)
    conflicts=sum(m["qa"]["Unresolved conflicting source keys"] for m in manifests)
    status="COMPLETE_WITH_DOCUMENTED_SOURCE_GAPS" if gaps or conflicts else "COMPLETE"
    report={"status":status,"generated_utc":utcnow(),"config_sha256":CONFIG_HASH,"years":manifests,"comparison":compare,"retrieval":diag,"unobserved_marketwide_intervals":gaps}
    save_json(SUPPORT/"completion.json",report)
    lines=["# CAISO day-ahead solar-weighted prices","",f"**{status}**. Pacific delivery from January 1, 2024 through November 18, 2026. Each workbook retains the same {manifests[0]['nodes']:,} historical price identifiers, including the three named reference hubs.","",
        "| Year | First and last observed delivery date | Hours | Nonmissing node-hour prices | Sheets | File size (MiB) |","|---|---|---:|---:|---:|---:|"]
    for m in manifests:lines.append(f"| {m['year']} | {m['observed_first_day']} to {m['observed_last_day']} | {m['hours']:,} | {m['valid_prices']:,} | {m['worksheets']} | {m['bytes']/2**20:,.1f} |")
    for field,title in [("mapping_counts","Effective mapping across each reporting window"),("classifications","Dated node classifications"),("heatmap_layers","Coverage and display layers")]:
        lines+=["","## "+title,"","| Category | 2024 | 2025 | 2026 YTD |","|---|---:|---:|---:|"]
        for key in sorted(set().union(*(m[field] for m in manifests))):lines.append("| "+key+" | "+" | ".join(f"{m[field].get(key,0):,}" for m in manifests)+" |")
    lines+=["","## Source coverage and readback","",f"There were {gaps:,} missing market-wide hourly intervals and {conflicts:,} quarantined conflicting source keys across the period. Exact intervals are recorded in the annual readback JSON and Daily_Source_QA.",
        "",f"Price retrievals span {min(m['source_first_retrieved_utc'] for m in manifests)} through {max(m['source_last_retrieved_utc'] for m in manifests)}. The retrieval summary records cache hits, successful attempts and transport errors from the archived acquisition logs.",
        "","Each archive passed CRC validation and reopened with openpyxl. The validator checked every matrix header, timestamp, nonmissing-cell total, dictionary address, summary key and display field. At the following sample sizes it compared individual raw prices and weighted numerators with dated canonical prices and mapping evidence.",""]
    for m in manifests:lines.append(f"- {m['year']} covered {m['sampled_raw_cells']:,} raw and {m['sampled_weighted_cells']:,} weighted positions at {len(m['sample_utc'])} UTC timestamps. SHA-256 `{m['sha256']}`.")
    lines+=["","## Balanced-node comparison and coverage","",f"{compare['balanced_nodes']:,} nonreference locations held the same assigned zone and met both 90% coverage thresholds in all three January 1–November 18 periods. The per-node estimates are in balanced_node_matched_period.parquet. Population_comparison.csv gives within-zone cross-node quantiles for full-year/YTD, matched-calendar and balanced populations.",""]
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
        for name in ["DATA_CLEANING_AND_LESSONS.md","config.json","analysis_specification.json","requirements.txt"]:z.write(ROOT/name,name)
