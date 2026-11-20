"""Materialize compact, auditable reference inputs from the previously verified OASIS/PVWatts cache."""
from common import *
from history_references import windows
from metrics import canonical
import zipfile
import pandas as pd

def run():
    scheduled={(a.strftime("%Y%m%d"),b.strftime("%Y%m%d")) for a,b in windows()}
    frames=[];sources=[]
    for path in sorted((ROOT/"manifests").glob("PRC_LMP_*.json")):
        m=json.loads(path.read_text());q=m["params"]
        if q.get("node")!=",".join(C["basis_hubs"].values()) or (q["startdatetime"][:8],q["enddatetime"][:8]) not in scheduled:continue
        raw=ROOT/"cache"/(path.stem+".zip")
        if sha(raw)!=m["sha256"]:raise ValueError("bad hub reference archive")
        with zipfile.ZipFile(raw) as z:
            for n in z.namelist():frames.append(pd.read_csv(z.open(n),dtype=str,keep_default_na=False))
        sources.append({k:m[k] for k in ("endpoint","params","retrieved","sha256","size")})
    clean,conflicts,dup=canonical(pd.concat(frames,ignore_index=True))
    if len(conflicts):raise ValueError("hub reference has conflicting revisions")
    idx=["INTERVALSTARTTIME_GMT","OPR_DT","OPR_HR","OPR_INTERVAL","NODE_ID"]
    data=clean.pivot(index=idx,columns="LMP_TYPE",values="MW").reset_index()
    data["utc_start"]=pd.to_datetime(data.INTERVALSTARTTIME_GMT,utc=True)
    expected=pd.DatetimeIndex(list(hours(date.fromisoformat(C["start"]),date.fromisoformat(C["end_exclusive"]))))
    if set(data.NODE_ID)!=set(C["basis_hubs"].values()) or not pd.Index(data.utc_start.unique()).sort_values().equals(expected):raise ValueError("reference time coverage")
    folder=ROOT/"inputs";folder.mkdir(exist_ok=True)
    dst=folder/"independent_hubs.parquet";data.to_parquet(dst,index=False,compression="zstd")
    save_json(folder/"independent_hubs.json",dict(archives=sources,sha256=sha(dst),duplicate_rows=dup))
    sites=[json.loads(p.read_text()) for p in sorted((ROOT/"manifests").glob("*_PVWatts.json"))]
    if len(sites)!=6:raise ValueError("expected six model source metadata files")
    save_json(folder/"pvwatts_sources.json",sites)
if __name__=="__main__":run()
