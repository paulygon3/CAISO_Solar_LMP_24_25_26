"""Archive the CAISO SLD_REN_FCST actual-generation responses used in the hourly supplement."""
import argparse
import csv
import io
import json
import time
import zipfile
from datetime import date, timedelta
from hashlib import sha256
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree as ET

from common import C, ROOT, atomic, midnight, utcnow

SOURCE_PATH = ROOT / "inputs/historical_solar_actuals_oasis.zip"
CACHE = ROOT / "cache/solar_actuals_filtered"
FIRST = date.fromisoformat(C["start"])
END = date.fromisoformat(C["end_exclusive"])


def windows():
    day = FIRST
    while day < END:
        # At most 28 days per request, including around daylight-saving transitions.
        until = min(day + timedelta(days=28), END)
        yield day, until
        day = until


def query_url(start, end, hub):
    return C["oasis"] + "?" + urlencode({
        "resultformat": 6, "queryname": "SLD_REN_FCST", "version": 1, "market_run_id": "ACTUAL",
        "trading_hub": hub, "renewable_type": "Solar",
        "startdatetime": midnight(start).strftime("%Y%m%dT%H:%M-0000"),
        "enddatetime": midnight(end).strftime("%Y%m%dT%H:%M-0000"),
    })


def response_type(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if z.testzip() is not None or not z.namelist():
            raise ValueError("Invalid OASIS archive")
        if all(n.lower().endswith(".csv") for n in z.namelist()):
            return "CSV"
        if len(z.namelist()) == 1:
            root = ET.fromstring(z.read(z.namelist()[0]))
            code = root.findtext(".//{*}ERR_CODE")
            description = root.findtext(".//{*}ERR_DESC")
            if code == "1000" and "no data" in (description or "").lower():
                return "OASIS_NO_DATA"
            raise ValueError(f"OASIS {code}: {description}")
        raise ValueError("Unexpected response format")


def fetch(start, end, hub):
    key = f"{start}_{end}" if hub == "ALL" else f"{start}_{end}_{hub}"
    path = CACHE / (key + ".zip")
    receipt = CACHE / (key + ".json")
    # Request one extra day on each side to recover boundary hours and verify overlap.
    url = query_url(start - timedelta(days=1), end + timedelta(days=1), hub)
    if receipt.is_file() and path.is_file():
        record = json.loads(receipt.read_text())
        data = path.read_bytes()
        if record["url"] == url and sha256(data).hexdigest() == record["sha256"] and response_type(data) == record["result"]:
            return record
    for attempt in range(4):
        try:
            with urlopen(url, timeout=90) as response:
                data = response.read()
            status = response_type(data)
            break
        except (OSError, URLError, HTTPException, ValueError, zipfile.BadZipFile, ET.ParseError):
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
    record = dict(file=path.name, start=str(start), end_exclusive=str(end), url=url, retrieved_utc=utcnow(),
                  result=status, sha256=sha256(data).hexdigest())
    atomic(path, data)
    atomic(receipt, json.dumps(record).encode())
    print(key, status, len(data), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-day", type=date.fromisoformat, action="append", default=[],
                        help="Also query an individual delivery day to check a gap")
    parser.add_argument("--gap-file", type=Path, help="Retry missing delivery dates using each named trading hub")
    args = parser.parse_args()
    requests = [(a, b, "ALL") for a, b in windows()]
    requests.extend((d, d + timedelta(days=1), "ALL") for d in args.check_day)
    if args.gap_file:
        with args.gap_file.open() as handle:
            for row in csv.DictReader(handle):
                day = date.fromisoformat(row["pacific_start"][:10])
                zone = row["zone"]
                if zone not in C["basis_hubs"] or day < FIRST or day >= END:
                    raise ValueError("Invalid recovery request")
                requests.append((day, day + timedelta(days=1), zone))
    records = []
    for start, end, hub in dict.fromkeys(requests):
        key = f"{start}_{end}" if hub == "ALL" else f"{start}_{end}_{hub}"
        cached = (CACHE / (key + ".json")).exists()
        records.append(fetch(start, end, hub))
        if not cached:
            time.sleep(C["seconds_between_requests"])
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for r in records:
            archive.writestr(r["file"], (CACHE / r["file"]).read_bytes())
        archive.writestr("requests.json", json.dumps(records, indent=2) + "\n")
    atomic(SOURCE_PATH, result.getvalue())


if __name__ == "__main__":
    main()
