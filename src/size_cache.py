"""Test lossless columnar archival of all response fields, row order, and cell strings."""
from common import *
import csv
import io
import zipfile
import pyarrow as pa
import pyarrow.csv as pc
import pyarrow.parquet as pq

def run():
    sizes=[]
    for mf in sorted((ROOT/"manifests").glob("PRC_LMP*.json")):
        m=json.loads(mf.read_text())
        if m["params"].get("grp_type")!="ALL":continue
        path=ROOT/"cache"/(mf.stem+".zip")
        result=0
        with zipfile.ZipFile(path) as z:
            for member in z.namelist():
                with z.open(member) as f:
                    cols=next(csv.reader([f.readline().decode()]))
                opts=pc.ConvertOptions(column_types={s:pa.string() for s in cols},strings_can_be_null=False)
                with z.open(member) as f:
                    table=pc.read_csv(f,convert_options=opts).combine_chunks()
                target=ROOT/"benchmark"/"cache-test.parquet"
                pq.write_table(table,target,compression="zstd",compression_level=9,row_group_size=1000000)
                if not pq.read_table(target).equals(table):raise ValueError("columnar archive round trip failed")
                result+=target.stat().st_size
                target.unlink()
        sizes.append(dict(date=m["params"]["startdatetime"][:8],raw=path.stat().st_size,parquet_bytes=result))
        print(sizes[-1],flush=True)
    save_json(ROOT/"manifests/cache-sizing.json",sizes)
if __name__=="__main__":run()
