"""Frozen study definitions and checks tying the analysis to original model observations."""
import json
import zipfile
import hashlib
import itertools
import numpy as np
import pandas as pd
from common import C, CONFIG_HASH, ROOT, sha, save_json
from solar import tmy_value
from reference import ZONES

SPEC_FILE=ROOT/"analysis_specification.json"
SPEC=json.loads(SPEC_FILE.read_text())
SPEC_HASH=sha(SPEC_FILE)
if SPEC["price_configuration_sha256"]!=CONFIG_HASH:
    raise ValueError("analysis specification requires review for this price/solar configuration")
if (SPEC["coverage"]["pass_pct"],SPEC["coverage"]["display_min_pct"])!=(C["thresholds"]["pass_pct"],C["thresholds"]["display_pct"]):
    raise ValueError("project coverage settings disagree")

def audit_model(index,profile,report):
    sources=json.loads((ROOT/"inputs/pvwatts_sources.json").read_text())
    frozen=json.loads((ROOT/"inputs/solar_profiles.json").read_text())
    year=index[0].year
    if sha(ROOT/"profiles"/f"Solar_Profile_{year}.csv.gz")!=frozen[str(year)]["sha256"]:raise ValueError("frozen calendar profile digest")
    rows=[];zone_series={}
    with zipfile.ZipFile(ROOT/"inputs/pvwatts_originals.zip") as archive:
        for m in sources:
            s=m["site"];node=s["node"];zone=s["zone"]
            raw=archive.read(node+"_PVWatts.json")
            if hashlib.sha256(raw).hexdigest()!=m["sha256"]:raise ValueError("raw model digest")
            source=json.loads(raw);ac=np.asarray(source["outputs"]["ac"],dtype=float)
            if (len(ac)!=8760 or not np.isfinite(ac).all() or (ac<0).any() or
                not np.isclose(ac.sum()/1000,source["outputs"]["ac_annual"],rtol=1e-5)):
                raise ValueError("original PVWatts hourly coverage or units failed; new repair assessment required for "+node)
            zone_series.setdefault(zone,[]).append((s["share"],ac/(1e6*C["ac_mw"])))
            rows.append(dict(model_location=node,zone=zone,source_sha256=m["sha256"],model_version=m["model_version"],
                expected_tmy_hours=8760,observed_original_hours=len(ac),unexpected_missing_hours=0,estimated_repair_hours=0))
    for zone,items in zone_series.items():
        if len(items)!=2 or not np.isclose(sum(w for w,_ in items),1):raise ValueError("configured composite shares")
        composite=sum(w*x for w,x in items)
        vals,leap=zip(*(tmy_value(composite,t) for t in index))
        if not np.allclose(profile[zone+"_weight_hours"],vals,rtol=1e-13,atol=1e-14):raise ValueError("profile differs from original site composite")
        if not np.array_equal(profile.leap_day_synthetic,leap) or profile.repair_flag.any():raise ValueError("unexpected repair/calendar flag")
    if any(np.array_equal(profile[a+"_weight_hours"],profile[b+"_weight_hours"]) for a,b in itertools.combinations(ZONES,2)):
        raise ValueError("zonal model shapes coincide for this scope")
    pd.DataFrame(rows).to_csv(report/"solar_location_audit.csv",index=False)
    pd.DataFrame(columns=["site","zone","utc_start","original_value","repaired_value","method","validation_performance","processing_version"]).to_csv(report/"solar_repairs.csv",index=False)
    out=dict(source_hours_verified=6*8760,sites=len(rows),estimated_repair_hours=0,repair_share=0.,repair_weight_share=0.,leap_day_hours=int(profile.leap_day_synthetic.sum()),
        repair_validation="NOT_TRIGGERED_NO_UNEXPECTED_MODEL_GAPS",changed_support_test="NOT_APPLICABLE_NO_REPAIRED_TIMESTAMPS",
        assessment="Original source coverage and composite reconstruction verified for every site, zone and delivery hour",specification_sha256=SPEC_HASH)
    save_json(report/"solar_audit.json",out)
    return out
