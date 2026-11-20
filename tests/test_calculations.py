"""Isolated synthetic unit fixtures. No fixture is accepted by any retrieval or export stage."""
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from common import *
from metrics import describe,canonical
from solar import tmy_value

class Checks(unittest.TestCase):
    def setUp(self):
        self.index=pd.date_range("2025-01-01",periods=4,freq="h",tz="UTC")
    def s(self,values):
        return pd.Series(values,index=self.index,dtype=float)
    def calc(self,p,w,h=None,c=None,status="DIRECT",ref=False):
        return describe(self.s(p),self.s(w),{"NP15":self.s(h if h is not None else [10]*4)},
            {"MCE":self.s(c if c is not None else p)},status,ref)
    def test_exact_and_conflicting(self):
        row=dict(NODE_ID="case",MARKET_RUN_ID="DAM",INTERVALSTARTTIME_GMT="t",LMP_TYPE="LMP",MW="10")
        a=pd.DataFrame([row,row,row|{"MW":"11"},row|{"LMP_TYPE":"MCE"}])
        clean,q,k=canonical(a)
        self.assertEqual((len(clean),len(q),k),(1,2,1))
        self.assertEqual(clean.LMP_TYPE.tolist(),["MCE"])
    def test_negative_and_missing(self):
        r=self.calc([-10,20,np.nan,5],[1,1,1,0])
        self.assertAlmostEqual(r["solar_weighted_lmp_usd_per_mwh"],5)
        self.assertAlmostEqual(r["negative_price_solar_share"],.5)
        self.assertEqual(r["hour_coverage_pct"],75)
        self.assertAlmostEqual(r["solar_coverage_pct"],200/3)
        self.assertIsNone(r["heatmap_lmp_usd_per_mwh"])
        self.assertEqual(r["availability"],"PARTIAL")
    def test_missing_component(self):
        r=self.calc([0,-1,4,5],[0,1,1,1],c=[np.nan,3,3,3])
        self.assertIsNone(r["MCE_weighted_usd_per_mwh"]);self.assertEqual(r["MCE_missing_on_valid_hours"],1)
    def test_pairwise(self):
        r=self.calc([-3,6,15,50],[0,.3,.7,0],h=[5,np.nan,10,3])
        self.assertAlmostEqual(r["NP15_basis_usd_per_mwh"],5);self.assertIsNone(r["NP15_display_basis_usd_per_mwh"])
        self.assertAlmostEqual(r["NP15_solar_coverage_pct"],70)
    def test_zero_weight(self):
        r=self.calc([1,2,np.nan,np.nan],[0,0,1,1])
        self.assertEqual(r["matched_weight_hours"],0);self.assertIsNone(r["solar_weighted_lmp_usd_per_mwh"])
    def test_zones(self):
        for st in ("UNRESOLVED","CONFLICTING","OUTSIDE_THREE_ZONE_SCOPE"):
            r=self.calc([1,2,3,4],[1]*4,status=st)
            self.assertIsNone(r["solar_weighted_lmp_usd_per_mwh"]);self.assertIsNone(r["solar_coverage_pct"])
            self.assertEqual(r["hour_coverage_pct"],100);self.assertIsNone(r["NP15_basis_usd_per_mwh"])
    def test_profile_gap(self):
        r=self.calc([1,2,3,4],[1,np.nan,1,1])
        self.assertEqual(r["solar_coverage_status"],"PROFILE_GAP");self.assertIsNone(r["solar_weighted_lmp_usd_per_mwh"])
    def test_night_missing(self):
        r=self.calc([np.nan,np.nan,1,2],[0,0,.4,.6])
        self.assertEqual(r["solar_coverage_status"],"PASS");self.assertEqual(r["hour_coverage_status"],"FAIL")
        self.assertAlmostEqual(r["heatmap_lmp_usd_per_mwh"],1.6)
    def test_capture_and_reference(self):
        for p in ([0]*4,[-1]*4,[1e-8]*4):
            r=self.calc(p,[1]*4,ref=True);self.assertIsNone(r["solar_capture_rate"]);self.assertEqual(r["heatmap_layer"],"REFERENCE")
    def test_join(self):
        hist=pd.DataFrame({"id":["one","two"]});meta=pd.DataFrame({"id":["one"],"type":["PNODE"]})
        joined=hist.merge(meta,how="left",on="id",validate="one_to_one",indicator=True)
        self.assertEqual(joined._merge.tolist(),["both","left_only"])
    def test_dst(self):
        for d,n in ((date(2024,3,10),23),(date(2024,11,3),25)):
            times=list(hours(d,d+DAY));self.assertEqual(len(times),n);self.assertEqual(len(set(times)),n)
        fall=[s.astimezone(PACIFIC) for s in hours(date(2024,11,3),date(2024,11,4))]
        self.assertEqual([t.fold for t in fall if t.hour==1],[0,1])
    def test_tmy(self):
        v=np.arange(8760,dtype=float)
        def mapped(d):return tmy_value(v,midnight(d)+timedelta(hours=5))
        avg=(mapped(date(2024,2,28))[0]+mapped(date(2024,3,1))[0])/2
        self.assertEqual(mapped(date(2024,2,29)),(avg,True))
        self.assertEqual(mapped(date(2024,3,1)),mapped(date(2025,3,1)))
        self.assertEqual(tmy_value(v,datetime(2025,1,1,7,tzinfo=UTC)),(8759,False))
    def test_no_observations(self):
        r=self.calc([np.nan]*4,[1]*4)
        self.assertEqual(r["availability"],"NO_OBSERVATIONS");self.assertIsNone(r["solar_weighted_lmp_usd_per_mwh"])
if __name__=="__main__":unittest.main()
