"""Package the verified continuation files with member checksums; avoid session-specific portal pages."""
from common import *
import zipfile

def run():
    from document import run as document
    document()
    public_evidence={"reference.bin","reference.txt","faq.pdf","faq.txt","membership.bin","contour.bin","weather-interval.bin","pvwatts-doc.bin","nsrdb.bin","hub-pilot.bin"}
    files=[f for f in ROOT.rglob("*") if f.is_file() and "__pycache__" not in f.parts and f.suffix!=".pyc" and not f.name.endswith(".part")]
    files=[f for f in files if f.parent.name!="evidence" or f.name in public_evidence]
    files=[f for f in files if f.name!="contents.sha256"]
    hashes={str(f.relative_to(ROOT)):sha(f) for f in sorted(files)}
    check=ROOT/"manifests/contents.sha256"
    atomic(check,("".join(f"{digest}  {name}\n" for name,digest in hashes.items())).encode())
    files.append(check)
    dest=ROOT.parent/"CAISO_resume.zip"
    tmp=dest.with_suffix(".tmp")
    with zipfile.ZipFile(tmp,"w",allowZip64=True) as z:
        for f in sorted(files):
            method=zipfile.ZIP_STORED if f.suffix in {".zip",".xlsx",".parquet",".gz",".pdf"} else zipfile.ZIP_DEFLATED
            z.write(f,arcname=str(Path("caiso")/f.relative_to(ROOT)),compress_type=method)
    with zipfile.ZipFile(tmp) as z:
        if z.testzip():raise ValueError("checkpoint ZIP CRC failure")
        for name,digest in hashes.items():
            with z.open("caiso/"+name) as f:
                if hashlib.file_digest(f,"sha256").hexdigest()!=digest:raise ValueError("checkpoint mismatch "+name)
    os.replace(tmp,dest)
    print(f"{dest} | {len(files)} files | {dest.stat().st_size} bytes | sha256 {sha(dest)}")
if __name__=="__main__":run()
