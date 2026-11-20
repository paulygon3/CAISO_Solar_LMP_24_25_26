"""Resolve exact historical IDs on the intersection of OASIS query and source-effective intervals."""
from collections import defaultdict
import json
import re
import zipfile

import numpy as np
import pandas as pd
from common import C, ROOT, sha

HUBS=C["basis_hubs"]
ZONES=list(HUBS)
HUB_ZONE={v:k for k,v in HUBS.items()}
REPORTS={
    "ATL_PNODE":("PNODE_ID",["PNODE_TYPE","DESCRIPTION"]),
    "ATL_APNODE":("APNODE_ID",["APNODE_TYPE","DESCRIPTION"]),
    "ATL_HUB":("APNODE_ID",["DESCRIPTION"]),
    "ATL_PNODE_MAP":("PNODE_ID",["APNODE_ID"]),
    "ATL_TAC_AREA_MAP":("PNODE_ID",["TAC_AREA_ID"]),
    "ATL_AS_REGION_MAP":("PNODE_ID",["AS_REGION_ID"]),
    "ATL_RESOURCE":("NODE_ID",["RESOURCE_TYPE"]),
    "ATL_LDF":("APNODE_ID",["PNODE_ID","DIST_FACTOR","SEASON","TIME_OF_USE"]),
}
AREA_SETS={
    frozenset(["AS_NP15","AS_NP26"]):"NP15",
    frozenset(["AS_SP15","AS_NP26"]):"ZP26",
    frozenset(["AS_SP15","AS_SP26"]):"SP15",
}
AREA_NAMES={"AS_NP15","AS_NP26","AS_SP15","AS_SP26"}
MAP_SOURCE="OASIS ATL_PNODE_MAP / ATL_AS_REGION_MAP / ATL_LDF v1"
BASE_FIELDS=["solar_zone","zone_mapping_status","zone_mapping_method","mapping_detail","published_hubs",
             "node_classification","node_subtype","resource_type","description","tac_area","as_region",
             "market_classification","metadata_match_status"]

def epoch(values):
    # Midnight in some source reports is represented in extended future years.
    stamps=pd.to_datetime(values,utc=True,format="ISO8601",errors="raise")
    return stamps.astype("datetime64[s, UTC]").astype("int64")

def param_time(label):
    return int(pd.to_datetime(label,format="%Y%m%dT%H:%M-0000",utc=True).timestamp())

def reference_windows(timestamps):
    start=int(timestamps[0].timestamp());end=int(timestamps[-1].timestamp())+3600
    grouped=defaultdict(list)
    for p in sorted((ROOT/"manifests").glob("ATL_*.json")):
        m=json.loads(p.read_text());q=m["params"];name=q["queryname"]
        if name not in REPORTS:continue
        lo=max(start,param_time(q["startdatetime"]));hi=min(end,param_time(q["enddatetime"]))
        if lo>=hi:continue
        path=ROOT/"cache"/(p.stem+".zip")
        if not path.exists() or sha(path)!=m["sha256"]:raise ValueError("missing or corrupt reference "+p.name)
        key,cols=REPORTS[name]
        with zipfile.ZipFile(path) as z:
            for f in z.namelist():
                cols2=[key,*cols,"EFF_START_DT_GMT","EFF_END_DT_GMT"]
                a=pd.read_csv(z.open(f),dtype=str,keep_default_na=False,usecols=cols2)
                if name=="ATL_AS_REGION_MAP":
                    a=a[a.AS_REGION_ID.isin(AREA_NAMES|{"AS_CAISO"})].copy()
                if a.empty:continue
                a["lo"]=np.maximum(epoch(a.EFF_START_DT_GMT),lo)
                a["hi"]=np.minimum(epoch(a.EFF_END_DT_GMT)+1,hi)
                a=a[a.lo<a.hi].drop_duplicates()
                a=a.rename(columns={key:"node_id"});grouped[name].append(a)
    frames={k:pd.concat(v,ignore_index=True).drop_duplicates() for k,v in grouped.items()}
    return frames

def by_id(table,column):
    if table.empty:return {}
    pairs=table[["node_id",column]].drop_duplicates()
    return pairs.groupby("node_id",sort=False)[column].agg(lambda s:"|".join(sorted(x for x in set(s) if x))).to_dict()

