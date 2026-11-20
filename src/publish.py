"""Publish a draft only after every validated workbook and its evidence are available."""
import json
from pathlib import Path
import subprocess
import tempfile
from common import ROOT, sha
from acquire import gh
from dataset import REPO
TAG="annual-workbooks-v1"

def run():
    support=ROOT/"staging/support"
    files=sorted((ROOT/"output").glob("*.xlsx"))+[ROOT/"staging/CAISO_provenance.zip",support/"RUN_REPORT.md"]
    if len(files)!=5 or not all(p.is_file() and p.stat().st_size<2*1024**3 for p in files):raise ValueError("three valid release-sized workbooks and two supporting files required")
    if subprocess.run(["gh","release","view",TAG],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        gh("release","create",TAG,"--draft","--target",gh("api",f"repos/{REPO}/commits/main","--jq",".sha").strip(),"--title","CAISO solar-weighted LMP workbooks, 2024–2026","--notes-file",support/"RUN_REPORT.md")
    before=json.loads(gh("release","view",TAG,"--json","assets,isDraft"))
    existing={a["name"]:a for a in before["assets"]}
    for path in files:
        if path.name in existing:
            with tempfile.TemporaryDirectory() as d:
                gh("release","download",TAG,"--pattern",path.name,"-D",d)
                if sha(Path(d)/path.name)!=sha(path):raise ValueError("existing release differs: "+path.name)
        else:
            if not before["isDraft"]:raise ValueError("published release has different contents")
            gh("release","upload",TAG,path)
    assets=json.loads(gh("release","view",TAG,"--json","assets"))["assets"]
    if {a["name"]:a["size"] for a in assets}!={p.name:p.stat().st_size for p in files}:raise ValueError("published release asset inventory")
    if before["isDraft"]:gh("release","edit",TAG,"--draft=false","--latest")
    print(gh("release","view",TAG,"--json","url"))
if __name__=="__main__":run()
