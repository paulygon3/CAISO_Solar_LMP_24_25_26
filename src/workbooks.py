"""Build all requested annual tables from saved canonical values and dated mapping segments."""
from pathlib import Path
import json
import math
import zipfile
import numpy as np
import pandas as pd
from xlsxwriter.utility import xl_col_to_name
from common import *
from reference import ZONES,BASE_FIELDS,MAP_SOURCE
from dataset import BATCH
from aggregate import profile,weights,period_definitions
from excel_stream import Sheet,write_workbook

TIMECOLS=["utc_interval_start","utc_interval_end","pacific_start_with_offset","delivery_date","source_opr_hr","source_opr_interval"]

def frame_sheet(name,df):
    return Sheet(name,list(df.columns),len(df),lambda:iter([df]))

def summary_blocks(stage,periods,batches):
    for period in periods:
        for bi in range(batches):
            yield pd.read_parquet(stage/"summary"/f"{period}_{bi:03d}.parquet")

def table_from_summary(name,stage,periods,batches,nodes):
    first=pd.read_parquet(stage/"summary"/f"{periods[0]}_000.parquet")
    return Sheet(name,list(first.columns),len(periods)*nodes,lambda:summary_blocks(stage,periods,batches))

def matrix_frames(stage,months,bi,ids,profile_df,weighted):
    at=0
    for month in months:
        with np.load(stage/month/f"batch-{bi:03d}.npz") as data:
            p=data["LMP"];c=data["mapping"];chunk=profile_df.iloc[at:at+len(p)]
            if weighted:
                p=p*weights(c,chunk[[z+"_weight_hours" for z in ZONES]].to_numpy())
            meta=chunk[TIMECOLS].reset_index(drop=True)
            yield pd.concat([meta,pd.DataFrame(p,columns=ids)],axis=1)
            at+=len(p)
    if at!=len(profile_df):raise ValueError("matrix hours")

def source_profiles():
    rows=[]
    for m in json.loads((ROOT/"inputs/pvwatts_sources.json").read_text()):
        s=m["site"];station=m["station"]
        rows.append(dict(solar_zone=s["zone"],reference_node_id=s["node"],latitude=s["lat"],longitude=s["lon"],
            location_weight=s["share"],site_evidence="Exact ATL_PNODE_MAP ID plus published CAISO map marker",site_selection=C["site_selection"],
            grid_latitude=station["lat"],grid_longitude=station["lon"],weather_station=station["location"],
            weather_grid_distance_m=station.get("distance"),resource=station["weather_data_source"],resource_file=station["solar_resource_file"],standard_utc_offset_hours=station["tz"],
            model=m["model_version"],model_source_sha256=m["sha256"],retrieved_utc=m["retrieved"],equivalent_ac_mw=C["ac_mw"],
            axis="Horizontal north–south",configuration=json.dumps(m["args"],sort_keys=True),time_mapping="NSRDB TMY; UTC to fixed PST month/day/hour; Feb 29 averages adjacent dates",**m["args"]))
    return pd.DataFrame(rows)

def raw_reference(prof,hub_frame):
    path=ROOT/"inputs/independent_hubs.parquet";m=json.loads((ROOT/"inputs/independent_hubs.json").read_text())
    if sha(path)!=m["sha256"]:raise ValueError("independent hub checksum")
    a=pd.read_parquet(path);a=a[a.utc_start.isin(prof.index)]
    labels=a[["utc_start","OPR_DT","OPR_HR","OPR_INTERVAL"]].drop_duplicates().set_index("utc_start")
    if not labels.index.is_unique or not labels.index.sort_values().equals(prof.index):raise ValueError("hub delivery labels")
    labels=labels.loc[prof.index]
    if (labels.OPR_DT.to_numpy()!=prof.delivery_date.to_numpy()).any():raise ValueError("source delivery date anchor")
    prof=prof.copy();prof["source_opr_hr"]=pd.to_numeric(labels.OPR_HR).to_numpy();prof["source_opr_interval"]=pd.to_numeric(labels.OPR_INTERVAL).to_numpy()
    matches=0
    for z,node in C["basis_hubs"].items():
        orig=pd.to_numeric(a[a.NODE_ID==node].set_index("utc_start").LMP).reindex(prof.index)
        actual=hub_frame[z+"_hub_lmp_usd_per_mwh"].to_numpy()
        if not np.allclose(orig,actual,rtol=0,atol=1e-10,equal_nan=True):raise ValueError(f"all-location and separate hub retrieval disagree: {z}")
        matches+=int(orig.notna().sum())
    return prof,matches

