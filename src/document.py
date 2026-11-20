"""Document current completed batches. Does not build any workbook."""
import csv
import shutil
from common import *

def read(name):
    return json.loads((ROOT/"manifests"/name).read_text())
def run():
    paths=sorted((ROOT/"manifests").glob("PRC_LMP_*.json"))
    all_days={}
    for f in paths:
        m=json.loads(f.read_text())
        if m["params"].get("grp_type")=="ALL":
            p=ROOT/"cache"/(f.stem+".zip")
            if not p.exists() or sha(p)!=m["sha256"]:raise ValueError("invalid cache "+str(p))
            all_days[date.fromisoformat(m["params"]["startdatetime"][:8])]=m
    requested=list(date_range(date.fromisoformat(C["start"]),date.fromisoformat(C["end_exclusive"])))
    with (ROOT/"manifests/date-status.csv").open("w",newline="") as h:
        w=csv.writer(h);w.writerow(["pacific_trade_date","expected_utc_start","expected_utc_end_exclusive","all_node_acquisition","confirmed_source_gap"])
        for day in requested:
            w.writerow([day,midnight(day).isoformat(),midnight(day+DAY).isoformat(),"VERIFIED_ARCHIVE" if day in all_days else "NOT_RETRIEVED",""])
    tests=read("pilot-qa.json");sizes=read("cache-sizing.json");bench=read("benchmark.json")
    n=len(requested)
    disk=shutil.disk_usage(ROOT).free
    events=[json.loads(s) for s in (ROOT/"manifests/events.jsonl").read_text().splitlines()]
    price_times=[json.loads(f.read_text())["retrieved"] for f in paths]
    code_hash=hashlib.sha256()
    for f in sorted((ROOT/"src").glob("*.py")):
        code_hash.update(f.name.encode());code_hash.update(f.read_bytes())
    for f in sorted((ROOT/"tests").glob("*.py")):
        code_hash.update(f.name.encode());code_hash.update(f.read_bytes())
    report=dict(run_id="caiso-zonal-20261120T0229Z",updated_utc=utcnow(),configuration_sha256=CONFIG_HASH,
        code_sha256=code_hash.hexdigest(),status="INCOMPLETE_BLOCKED",requested_output_count=3,produced_final_workbooks=0,
        completed_trade_dates=len(all_days),requested_trade_dates=n,unretrieved_trade_dates=n-len(all_days),
        all_node_dates_sorted=[str(d) for d in sorted(all_days)],
        exhaustive_period_download=False,marketwide_missing_intervals="unknown outside six pilot days",
        mapping_coverage="Membership evaluated for pilot days only. Full market historical counts unknown.",
        calendar=read("solar.json"),profiles_and_matrix_readback=read("checkpoint-readback.json"),
        pilot_valid_lmp_records=sum(r["valid_total_prices"] for r in tests),
        pilot_separate_hub_checks=sum(r["independent_hub_pairs"] for r in tests),
        price_source_retrieval_utc=[min(price_times),max(price_times)],raw_daily_archives=len(all_days),
        stage_events={s:sum(r.get("status")==s for r in events) for s in ("OK","CACHED","FAILED")},
        full_hub_history=read("hubs.json") if (ROOT/"manifests/hubs.json").exists() else "PENDING",
        full_history_pilot_comparison=read("hub-history-pilot-comparison.json") if (ROOT/"manifests/hub-history-pilot-comparison.json").exists() else "PENDING",
        independent_node_comparison=read("independent-node-check.json") if (ROOT/"manifests/independent-node-check.json").exists() else "PENDING",
        capacity=dict(units="bytes",free_when_measured=disk,projected_raw_zip=n*sum(x["raw"] for x in sizes)/len(sizes),
            projected_lossless_parquet=n*sum(x["parquet_bytes"] for x in sizes)/len(sizes),projected_matrices=n*bench["bytes"],
            projected_annual_uncompressed_matrix_xml=366*bench["sheet_xml_bytes"],
            assumptions="Arithmetic average of 6 pilot archive sizes, 1 measured matrix day extrapolated across 1,053 days. Includes repeated day headers. No claim of exact annual file sizes. Additional historical nodes, mapping changes, summary sheets and scratch costs can change sizes.",
            suggested_new_workspace_free_gib=32),
        final_directory_problem="The designated /codex/browser/projectless/0006-whats-up/output does not exist on the selected cloud machine. Creation returned read-only filesystem inside the sandbox and permission denied through the approved command path.",
        outstanding=["Full all-node acquisition and observed historical universe", "historical classification and zone evidence beyond pilot",
        "annual/monthly/matched nodal production aggregation and full exporter", "three final Excel workbooks and exhaustive annual file readback"])
    save_json(ROOT/"manifests/run.json",report)
    print(report["status"],len(all_days),"of",n,"full-location days")
if __name__=="__main__":run()
