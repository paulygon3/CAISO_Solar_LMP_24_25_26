"""Keep large verified Excel files in a draft release until the complete study passes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from common import ROOT,sha
from acquire import gh

FINAL_TAG="annual-workbooks-v1"
CANDIDATE="caiso-annual-candidate-"+os.environ.get("GITHUB_RUN_ID","local")
TITLE="CAISO solar-weighted LMP workbooks, 2024–2026"

def release(tag):
    result=subprocess.run(["gh","release","view",tag,"--json","assets,isDraft"],text=True,capture_output=True)
    if result.returncode:
        if any(s in result.stderr.lower() for s in ("not found","release not found","404")):return None
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)

def prepare():
    state=release(CANDIDATE)
    if state is None:
        commit=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
        gh("release","create",CANDIDATE,"--draft","--target",commit,"--title",TITLE,"--notes","The annual workbooks are undergoing validation.")
    elif not state["isDraft"]:raise ValueError("candidate release is already public")

def verify_file(tag,path,assets):
    if path.name not in assets:raise ValueError("missing release asset "+path.name)
    entry=assets[path.name]
    if entry["size"]!=path.stat().st_size:raise ValueError("truncated release asset "+path.name)
    digest=entry.get("digest")
    if digest and digest.startswith("sha256:"):
        if digest!="sha256:"+sha(path):raise ValueError("release hash mismatch "+path.name)
    else:
        with tempfile.TemporaryDirectory() as d:
            gh("release","download",tag,"--pattern",path.name,"-D",d)
            if sha(Path(d)/path.name)!=sha(path):raise ValueError("release readback mismatch "+path.name)

def stage_file(path):
    if not path.exists() or path.stat().st_size>=2*1024**3:raise ValueError("file unavailable or exceeds individual release size limit: "+path.name)
    state=release(CANDIDATE)
    if not state or not state["isDraft"]:raise ValueError("expected an unpublished candidate release")
    assets={a["name"]:a for a in state["assets"]}
    if path.name not in assets:
        gh("release","upload",CANDIDATE,path)
        assets={a["name"]:a for a in release(CANDIDATE)["assets"]}
    verify_file(CANDIDATE,path,assets)

def stage_year(year):
    receipt=json.loads((ROOT/f"staging/support/{year}/readback.json").read_text())
    path=ROOT/"output"/receipt["filename"]
    if receipt["sealed_readback"]!="PASS" or sha(path)!=receipt["sha256"]:raise ValueError("unvalidated annual workbook")
    stage_file(path)

def run():
    support=ROOT/"staging/support"
    files=sorted((ROOT/"output").glob("*.xlsx"))+[ROOT/"staging/CAISO_provenance.zip",support/"RUN_REPORT.md"]
    if len(files)!=5:raise ValueError("three workbooks and two supporting files are required")
    existing=release(FINAL_TAG)
    if existing:
        assets={a["name"]:a for a in existing["assets"]}
        if set(assets)!={p.name for p in files}:raise ValueError("existing public release inventory differs")
        for p in files:verify_file(FINAL_TAG,p,assets)
        return
    prepare()
    for path in files:stage_file(path)
    state=release(CANDIDATE);assets=state["assets"]
    if {a["name"]:a["size"] for a in assets}!={p.name:p.stat().st_size for p in files}:raise ValueError("candidate release asset inventory")
    gh("release","edit",CANDIDATE,"--tag",FINAL_TAG,"--draft=false","--latest","--title",TITLE,"--notes-file",support/"RUN_REPORT.md")
    print(gh("release","view",FINAL_TAG,"--json","url"))

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",nargs="?",choices=["prepare","year","publish"],default="publish")
    p.add_argument("--year",type=int,choices=[2024,2025,2026]);a=p.parse_args()
    if a.mode=="prepare":prepare()
    elif a.mode=="year":
        if not a.year:p.error("--year is required")
        stage_year(a.year)
    else:run()
