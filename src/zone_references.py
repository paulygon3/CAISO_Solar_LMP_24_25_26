"""Historical ancillary-service region, resource classification and load-factor reference snapshots."""
from common import *
from acquire import periods,package,gh,upload,release_inventory
from oasis import query
import argparse
def run():
    p=argparse.ArgumentParser()
    p.add_argument("--month");p.add_argument("--release")
    args=p.parse_args()
    out=ROOT/"staging/packages";out.mkdir(parents=True,exist_ok=True)
    for start,end in periods():
        month=start.strftime("%Y-%m")
        if args.month and args.month!=month:continue
        archive=out/(month+"-zones.zip");receipt=out/(month+"-zones.json")
        if args.release and receipt.name in release_inventory(args.release):continue
        files=[]
        for day in (start,start+28*DAY):
            if day>=end:continue
            for report in ("ATL_AS_REGION_MAP","ATL_RESOURCE","ATL_LDF"):
                f=query(day,report,end=min(end,day+28*DAY));files.extend([f,ROOT/"manifests"/(f.stem+".json")])
        info=package(archive,files)
        save_json(receipt,dict(month=month,config_sha256=CONFIG_HASH,asset=info,source="CAISO OASIS"))
        if args.release:upload(args.release,[archive,receipt])
if __name__=="__main__":run()
