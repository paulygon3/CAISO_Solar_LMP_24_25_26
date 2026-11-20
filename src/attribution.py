"""Attribute matched node-minus-hub basis to published components on the identical pairwise support."""
import numpy as np
from study import SPEC
KNOWN={"MCC","MCE","MCL","MGHG"}

def decompose(prices,hub,weights,pair,all_resolved,components,hub_components,applicable,den,basis):
    n,k=prices.shape
    common=pair.copy()
    known=np.ones(n,bool);has=np.zeros(n,bool)
    node_sum=np.zeros_like(prices);hub_sum=np.zeros(n)
    nums={}
    for code,v in components.items():
        on=applicable[code];h=hub_components[code]
        has|=on
        if code not in KNOWN:known&=~on
        good=np.isfinite(v)&np.isfinite(h[:,None])
        common&=(~on[:,None])|good
        node_sum+=np.where(on[:,None]&np.isfinite(v),v,0)
        hub_sum+=np.where(on&np.isfinite(h),h,0)
        contribute=pair&on[:,None]&good
        nums[code]=np.sum(np.where(contribute,(v-h[:,None])*weights,0),axis=0)
    tested=common&(known&has)[:,None]
    tol=SPEC["reconciliation"]["component_review_usd_mwh"]+SPEC["reconciliation"]["floating_absolute_epsilon"]
    residual=(prices-hub[:,None])-(node_sum-hub_sum[:,None])
    invalid=tested&((np.abs(prices-node_sum)>tol)|(np.abs(hub-hub_sum)[:,None]>tol)|(np.abs(residual)>2*tol))
    exceptions=invalid.sum(0);matched=pair.sum(0);complete=tested.sum(0)
    publish=all_resolved&(den>0)&(matched==complete)&(exceptions==0)
    with np.errstate(divide="ignore",invalid="ignore"):
        weighted_residual=np.where(all_resolved&(den>0)&(matched==complete),np.sum(np.where(tested,residual*weights,0),axis=0)/den,np.nan)
        out={"component_basis_pair_hours":matched,"component_basis_verified_hours":complete,"component_basis_exceptions":exceptions,
             "component_basis_residual_usd_per_mwh":weighted_residual,"component_basis_status":np.select([~all_resolved,den<=0,complete<matched,exceptions>0],["MAPPING_INCOMPLETE","NO_MATCHED_WEIGHT","INCOMPLETE_COMPONENT_SUPPORT","RECONCILIATION_EXCEPTION"],default="PUBLISHED_COMPONENTS_VERIFIED")}
        for code,num in nums.items():
            relevant=(pair&applicable[code][:,None]).any(0)
            out[code+"_basis_diff_usd_per_mwh"]=np.where(publish&relevant,num/den,np.nan)
        total=sum(np.nan_to_num(out[c+"_basis_diff_usd_per_mwh"]) for c in nums) if nums else np.zeros(k)
        if publish.any() and not np.allclose((total+weighted_residual)[publish],basis[publish],rtol=1e-10,atol=1e-8):raise ValueError("basis component reconstruction")
    return out
