"""Write ordinary XLSX tables with a single compressed worksheet stream open at a time."""
from dataclasses import dataclass
from datetime import datetime,date
from functools import lru_cache
import math
import re
import shutil
from pathlib import Path
import zipfile
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

@dataclass
class Sheet:
    name:str
    columns:list
    count:int
    frames:object
    matrix:bool=False

escape_token=re.compile(r"_x[0-9a-fA-F]{4}_")
illegal=re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
@lru_cache(maxsize=24000)
def safe_text(value):
    if len(value)>32767:raise ValueError("Excel text limit exceeded")
    value=escape_token.sub(lambda m:"_x005F_"+m.group()[1:],value)
    return escape(illegal.sub(lambda m:f"_x{ord(m.group()):04X}_",value)).replace("\r","&#13;").replace("\n","&#10;")

def cell(value,address,style):
    if value is None or value is pd.NA or value is pd.NaT:return ""
    if isinstance(value,(bool,np.bool_)):
        return f'<c r="{address}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value,(float,np.floating)):
        if math.isnan(value):return ""
        if not math.isfinite(value):raise ValueError("nonfinite numeric workbook input")
        return f'<c r="{address}"{style}><v>{value}</v></c>'
    if isinstance(value,(int,np.integer)):
        return f'<c r="{address}"{style}><v>{value}</v></c>'
    if isinstance(value,(datetime,date)):value=value.isoformat()
    value=str(value)
    if not value:return ""
    return f'<c r="{address}" t="inlineStr"><is><t xml:space="preserve">{safe_text(value)}</t></is></c>'

def style_for(col,ids):
    if col.endswith("_pct"):return ids["pct"]
    if any(s in col for s in ["usd_per_mwh","_lmp","_basis","_numerator"]):return ids["money"]
    if any(s in col for s in ["weight","share","rate","output_mw"]):return ids["decimal"]
    return ""

def skeleton(sheets,file,n_nonreference):
    with xlsxwriter.Workbook(file,{"strings_to_urls":False,"strings_to_formulas":False}) as book:
        header=book.add_format({"bold":True,"font_color":"#FFFFFF","bg_color":"#17485A","text_wrap":True,"valign":"vcenter"})
        formats={k:book.add_format({"num_format":v}) for k,v in {"money":"#,##0.00;[Red](#,##0.00);0.00","pct":'0.00"%"',"decimal":"0.000000"}.items()}
        blank=book.add_format()
        ids={k:f' s="{v._get_xf_index()}"' for k,v in formats.items()}
        for table in sheets:
            cols=list(table.columns)
            if len(cols)>16384 or table.count>1048575 or len(set(cols))!=len(cols):raise ValueError("Excel sheet limits or nonunique headers: "+table.name)
            ws=book.add_worksheet(table.name);ws.set_row(0,46);ws.write_row(0,0,cols,header)
            if table.count:ws.write_blank(table.count,len(cols)-1,None,blank)
            ws.autofilter(0,0,table.count,len(cols)-1)
            ws.freeze_panes(1,6 if table.matrix else 2 if cols[:2]==["node_id","node_name"] else 1)
            for j,key in enumerate(cols):
                width=(21 if j>=6 else 29) if table.matrix else min(44,max(14,len(key)+2))
                if key in ("value","detail","treatment","interpretation_impact","evidence","description"):width=85
                ws.set_column(j,j,width)
            if table.name=="Node_Summary" and n_nonreference:
                j=cols.index("heatmap_lmp_usd_per_mwh")
                ws.conditional_format(1,j,n_nonreference,j,{"type":"3_color_scale","min_color":"#C45D48","mid_color":"#FFF4C2","max_color":"#4B9B7E"})
    return ids

def xml_rows(table,ids):
    cols=list(table.columns);letters=[xl_col_to_name(i) for i in range(len(cols))]
    styles=[style_for(s,ids) for s in cols]
    rowno=1
    for df in table.frames():
        if list(df.columns)!=cols:raise ValueError("schema changed while writing "+table.name)
        if table.matrix:
            values=df.iloc[:,6:].to_numpy(dtype=float,copy=False)
            for i,meta in enumerate(df.iloc[:,:6].itertuples(index=False,name=None)):
                rowno+=1;r=str(rowno)
                first="".join(cell(x,letter+r,style) for x,letter,style in zip(meta,letters,styles))
                nums="".join(f'<c r="{letter}{r}"{ids["money"]}><v>{v}</v></c>' for letter,v in zip(letters[6:],values[i]) if v==v)
                yield f'<row r="{r}">{first}{nums}</row>\n'.encode()
        else:
            for row in df.itertuples(index=False,name=None):
                rowno+=1;r=str(rowno)
                cells="".join(cell(x,col+r,s) for x,col,s in zip(row,letters,styles))
                yield f'<row r="{r}">{cells}</row>\n'.encode()
    if rowno!=table.count+1:raise ValueError(f"{table.name}: wrote {rowno-1}, expected {table.count}")

def write_workbook(path,sheets,n_nonreference):
    shell=path.with_suffix(".skeleton.xlsx");ids=skeleton(sheets,shell,n_nonreference)
    with zipfile.ZipFile(shell) as src,zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as dest:
        for name in src.namelist():
            match=re.fullmatch(r"xl/worksheets/sheet(\d+)\.xml",name)
            if not match:
                dest.writestr(name,src.read(name));continue
            table=sheets[int(match[1])-1]
            data=src.read(name);top=data[:data.index(b"</row>")+6];bottom=data[data.index(b"</sheetData>"):]
            with dest.open(name,"w",force_zip64=True) as f:
                f.write(top+b"\n")
                for row in xml_rows(table,ids):f.write(row)
                f.write(bottom)
            if table.matrix and table.name.endswith(("001","011","021","031")):print("Wrote",table.name,flush=True)
    shell.unlink()