def solve(active,ids):
    empty=pd.DataFrame()
    get=lambda k:active.get(k,empty)
    p=get("ATL_PNODE");ap=get("ATL_APNODE")
    ps=set(p.node_id) if not p.empty else set()
    aps=set(ap.node_id) if not ap.empty else set()
    ptype=by_id(p,"PNODE_TYPE");atype=by_id(ap,"APNODE_TYPE")
    descriptions=by_id(pd.concat([p,ap],ignore_index=True),"DESCRIPTION")
    resource=by_id(get("ATL_RESOURCE"),"RESOURCE_TYPE");tac=by_id(get("ATL_TAC_AREA_MAP"),"TAC_AREA_ID")
    direct=by_id(get("ATL_PNODE_MAP"),"APNODE_ID")
    area=by_id(get("ATL_AS_REGION_MAP"),"AS_REGION_ID")
    row={}
    for node in ids:
        memberships=set(filter(None,direct.get(node,"").split("|")))
        targeted={HUB_ZONE[h] for h in memberships if h in HUB_ZONE}
        other=memberships-set(HUB_ZONE)
        ars=set(area.get(node,"").split("|"))
        crossed=("AS_CAISO" in ars and ({"AS_NP15","AS_SP15"}<=ars or {"AS_NP26","AS_SP26"}<=ars))
        aszone=AREA_SETS.get(frozenset(ars&AREA_NAMES)) if "AS_CAISO" in ars else None
        evidence="";method="None";status="UNRESOLVED";zone=""
        if node in HUB_ZONE:
            zone=HUB_ZONE[node];status="DIRECT";method="Named trading hub"
        elif crossed:
            status="CONFLICTING";method="Overlapping internal AS path regions"
            evidence="|".join(sorted(ars&AREA_NAMES))
        elif len(targeted|({aszone} if aszone else set()))>1 or (other and (targeted or aszone)):
            status="CONFLICTING";method="Conflicting dated memberships"
            evidence="; ".join(sorted(memberships))+f" / AS path inference {aszone}"
        elif targeted:
            zone=next(iter(targeted));status="DIRECT";method="Exact trading-hub member"
        elif other:
            status="OUTSIDE_THREE_ZONE_SCOPE";method="Member of other published hub"
            evidence="Scope determined by published hub membership"
        elif aszone:
            zone=aszone;status="INFERRED";method="Two internal AS path subregions"
        market="CAISO_AS_REGION" if "AS_CAISO" in ars else ("OTHER_HUB_MEMBERSHIP" if other else "UNKNOWN")
        cls="PNODE_AND_APNODE" if node in ps and node in aps else "PNODE" if node in ps else "APNODE" if node in aps else "UNKNOWN"
        matched=cls!="UNKNOWN" or bool(memberships) or node in resource or node in tac or node in area
        row[node]=[zone,status,method,evidence,direct.get(node,""),cls,ptype.get(node,"") or atype.get(node,""),
                   resource.get(node,""),descriptions.get(node,""),tac.get(node,""),area.get(node,""),market,
                   "MATCHED" if matched else "UNMATCHED"]
    df=pd.DataFrame.from_dict(row,orient="index",columns=BASE_FIELDS)
    df.index.name="node_id"
    ldf=get("ATL_LDF")
    if not ldf.empty:
        factors=ldf[["node_id","PNODE_ID","DIST_FACTOR","SEASON","TIME_OF_USE"]].drop_duplicates().copy()
        factors["factor"]=pd.to_numeric(factors.DIST_FACTOR,errors="raise")
        factors=factors[factors.factor!=0].copy()
        factors["zone"]=factors.PNODE_ID.map(df.solar_zone).fillna("")
        for node,g in factors.groupby("node_id",sort=False):
            if node not in df.index or node in HUB_ZONE:continue
            sums=g.groupby(["SEASON","TIME_OF_USE"]).factor.sum()
            options=set(g.zone)
            if len(options)!=1 or "" in options or not np.allclose(sums,100,rtol=0,atol=0.02):continue
            candidate=next(iter(options));old=df.at[node,"zone_mapping_status"]
            if old=="UNRESOLVED":
                df.loc[node,BASE_FIELDS[:4]]=[candidate,"INFERRED","All nonzero LDF members agree",f"{g.PNODE_ID.nunique()} distinct PNodes; participation totals checked"]
            elif old in ("DIRECT","INFERRED","OUTSIDE_THREE_ZONE_SCOPE") and df.at[node,"solar_zone"]!=candidate:
                df.loc[node,BASE_FIELDS[:4]]=["","CONFLICTING","LDF and other evidence disagree",candidate]
    return df

def segments(timestamps,ids):
    frames=reference_windows(timestamps)
    times=timestamps.as_unit("s").asi8
    changes={0,len(times)}
    for f in frames.values():
        boundaries=np.unique(np.concatenate((f.lo.unique(),f.hi.unique())))
        changes.update(np.searchsorted(times,boundaries).tolist())
    marks=sorted(changes)
    for a,b in zip(marks,marks[1:]):
        if a==b:continue
        active={name:f[(f.lo<=times[a])&(times[a]<f.hi)] for name,f in frames.items()}
        yield a,b,solve(active,ids)

def contour():
    x=json.loads((ROOT/"evidence/contour.bin").read_text())
    marker=[(m["n"],m.get("a",""),m.get("p","")) for layer in x["l"] for m in layer["m"] if m.get("n")]
    df=pd.DataFrame(marker,columns=["node_id","snapshot_area","snapshot_type"]).drop_duplicates()
    result=df.groupby("node_id",sort=False).agg(lambda a:"|".join(sorted(set(a))))
    result["price_map_snapshot_time"]=x["d"]
    return result
