from pathlib import Path
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config.json"
C = json.loads(CONFIG_FILE.read_text())
UTC = timezone.utc
PACIFIC = ZoneInfo(C["timezone"])
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
CONFIG_HASH = hashlib.sha256(CONFIG_FILE.read_bytes()).hexdigest()

def utcnow():
    return datetime.now(UTC).isoformat()

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    os.replace(tmp, path)

def save_json(path, obj):
    atomic(path, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode())

def midnight(d):
    return datetime.combine(d, time(), tzinfo=PACIFIC).astimezone(UTC)

def hours(start, end):
    cur = midnight(start)
    limit = midnight(end)
    while cur < limit:
        yield cur
        cur += HOUR

def date_range(start, end):
    while start < end:
        yield start
        start += DAY

def record(event):
    path = ROOT / "manifests/events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"utc": utcnow(), **event}) + "\n")
