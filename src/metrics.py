"""Nodal finite-support metrics for a single period, with hourly UTC rows on the full scaffold."""
import numpy as np
import pandas as pd
from common import C

def tier(pct):
    if pd.isna(pct):return None
    if pct>=C["thresholds"]["pass_pct"]:return "PASS"
    return "WARN" if pct>=C["thresholds"]["display_pct"] else "FAIL"

def canonical(rows):
    """Preserve original records outside this function. Return unambiguous prices and exceptions."""
    keys=["NODE_ID","INTERVALSTARTTIME_GMT","MARKET_RUN_ID","LMP_TYPE"]
    exact=int(rows.duplicated().sum())
    clean=rows.drop_duplicates().copy()
    # Without verified source revision precedence quarantine every remaining collision.
    collision=clean.duplicated(keys,keep=False)
    return clean.loc[~collision].copy(),clean.loc[collision].copy(),exact

def describe(price,weight,hubs,components,zone_status,reference=False):
    if not price.index.is_unique or len(price)==0:raise ValueError("expected unique nonempty hourly scaffold")
    for s in [weight,*hubs.values(),*components.values()]:
        if not s.index.equals(price.index):raise ValueError("unaligned series")
        if np.isinf(s.to_numpy(dtype=float)).any():raise ValueError("infinite input")
    if np.isinf(price.to_numpy(dtype=float)).any() or (weight.dropna()<0).any():raise ValueError("invalid price/weight")
    hourly=price.notna()
    n=len(price);valid=int(hourly.sum());p=price[hourly]
    ok=zone_status in ("DIRECT","INFERRED")
    profile_ok=ok and weight.notna().all()
    full=float(weight.sum()) if profile_ok else None
    w=weight[hourly]
    denom=float(w.sum()) if profile_ok else None
    numerator=float(np.dot(w,p)) if profile_ok else None
    # Incomplete zone/profile invalidates all assigned-zone ratios, even if some hours are mapped.
    sw=numerator/denom if denom is not None and denom>0 else None
    solar_pct=100*denom/full if full is not None and full>0 else None
    solar_status=tier(solar_pct)
    if not ok:
        solar_status={"CONFLICTING":"CONFLICTING_ZONE","OUTSIDE_THREE_ZONE_SCOPE":"OUTSIDE_THREE_ZONE_SCOPE"}.get(zone_status,"UNRESOLVED_ZONE")
    elif not profile_ok:solar_status="PROFILE_GAP"
    elif full==0:solar_status="NO_ESTIMATE"
    eligible=sw is not None and solar_pct>=C["thresholds"]["display_pct"]
    layer=("REFERENCE" if reference else "UNMAPPED" if not ok else "NO_ESTIMATE" if sw is None else "HEATMAP" if eligible else "LOW_COVERAGE")
    avg=float(p.mean()) if valid else None
    capture=None
    if avg is None: cap="NO_VALID_PRICE"
    elif sw is None:cap="NO_ESTIMATE"
    elif abs(avg)<=C["thresholds"]["capture_near_zero_usd_mwh"]:cap="NEAR_ZERO_DENOMINATOR"
    elif avg<0:cap="NEGATIVE_DENOMINATOR"
    else:cap="OK";capture=sw/avg
    neg_w=float(weight[hourly&price.lt(0)].sum()) if profile_ok else None
    result=dict(expected_hours=n,valid_price_hours=valid,missing_price_hours=n-valid,
        availability="NO_OBSERVATIONS" if valid==0 else ("PARTIAL" if valid<n else "FULL"),
        first_observed_utc=p.index[0].isoformat() if valid else None,last_observed_utc=p.index[-1].isoformat() if valid else None,
        valid_price_sum_usd_per_mwh_hours=float(p.sum()),time_weighted_lmp_usd_per_mwh=avg,
        min_lmp_usd_per_mwh=p.min(),max_lmp_usd_per_mwh=p.max(),negative_price_hours=int((p<0).sum()),
        zero_price_hours=int((p==0).sum()),extreme_price_hours=int((p.abs()>=C["thresholds"]["extreme_absolute_usd_mwh"]).sum()),
        hour_coverage_pct=100*valid/n,hour_coverage_status=tier(100*valid/n),full_period_weight_hours=full,
        matched_weight_hours=denom,weighted_numerator=numerator,solar_weighted_lmp_usd_per_mwh=sw,
        solar_coverage_pct=solar_pct,solar_coverage_status=solar_status,heatmap_eligible=bool(eligible),
        heatmap_lmp_usd_per_mwh=sw if eligible else None,heatmap_layer=layer,
        solar_capture_rate=capture,capture_status=cap,negative_weight_hours=neg_w,
        negative_price_solar_share=neg_w/denom if denom and denom>0 else None)
    if sw is not None:
        if not np.isclose((w/denom).sum(),1) or not np.isclose((p*w/denom).sum(),sw):raise ValueError("weighted contributions failed")
    complete=hourly.copy()
    for code,c in components.items():
        matched=hourly & c.notna()
        complete &= c.notna()
        missing=int((hourly & c.isna()).sum())
        num=float(np.dot(weight[matched],c[matched])) if profile_ok else None
        cd=float(weight[matched].sum()) if profile_ok else None
        result.update({f"{code}_valid_hours":int(matched.sum()),f"{code}_missing_on_valid_hours":missing,
                       f"{code}_matched_weight_hours":cd,f"{code}_numerator":num,
                       f"{code}_weighted_usd_per_mwh":num/denom if denom and not missing else None,
                       f"{code}_input_status":("NO_OBSERVATIONS" if not valid else "MISSING_COMPONENT_INPUTS" if missing else "INPUTS_COMPLETE")})
    result["common_component_valid_hours"]=int(complete.sum()) if components else None
    result["common_component_weight_hours"]=float(weight[complete].sum()) if profile_ok and components else None
    for z,h in hubs.items():
        pair=hourly & h.notna()
        cnt=int(pair.sum())
        pw=weight[pair]
        d=float(pw.sum()) if profile_ok else None
        sn=float(np.dot(pw,price[pair])) if profile_ok else None
        sh=float(np.dot(pw,h[pair])) if profile_ok else None
        bn=float(np.dot(pw,price[pair]-h[pair])) if profile_ok else None
        basis=bn/d if d and d>0 else None
        pc=100*d/full if full and full>0 else None
        use=basis is not None and pc>=C["thresholds"]["display_pct"]
        if basis is not None and not np.isclose(sn/d-sh/d,basis,atol=1e-8):raise ValueError("basis identity failed")
        values=dict(matched_hours=cnt,hour_coverage_pct=100*cnt/n,solar_coverage_pct=pc,weight_hours=d,
            node_numerator=sn,hub_numerator=sh,basis_numerator=bn,node_matched_usd_per_mwh=sn/d if d else None,
            hub_matched_usd_per_mwh=sh/d if d else None,basis_usd_per_mwh=basis,eligible=bool(use),display_basis_usd_per_mwh=basis if use else None,
            eligibility_reason="ELIGIBLE" if use else (solar_status if not profile_ok else "NO_MATCHED_WEIGHT" if not d else "LOW_COVERAGE"))
        result.update({f"{z}_{k}":v for k,v in values.items()})
    return result