def build_tables(inv,index,stage,months,test=False):
    periods=list(period_definitions(index,test));primary=periods[0]
    matched=[p for p in periods if p.startswith("MATCHED")]
    n=len(inv);nb=math.ceil(n/BATCH);year=index[0].year
    hub=pd.read_parquet(stage/"hubs.parquet");prof,matches=raw_reference(profile(year,index),hub)
    files=[json.loads((ROOT/"manifests"/("canonical_"+str(d)+".json")).read_text()) for d in pd.unique(index.tz_convert(PACIFIC).date)]
    source_log=[]
    for d in files:
        relevant=[p for p in (ROOT/"manifests").glob("PRC_LMP_"+d["date"]+"*.json") if json.loads(p.read_text())["params"].get("grp_type")=="ALL"]
        if len(relevant)!=1:raise ValueError("missing daily source provenance")
        m=json.loads(relevant[0].read_text())
        source_log.append(dict(delivery_date=d["date"],retrieved_utc=m["retrieved"],source_sha256=m["sha256"],canonical_sha256=d["sha256"],
             source_report="PRC_LMP",version=m["params"]["version"],valid_node_hours=d["valid_lmp_hours"],priced_nodes=d["priced_nodes"],
             expected_hours=d["expected_hours"],marketwide_missing_utc="|".join(d["unobserved_marketwide_lmp_hours"]),components="|".join(d["distinct_components"]),
             exact_duplicate_rows=d["exact_duplicates"],conflicting_keys=d["conflicting_keys"],component_exception_count=d["component_exception_count"],
             max_component_residual_usd_per_mwh=d["max_abs_component_difference"]))
    daily=pd.DataFrame(source_log)
    summary=pd.concat(summary_blocks(stage,[primary],nb),ignore_index=True)
    if not summary.node_id.equals(pd.Series(inv.index,name="node_id").reset_index(drop=True)):raise ValueError("summary population/order")
    if int(summary.valid_price_hours.sum())!=daily.valid_node_hours.sum():raise ValueError("summary/raw total count mismatch")
    history=pd.read_parquet(stage/"history.parquet")
    dictcols=["node_id","node_name","node_classification","node_subtype","resource_type","description","tac_area","as_region","market_classification","metadata_match_status","solar_zone","zone_mapping_status","zone_mapping_method","mapping_detail","published_hubs","snapshot_area","snapshot_type","price_map_snapshot_time","reference_flag","pdrp_name_flag","availability","first_observed_utc","last_observed_utc"]
    dictionary=summary[dictcols].copy().merge(inv[[c for c in inv if c.startswith("historical_")]],left_on="node_id",right_index=True,validate="one_to_one",sort=False)
    dictionary["zone_mapping_source"]=MAP_SOURCE
    dictionary["raw_sheet"]=[f"Hourly_LMP_{i//BATCH+1:03d}" for i in range(n)]
    dictionary["weighted_sheet"]=[f"Hourly_Weighted_{i//BATCH+1:03d}" for i in range(n)]
    dictionary["matrix_column"]=[xl_col_to_name(len(TIMECOLS)+i%BATCH) for i in range(n)]
    dictionary["time_varying_evidence"]="See Node_Zone_History and published monthly source ZIPs"
    history=history.merge(inv[["node_name"]],left_on="node_id",right_index=True,how="left",validate="many_to_one")
    history=history[["node_id","node_name","effective_from_utc","effective_until_utc_exclusive",*BASE_FIELDS]]
    history["zone_mapping_source"]=MAP_SOURCE
    missing=sum(len(d["unobserved_marketwide_lmp_hours"]) for d in files)
    qa=[
        ("Expected delivery hours",len(index),"UTC scaffold from Pacific delivery bounds"),
        ("All-location source archive days",len(daily),"Validated CRC, schema, source and canonical hashes"),
        ("Marketwide missing hours",missing,"Exact UTC starts, when present, on Daily_Source_QA"),
        ("Historical universe",n,"Union over the configured three-year price history; pilot scope when explicitly labeled"),
        ("Observed priced nodes",int((summary.valid_price_hours>0).sum()),"Observed in this workbook's reporting window"),
        ("Valid hourly prices",int(summary.valid_price_hours.sum()),"Reconciled to every published canonical day"),
        ("Exact duplicate source rows",int(daily.exact_duplicate_rows.sum()),"Components are distinct source records"),
        ("Unresolved conflicting source keys",int(daily.conflicting_keys.sum()),"Quarantined; no arbitrary price precedence"),
        ("Component reconciliation exceptions",int(daily.component_exception_count.sum()),"Review threshold 0.00005 USD/MWh; retain official total LMP"),
        ("Nonmissing hourly numerators",int(summary.known_weight_valid_priced_hours.sum()),"Includes valid zero production; source and mapping must be available"),
        ("Price report and version","PRC_LMP v12 / DAM","Individual source and canonical checksums in Daily_Source_QA"),
        ("Acquisition retries","See retrieval event logs","Raw request attempts, recovery and cache hits accompany the monthly artifacts or Actions acquisition log"),
        ("Independent retrieval checks",matches,"Every available hub total across the workbook compared with a separate named-hub retrieval"),
        ("Monthly additive reconciliation","PASS","Hours, weighted numerator, negative counts, matched/full support and reconciliation counts"),
        ("Hub basis and normalized contribution checks","PASS","Every node-period checked"),
        ("Source schema and join cardinality","PASS","Daily keys unique; complete node-hour scaffold and unique identifier joins"),
        ("Final written-file readback","PENDING","Replaced with actual readback findings after validating the written candidate"),
    ]
    for key in ["zone_mapping_status","node_classification","heatmap_layer","market_classification"]:
        for k,v in summary[key].value_counts(dropna=False).items():qa.append((f"{key} / {k}",int(v),"Full requested window"))
    qa_df=pd.DataFrame(qa,columns=["check","result","detail"])
    completeness="COMPLETE_WITH_DOCUMENTED_SOURCE_GAPS" if missing or daily.conflicting_keys.sum() else "COMPLETE"
    if test:completeness="INTERNAL_INTEGRATION_TEST"
    issues=[
        ("MAPPING","Unassigned locations",int(summary.solar_zone.eq("").sum()),"Node_Summary and Node_Zone_History","Preserve raw LMPs; blank the primary weighted estimate for incomplete mapping","Mapping uncertainty","OPEN"),
        ("AVAILABILITY","Partial or absent observations",int((summary.valid_price_hours<len(index)).sum()),"Expected vs published hours; Daily_Source_QA","Retain all historical IDs and compute full-period coverage","First/last observations alone cannot establish retirement or replacement","DISCLOSED"),
        ("COVERAGE","Low solar coverage",int((summary.heatmap_layer=="LOW_COVERAGE").sum()),"Available-price and full-profile weight-hours","Retain estimate with a blank display value","90% display threshold has no statistical error bound","DISCLOSED"),
        ("COMPONENTS","Residuals exceeding project review threshold",int(daily.component_exception_count.sum()),"Daily_Source_QA","Use published LMP and published components on complete support","A matching sum cannot independently verify component economics","DISCLOSED"),
        ("SOURCE_CONFLICTS","Unresolved conflicting canonical keys",int(daily.conflicting_keys.sum()),"Canonical manifests and quarantine files","Quarantine ambiguous observations","Affected values remain blank","DISCLOSED"),
    ]
    for _,r in daily.assign(change=daily.priced_nodes.pct_change()).dropna(subset=["change"]).query("abs(change)>=0.20").iterrows():
        issues.append(("INVENTORY_"+r.delivery_date,"Daily priced location count changed by at least 20%",int(r.priced_nodes),f"Daily_Source_QA; change {r.change:.2%}","Retain all historical identifiers","Changes can reflect source participation or availability; cause unverified","OPEN"))
    issues_df=pd.DataFrame(issues,columns=["issue_id","confirmed_finding","affected_count","detection_evidence","treatment","interpretation_impact","resolution_status"])
    qa_df.loc[len(qa_df)]=["Processing and source completion",completeness,"Mapping and display counts are shown separately"]
    text={
        "Scope":f"{year} / {primary}, {prof.delivery_date.iat[0]} through {prof.delivery_date.iat[-1]}, Pacific inclusive. {len(index):,} expected hours; {n:,} historical locations.",
        "Completion":completeness,"Market":"CAISO OASIS PRC_LMP v12, DAM total LMP in USD/MWh, UTC interval starts.",
        "Extraction UTC":f"{daily.retrieved_utc.min()} through {daily.retrieved_utc.max()}. Daily source checksums in Daily_Source_QA.",
        "Distribution":"A workbook contains values and no external data connections. Original reports and machine-readable manifests are stored in the repository releases.",
        "Model":"Standardized two-location equal-capacity composite per zone. Utility-scale PVWatts V8 and NSRDB TMY; 130 MW DC / 100 MW AC; single-axis backtracking. No storage or curtailment.",
        "Calendar":"Each UTC price hour maps to local standard-time month/day/hour; nighttime zero is valid; February 29 averages corresponding February 28 and March 1. Pacific presentation explicitly includes repeated-hour offset and source OPR_HR.",
        "Zone mapping":"Use effective-dated official hub membership. Infer from the two unexpanded AS path subregions inside AS_CAISO, or complete, same-zone nonzero LDF support. Disagreements are flagged. Effective ranges are clipped to retrieved query windows.",
        "Geographic scope":"Other published trading-hub membership is outside the three-hub assignment scope. Unknown locations remain in the inventory. The exact-ID control-area and type from the separately dated price-map snapshot are descriptive as-of fields.",
        "Weighted LMP":"SUM(valid LMP × applicable zonal weight-hours) / SUM(matched weight-hours). Unmapped hours invalidate the full period assigned-zone estimate. A genuine price at zero production contributes zero.",
        "Coverage":"Solar coverage uses all expected assigned-zone weight-hours; hour coverage uses every expected hour. PASS ≥98%, WARN ≥90%, FAIL <90%. Retained estimates and eligible heatmap values are separate. Reference rows are excluded from the nodal color scale.",
        "Components":"MCE, MCC and MCL are published energy, congestion and losses. MGHG is the published greenhouse gas component where available. USD/MWh with published signs. Primary component output requires complete LMP-valid support; forward or residual fills are excluded.",
        "Hub basis":"Both prices use the node's zone on common valid timestamps; subtract the matched hub price from matched node price. Standalone hub results use each hub's own-zone production.",
        "Matched period":"January 1–November 18 for each year. 2024 includes a separate February-29-excluded sensitivity. Matching the cutoff cannot remove differences from pricing availability or mapping.",
        "Capture and negative share":"Capture equals SWLMP / all-hour mean only above +0.00001 USD/MWh. Negative exposure uses matched priced solar weight. Extreme threshold |LMP| ≥ 1000 USD/MWh flags the observation.",
        "Guide":"Solar_Profile and Solar_Profile_Config describe the model; Node_Summary, Monthly_Summary and Matched_Period give estimates; Hub_Comparison is hourly; Hub_Period_Summary contains hub aggregates. Node_Dictionary locates each matrix column.",
        "Hourly matrices":"Hourly_LMP contains published raw prices. Hourly_Weighted contains USD/MWh × assigned-zone weight-hours, the numerators. Missing prices and hours without assigned zones remain blank in the appropriate matrices.",
        "Evidence and QA":"Node_Zone_History supplies effective applied spans; Daily_Source_QA records individually dated retrievals. QA_Validation and Data_Issues document source, computations, classification and readback.",
        "Historical availability":"Node_Dictionary gives first and last price and largest internal gap over the whole study. A name containing PDRP is a naming heuristic. A mixed-classification period points to effective history.",
        "Scenario interpretation":"Within-zone prices use common weights. Cross-zone comparisons also reflect different TMY shapes. These project calculations use modeled profiles, not actual-year fleet generation or capture revenue.",
        "Configuration SHA-256":CONFIG_HASH}
    sheets=[frame_sheet("README",pd.DataFrame(list(text.items()),columns=["topic","value"])),
            frame_sheet("Solar_Profile",prof.reset_index(drop=True)),frame_sheet("Solar_Profile_Config",source_profiles()),
            table_from_summary("Node_Summary",stage,[primary],nb,n),table_from_summary("Monthly_Summary",stage,months,nb,n),
            table_from_summary("Matched_Period",stage,matched,nb,n),frame_sheet("Hub_Comparison",hub)]
    hubsumm=[]
    for period in periods:
        for b in sorted({inv.index.get_loc(node)//BATCH for node in C["basis_hubs"].values()}):
            df=pd.read_parquet(stage/"summary"/f"{period}_{b:03d}.parquet")
            hubsumm.append(df[df.reference_flag])
    sheets.extend([frame_sheet("Hub_Period_Summary",pd.concat(hubsumm,ignore_index=True)),
                   frame_sheet("Node_Dictionary",dictionary),frame_sheet("Node_Zone_History",history),
                   frame_sheet("Daily_Source_QA",daily),frame_sheet("Data_Issues",issues_df),frame_sheet("QA_Validation",qa_df)])
    for i in range(0,n,BATCH):
        bi=i//BATCH;keys=list(inv.index[i:i+BATCH])
        for weighted in (False,True):
            title=("Hourly_Weighted_" if weighted else "Hourly_LMP_")+f"{bi+1:03d}"
            sheets.append(Sheet(title,TIMECOLS+keys,len(index),lambda b=bi,k=keys,w=weighted:matrix_frames(stage,months,b,k,prof,w),True))
    return sheets
