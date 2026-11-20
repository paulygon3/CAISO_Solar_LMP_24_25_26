import unittest
from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from aggregate import summarize_period,weights,apply_price_conflicts
from gaps import runs,regime
from reference import solve
from common import C
from study import SPEC

class StudyTests(unittest.TestCase):
    def fixture(self,missing=False):
        t=pd.date_range("2024-02-01",periods=4,freq="h",tz="UTC")
        p=np.array([-10.,20.,30.,np.nan])[:,None]
        h=np.tile(np.array([5.,10.,20.,25.])[:,None],(1,3))
        codes=np.zeros((4,1),int);solar=np.array([0.,1.,.5,1.])[:,None]
        comp={"MCE":p.copy(),"MCC":np.zeros_like(p)};hc={"MCE":h.copy(),"MCC":np.zeros_like(h)}
        if missing:hc["MCC"][0,1]=np.nan
        return summarize_period(p,codes,solar,h,comp,{k:np.ones(4,bool) for k in comp},t,hc).iloc[0]
    def test_component_attribution_and_missing_hub_component(self):
        a=self.fixture();self.assertAlmostEqual(a.NP15_MCE_basis_diff_usd_per_mwh,10)
        self.assertEqual(a.NP15_MCC_basis_diff_usd_per_mwh,0)
        self.assertAlmostEqual(a.NP15_basis_usd_per_mwh,10)
        b=self.fixture(True);self.assertEqual(b.ZP26_component_basis_status,"INCOMPLETE_COMPONENT_SUPPORT")
        self.assertTrue(np.isnan(b.ZP26_MCE_basis_diff_usd_per_mwh));self.assertAlmostEqual(b.ZP26_basis_usd_per_mwh,10)
        self.assertEqual(b.known_weight_valid_priced_hours,3);self.assertAlmostEqual(b.negative_price_frequency,1/3)
    def test_zone_conflict_and_nonmatching_history(self):
        p=pd.DataFrame([["one","PNODE","one"]],columns=["node_id","PNODE_TYPE","DESCRIPTION"])
        h=pd.DataFrame([["one",C["basis_hubs"]["NP15"]]],columns=["node_id","APNODE_ID"])
        a=pd.DataFrame([["one",s] for s in ["AS_CAISO","AS_SP15","AS_SP26"]],columns=["node_id","AS_REGION_ID"])
        f=solve({"ATL_PNODE":p,"ATL_PNODE_MAP":h,"ATL_AS_REGION_MAP":a},pd.Index(["one","unknown"],name="node_id"))
        self.assertEqual(f.loc["one","zone_mapping_status"],"CONFLICTING")
        self.assertEqual(f.loc["unknown","metadata_match_status"],"UNMATCHED")
    def test_conflicting_total_blocks_affected_result(self):
        row=self.fixture().to_frame().T
        ids=pd.Index(["N"]);row.index=ids;t=pd.date_range("2024-02-01",periods=4,freq="h",tz="UTC")
        apply_price_conflicts(row,ids,t,{("N",t[2]):{"LMP"}})
        self.assertEqual(row.iloc[0].coverage_status,"SOURCE_CONFLICT")
        self.assertTrue(pd.isna(row.iloc[0].solar_weighted_lmp_usd_per_mwh))
        self.assertEqual(row.iloc[0].NP15_component_basis_status,"SOURCE_CONFLICT")
        self.assertEqual(row.iloc[0].total_price_conflict_hours,1)
    def test_gap_edges_and_regime(self):
        self.assertEqual(list(runs([True,True,False,True])),[(0,2),(3,4)])
        self.assertNotEqual(regime("2026-04-30"),regime("2026-05-01"))
    def test_changing_zones_keep_distinct_weights(self):
        solar=np.array([[1.,2.,3.],[1.5,2.5,3.5]])
        result=weights(np.array([[0,1,-1],[5,3,-2]]),solar)
        np.testing.assert_allclose(result,[[1.,2.,np.nan],[3.5,1.5,np.nan]],equal_nan=True)
if __name__=="__main__":unittest.main()
