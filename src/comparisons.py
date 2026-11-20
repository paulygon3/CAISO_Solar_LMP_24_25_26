"""Build cross-year balanced-node and missingness comparisons from final annual evidence."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from common import C,save_json
from reference import ZONES

METRICS=["solar_weighted_lmp_usd_per_mwh","time_weighted_lmp_usd_per_mwh","solar_coverage_pct","hour_coverage_pct","negative_price_solar_share",
         "negative_price_frequency","largest_10_hours_absolute_weighted_contribution_share"]+[z+"_basis_usd_per_mwh" for z in ZONES]

def comparisons(support):
    whole_study_gaps(support)
    cols=["node_id","solar_zone","zone_mapping_status","reference_flag","heatmap_eligible","period","valid_price_hours",*METRICS]
    full=[];matched=[];regional=[];timing=[]
    for year in (2024,2025,2026):
        folder=support/str(year)
        for name,dest in [("Node_Summary",full),("Matched_Period",matched)]:
            f=pd.read_parquet(folder/(name+".parquet"),columns=cols);f["year"]=year;dest.append(f)
        f=pd.read_parquet(folder/"gap_composition.parquet")
        f["month"]=f.delivery_date.str[:7]
        for key in ["month","node_type","zone","market","snapshot_area","market_regime","delivery_date"]:
            g=f.groupby(key,dropna=False)[["observed","expected"]].sum().reset_index()
            g["missing"]=g.expected-g.observed;g["missing_share"]=g.missing/g.expected
            g=g.rename(columns={key:"value"});g["grouping"]=key;g["year"]=year;regional.append(g)
        g=pd.read_parquet(folder/"hourly_gap_scope.parquet")
        for key in ["local_hour","month","market_regime","delivery_date"]:
            h=g.groupby(key)[["observed","universe","internal_missing","internal_eligible"]].sum().reset_index()
            h["internal_missing_share"]=h.internal_missing.div(h.internal_eligible.replace(0,np.nan));h["all_missing_share"]=1-h.observed/h.universe
            h=h.rename(columns={key:"value"});h["grouping"]=key;h["year"]=year;h["value"]=h.value.astype(str);timing.append(h)
    full=pd.concat(full,ignore_index=True);matched=pd.concat(matched,ignore_index=True)
    common=matched[matched.period.eq("MATCHED_JAN01_NOV18")].copy()
    good=common[(~common.reference_flag)&common.solar_zone.isin(ZONES)&common.zone_mapping_status.isin(["DIRECT","INFERRED"])&
                common.heatmap_eligible&(common.hour_coverage_pct>=C["thresholds"]["display_pct"])]
    e=good.groupby("node_id").agg(years=("year","nunique"),zones=("solar_zone","nunique"))
    balanced=e.index[(e.years==3)&(e.zones==1)]
    panel=common[common.node_id.isin(balanced)].copy().sort_values(["node_id","year"])
    panel.to_parquet(support/"balanced_node_matched_period.parquet",index=False,compression="zstd")
    panels=[]
    for name,f in [("FULL_YEAR_OR_YTD",full),("MATCHED_ALL_AVAILABLE",matched),("BALANCED_MATCHED_SAME_NODES",panel)]:
        eligible=f[~f.reference_flag & f.heatmap_eligible]
        for (year,period,zone),g in eligible.groupby(["year","period","solar_zone"]):
            row=dict(population=name,year=year,period=period,zone=zone,nodes=len(g))
            for metric in METRICS:
                for quant,label in [(0.1,"p10"),(0.5,"median"),(0.9,"p90")]:
                    row[label+"_"+metric]=g[metric].quantile(quant)
            panels.append(row)
    pd.DataFrame(panels).to_csv(support/"population_comparison.csv",index=False)
    regions=pd.concat(regional,ignore_index=True);regions.to_csv(support/"gap_clustering_by_area_and_batch.csv",index=False)
    time=pd.concat(timing,ignore_index=True);time.to_csv(support/"gap_clustering_by_calendar.csv",index=False)
    summary={"balanced_nodes":len(balanced),"balanced_counts_by_zone":{k:int(v) for k,v in panel.drop_duplicates("node_id").solar_zone.value_counts().items()},
        "rule":"Nonreference, stable single zone, accepted direct/inferred mapping, heatmap eligible and >=90% hour coverage in every January 1–November 18 window.",
        "population_metric":"Cross-node quantiles give each qualifying node one observation; hub reference rows are excluded.",
        "highest_internal_missing_share_by_pacific_hour":[]}
    for year,g in time[time.grouping=="local_hour"].groupby("year"):
        peak=g.nlargest(1,"internal_missing_share").iloc[0]
        summary["highest_internal_missing_share_by_pacific_hour"].append(dict(year=int(year),hour=int(peak.value),share=float(peak.internal_missing_share),numerator=int(peak.internal_missing),denominator=int(peak.internal_eligible)))
    save_json(support/"comparison_summary.json",summary)
    return summary

def whole_study_gaps(support):
    """Join date-adjacent missing runs across workbook boundaries while retaining annual register detail."""
    columns=["node_id","category","run_start_utc","run_end_utc_exclusive"]
    pieces=[]
    for y in [2024,2025,2026]:
        f=pd.read_parquet(support/str(y)/"price_gap_register.parquet",columns=columns).drop_duplicates()
        if len(f):pieces.append(f)
    if not pieces:
        pd.DataFrame(columns=["node_id","category","study_start_utc","study_end_utc_exclusive","study_consecutive_hours"]).to_parquet(support/"price_gap_study_runs.parquet",index=False)
        return
    f=pd.concat(pieces,ignore_index=True).sort_values(["node_id","run_start_utc"])
    boundary=f.node_id.ne(f.node_id.shift())|f.category.ne(f.category.shift())|f.run_start_utc.ne(f.run_end_utc_exclusive.shift())
    g=f.groupby(boundary.cumsum(),sort=False).agg(node_id=("node_id","first"),category=("category","first"),study_start_utc=("run_start_utc","first"),study_end_utc_exclusive=("run_end_utc_exclusive","last"))
    g["study_consecutive_hours"]=((g.study_end_utc_exclusive-g.study_start_utc).dt.total_seconds()/3600).astype(int)
    g.to_parquet(support/"price_gap_study_runs.parquet",index=False,compression="zstd")
