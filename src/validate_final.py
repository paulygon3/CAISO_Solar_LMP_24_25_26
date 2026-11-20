"""Read written workbooks, exhaustively check axes and display rules, and sample original values."""
from collections import Counter
from pathlib import Path
import json
import re
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import openpyxl
import pandas as pd
from xlsxwriter.utility import xl_col_to_name

from common import C, CONFIG_HASH, DAY, HOUR, PACIFIC, ROOT, sha, utcnow
from aggregate import period_definitions, profile
from dataset import BATCH
from reference import ZONES, segments
from workbooks import TIMECOLS

REQUIRED=("README Solar_Profile Solar_Profile_Config Node_Summary Monthly_Summary Matched_Period "
          "Hub_Comparison Hub_Period_Summary Node_Dictionary Node_Zone_History Daily_Source_QA Data_Issues QA_Validation").split()
MARK="Final written-file readback"
DETAIL="Replaced with actual readback findings after validating the written candidate"

def require(ok,description):
    if not ok:raise ValueError(description)

def header(ws):
    return list(next(ws.values))

def source_samples(index,inventory):
    local=index.tz_convert(PACIFIC)
    selected={0,len(index)-1,len(index)//2,min(12,len(index)-1)}
    offsets=[t.utcoffset() for t in local]
    for i in range(1,len(offsets)):
        if offsets[i]!=offsets[i-1]:selected.update([i-1,i])
    for i,t in enumerate(local):
        if t.strftime("%Y-%m-%d") in C["pilot_dates"] and t.hour in [0,12]:selected.add(i)
    prices={};numerators={};solar=profile(local[0].year,index)
    for d in sorted({local[i].date() for i in selected}):
        path=ROOT/"canonical"/(str(d)+".parquet")
        record=json.loads((ROOT/"manifests"/f"canonical_{d}.json").read_text())
        require(sha(path)==record["sha256"],"canonical sample digest "+str(d))
        positions=[i for i in sorted(selected) if local[i].date()==d]
        times=index[positions]
        df=pd.read_parquet(path,columns=["utc_start","node_id","LMP"])
        raw=df[df.utc_start.isin(times)].pivot(index="utc_start",columns="node_id",values="LMP").reindex(index=times,columns=inventory.index)
        for lo,hi,mapping in segments(times,inventory.index):
            for j in range(lo,hi):
                i=positions[j];values=raw.iloc[j].to_numpy()
                w=mapping.solar_zone.map({z:solar.iloc[i][z+"_weight_hours"] for z in ZONES}).to_numpy(float)
                prices[i]=values;numerators[i]=values*w
    return prices,numerators

def matrix_row(row,r,letters):
    values=np.full(len(letters),np.nan);cols={letter:i for i,letter in enumerate(letters)}
    for e in ET.fromstring(row).iter("c"):
        letter=e.get("r")[:-len(str(r))]
        if letter in cols:
            item=e.findtext("v");require(item is not None,"non-numeric price cell")
            values[cols[letter]]=float(item)
    return values

def body(file):
    for line in file:
        if b"</row>" in line:break
    yield from file

def scan_matrix(z,member,frames,stamps,samples,start,width):
    lo=start;hi=start+width
    letters=[xl_col_to_name(i+6) for i in range(width)]
    seen=valid=sampled=0
    with z.open(member) as file:
        for line in body(file):
            if line.startswith(b"</sheetData>"):break
            r=seen+2
            require(line.startswith(f'<row r="{r}">'.encode()),f"matrix row sequence {member}/{r}")
            require(seen<len(frames),"extra timestamp")
            # All six metadata cells precede the numeric node cells. Values include delivery hour 25.
            prefix=line[:line.index(b"</c>",line.index(f'<c r="F{r}"'.encode()))+4]
            require(all(s in prefix for s in stamps[seen]),f"matrix timestamp mismatch {member}/{r}")
            valid+=line.count(b"<v>")-2
            if seen in samples:
                actual=matrix_row(line,r,letters)
                require(np.allclose(actual,samples[seen][lo:hi],equal_nan=True,rtol=1e-13,atol=1e-10),f"matrix differs from source {member}/{r}")
                sampled+=len(actual)
            seen+=1
    require(seen==len(frames),"matrix length "+member)
    return valid,sampled

def extract_rows(z,member,cols,fields):
    mapping={xl_col_to_name(cols.index(k)):k for k in fields}
    pattern=re.compile(rb'<c r="('+"|".join(mapping).encode()+rb')\d+"[^>]*>(?:<v>([^<]*)</v>|<is><t[^>]*>([^<]*)</t></is>)</c>')
    from html import unescape
    with z.open(member) as f:
        for i,line in enumerate(body(f),2):
            if line.startswith(b"</sheetData>"):break
            require(line.startswith(f'<row r="{i}">'.encode()),"table row sequence "+member)
            yield {mapping[k.decode()]:unescape((v or s).decode()) for k,v,s in pattern.findall(line)}

def check_summary(z,member,cols,periods,ids):
    fields=["node_id","period","coverage_status","solar_zone","solar_coverage_pct","heatmap_eligible","heatmap_lmp_usd_per_mwh","solar_weighted_lmp_usd_per_mwh","matched_weight_hours","weighted_numerator","negative_price_solar_share"]
    for zone in ZONES:
        fields.extend(zone+"_"+s for s in ["eligible","solar_coverage_pct","basis_usd_per_mwh","display_basis_usd_per_mwh","matched_node_usd_per_mwh","matched_hub_usd_per_mwh"])
    groups=Counter();count=0
    for row in extract_rows(z,member,cols,fields):
        p,n=divmod(count,len(ids));count+=1
        require(p<len(periods) and row["period"]==periods[p] and row["node_id"]==ids[n],"summary key or order")
        eligible=row["heatmap_eligible"]=="1";sw=row.get("solar_weighted_lmp_usd_per_mwh")
        display=row.get("heatmap_lmp_usd_per_mwh");coverage=row.get("solar_coverage_pct")
        require(eligible==(sw is not None and coverage is not None and float(coverage)>=C["thresholds"]["display_pct"]),"nodal eligibility")
        require(display==(sw if eligible else None),"nodal display")
        if not row.get("solar_zone"):require(sw is None,"unmapped retained estimate")
        if row["coverage_status"]=="LOW_COVERAGE":require(sw is not None,"low coverage retention")
        if coverage is not None:require(-1e-8<=float(coverage)<=100+1e-8,"solar coverage bounds")
        if sw is not None:
            require(np.isclose(float(sw),float(row["weighted_numerator"])/float(row["matched_weight_hours"]),rtol=1e-11,atol=1e-10),"weighted ratio readback")
        if "negative_price_solar_share" in row:require(0<=float(row["negative_price_solar_share"])<=1+1e-9,"negative share bounds")
        for zone in ZONES:
            q=lambda name:row.get(zone+"_"+name)
            b=q("basis_usd_per_mwh");ok=q("eligible")=="1";cov=q("solar_coverage_pct")
            require(ok==(b is not None and cov is not None and float(cov)>=C["thresholds"]["display_pct"]),"basis eligibility")
            require(q("display_basis_usd_per_mwh")==(b if ok else None),"basis display")
            if b is not None:
                diff=float(q("matched_node_usd_per_mwh"))-float(q("matched_hub_usd_per_mwh"))
                require(abs(float(b)-diff)<1e-7,"basis readback identity")
        groups[row["coverage_status"]]+=1
    require(count==len(periods)*len(ids),"summary population")
    return count,dict(groups)

def validate(path,inventory,index,test=False):
    wb=openpyxl.load_workbook(path,read_only=True,data_only=True,keep_links=True)
    require(not wb._external_links,"unexpected external workbook link")
    ids=list(inventory.index);periods=list(period_definitions(index,test))
    months=[p for p in periods if p[0].isdigit()];matched=[p for p in periods if p.startswith("MATCHED")]
    expected=REQUIRED.copy()
    for i in range(0,len(ids),BATCH):
        expected.extend(x+f"{i//BATCH+1:03d}" for x in ("Hourly_LMP_","Hourly_Weighted_"))
    require(wb.sheetnames==expected,"sheet inventory/order")
    q=dict((a,b) for a,b,_ in list(wb["QA_Validation"].values)[1:])
    p=profile(index[0].year,index)
    source=pd.read_parquet(ROOT/"inputs/independent_hubs.parquet",columns=["utc_start","OPR_HR","OPR_INTERVAL"])
    labels=source.drop_duplicates().set_index("utc_start").loc[index]
    stamps=[]
    for t,meta,hr,opr in zip(index,p[TIMECOLS[:4]].itertuples(index=False,name=None),labels.OPR_HR,labels.OPR_INTERVAL):
        n=len(stamps)+2
        require(meta[0]==t.isoformat() and meta[1]==(t+HOUR).isoformat() and meta[2]==t.tz_convert(PACIFIC).isoformat(),"time presentation independent check")
        stamps.append([f">{v}</t>".encode() for v in meta]+[f'<c r="{col}{n}"><v>{v}</v></c>'.encode() for col,v in (("E",int(hr)),("F",int(opr)))])
    raw,weighted=source_samples(index,inventory)
    members={s:f"xl/worksheets/sheet{i+1}.xml" for i,s in enumerate(expected)}
    summary_counts={};counts=[0,0];sampled=[0,0]
    with zipfile.ZipFile(path) as z:
        require(not any("externallinks/" in n.lower() or n.lower().endswith("vbaproject.bin") for n in z.namelist()),"external workbook payload")
        for table,seq in [("Node_Summary",periods[:1]),("Monthly_Summary",months),("Matched_Period",matched)]:
            ws=wb[table];require(ws.max_row==len(ids)*len(seq)+1 and header(ws)[:2]==["node_id","node_name"],"summary shape")
            summary_counts[table]=check_summary(z,members[table],header(ws),seq,ids)
        dictionary=wb["Node_Dictionary"]
        fields=["node_id","raw_sheet","weighted_sheet","matrix_column"];seen=0
        for i,row in enumerate(extract_rows(z,members[dictionary.title],header(dictionary),fields)):
            b,k=divmod(i,BATCH);num=f"{b+1:03d}"
            require(row==dict(node_id=ids[i],raw_sheet="Hourly_LMP_"+num,weighted_sheet="Hourly_Weighted_"+num,matrix_column=xl_col_to_name(k+6)),"dictionary address")
            seen+=1
        require(seen==len(ids),"dictionary row count")
        for table in ["Solar_Profile","Hub_Comparison"]:
            require(wb[table].max_row==len(index)+1,"hour table length "+table)
            seen=0
            for i,row in enumerate(extract_rows(z,members[table],header(wb[table]),["utc_interval_start"])):
                require(row["utc_interval_start"]==index[i].isoformat(),"hour table timestamps")
                seen+=1
            require(seen==len(index),"hour table body length")
        for i in range(0,len(ids),BATCH):
            batch=ids[i:i+BATCH]
            for j,(prefix,samples) in enumerate([("Hourly_LMP_",raw),("Hourly_Weighted_",weighted)]):
                key=prefix+f"{i//BATCH+1:03d}";ws=wb[key]
                require(ws.max_row==len(index)+1 and header(ws)==TIMECOLS+batch,"matrix layout "+key)
                count,compared=scan_matrix(z,members[key],index,stamps,samples,i,len(batch))
                counts[j]+=count;sampled[j]+=compared
        require(z.testzip() is None,"archive CRC failure")
    require(counts[0]==q["Valid hourly prices"] and counts[1]==q["Nonmissing hourly numerators"],"written matrix counts")
    wb.close()
    return dict(validated_utc=utcnow(),config_sha256=CONFIG_HASH,hours=len(index),nodes=len(ids),worksheets=len(expected),
        summary_rows_checked={k:v[0] for k,v in summary_counts.items()},annual_coverage_status=summary_counts["Node_Summary"][1],
        valid_prices=counts[0],valid_numerators=counts[1],sample_utc=[index[i].isoformat() for i in sorted(raw)],
        sampled_raw_cells=sampled[0],sampled_weighted_cells=sampled[1],matrix_headers_and_timestamps="EXHAUSTIVE",
        dictionary_and_summary_keys_and_display_rules="EXHAUSTIVE",archive_crc="ALL_MEMBERS",external_links=0,
        mapping_counts={k.split(" / ")[1]:v for k,v in q.items() if k.startswith("zone_mapping_status / ")},
        classifications={k.split(" / ")[1]:v for k,v in q.items() if k.startswith("node_classification / ")},
        heatmap_layers={k.split(" / ")[1]:v for k,v in q.items() if k.startswith("heatmap_layer / ")},
        qa=q,qa_member=members["QA_Validation"],status="PASSED")

def seal(path,receipt):
    member=receipt["qa_member"]
    with zipfile.ZipFile(path) as z:
        original={i.filename:(i.CRC,i.file_size) for i in z.infolist() if i.filename!=member}
        qa=z.read(member)
    require(qa.count(b">PENDING</t>")==1 and qa.count(DETAIL.encode())==1,"readback placeholder")
    detail=(f"Validated all {receipt['hours']:,} hourly axes in every matrix, {receipt['nodes']:,} dictionary entries, all summary keys and display rules. "
            f"Compared {receipt['sampled_raw_cells']:,} raw and {receipt['sampled_weighted_cells']:,} weighted cell positions to source samples. All archive CRCs passed.")
    qa=qa.replace(b">PENDING</t>",b">PASS</t>").replace(DETAIL.encode(),detail.encode())
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        target=Path(tmp)/member;target.parent.mkdir(parents=True);target.write_bytes(qa)
        subprocess.run(["zip","-q",str(path.resolve()),member],cwd=tmp,check=True)
    with zipfile.ZipFile(path) as z:
        require(original=={i.filename:(i.CRC,i.file_size) for i in z.infolist() if i.filename!=member},"unexpected worksheet change")
        require(z.read(member)==qa and z.testzip() is None,"final archive validation")
    wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
    require([r for r in wb["QA_Validation"].values if r[0]==MARK]==[(MARK,"PASS",detail)],"sealed QA result")
    wb.close()
    receipt.update(bytes=path.stat().st_size,sha256=sha(path),sealed_readback="PASS")
    receipt["qa"][MARK]="PASS"
