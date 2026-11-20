"""Target the pilot's disjoint geographic samples and obtain dated membership for every pilot."""
from common import *
from oasis import query
from pilot import mapping,raw
from metrics import canonical
import pandas as pd

def run():
    for day in [date.fromisoformat(s) for s in C["pilot_dates"]]:
        query(day,"ATL_PNODE_MAP")
    day=date.fromisoformat(C["site_evidence_date"])
    full=pd.read_parquet(ROOT/"canonical"/(str(day)+".parquet"))
    zones,info=mapping(day,sorted(full.node_id.unique()))
    unresolved=info.loc[info.mapping_status=="UNRESOLVED","node_id"].iloc[0]
    target=[sites[0][0] for sites in C["sites"].values()]+[unresolved]
    result=query(day,C["report"],target)
    small,conf,exact=canonical(pd.concat(list(raw(result)),ignore_index=True))
    if len(conf):raise ValueError("conflicting pilot retrieval")
    small=small[small.LMP_TYPE=="LMP"].copy()
    small["utc_start"]=pd.to_datetime(small.INTERVALSTARTTIME_GMT,utc=True)
    merged=full[full.node_id.isin(target)].merge(small.rename(columns={"NODE_ID":"node_id"})[["node_id","utc_start","MW"]],
        on=["node_id","utc_start"],validate="one_to_one",how="outer",indicator=True)
    if not merged._merge.eq("both").all() or not merged.LMP.equals(pd.to_numeric(merged.MW)):raise ValueError("independent sample mismatch")
    summaries=[]
    for s in C["pilot_dates"]:
        p=pd.read_parquet(ROOT/"canonical"/(s+".parquet"),columns=["node_id"])
        _,m=mapping(date.fromisoformat(s),sorted(p.node_id.unique()))
        m.insert(1,"date",s);summaries.append(m)
    detail=pd.concat(summaries,ignore_index=True)
    detail.to_csv(ROOT/"manifests/dated_pilot_node_mapping.csv.gz",index=False)
    save_json(ROOT/"manifests/independent-node-check.json",dict(date=str(day),nodes=target,matched_rows=len(merged),
        exact_duplicates=exact,source_sha256=sha(result),pilot_mapping_counts=detail.groupby(["date","mapping_status"]).size().unstack(fill_value=0).to_dict("index")))
if __name__=="__main__":run()
