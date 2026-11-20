"""Export compact node-zone lookups from the three published annual workbooks."""
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
HISTORY_FIELDS = (
    "node_id", "effective_from_utc", "effective_until_utc_exclusive", "solar_zone",
    "zone_mapping_status", "zone_mapping_method", "published_hubs", "as_region", "mapping_detail",
)
ZONES = {"NP15", "ZP26", "SP15"}
PACIFIC = ZoneInfo("America/Los_Angeles")


def selected_rows(sheet, fields):
    rows = sheet.values
    header = next(rows)
    columns = [header.index(name) for name in fields]
    for row in rows:
        yield tuple(row[i] if row[i] is not None else "" for i in columns)


def write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def main():
    results = ROOT / "results"
    receipts = json.loads((results / "completion.json").read_text())["years"]
    annual = {}
    dated = []
    header = ["node_id"]
    for receipt in receipts:
        year = receipt["year"]
        header.extend([f"zone_{year}", f"status_{year}"])
        book = load_workbook(ROOT / "output" / receipt["filename"], read_only=True, data_only=True)
        try:
            dictionary = {}
            for node, zone, status in selected_rows(book["Node_Dictionary"], ["node_id", "solar_zone", "zone_mapping_status"]):
                if node in dictionary:
                    raise ValueError(f"Duplicate {node} in {year} dictionary")
                dictionary[node] = (zone, status)
            if len(dictionary) != receipt["study_inventory_nodes"] or (annual and annual.keys() != dictionary.keys()):
                raise ValueError(f"Inventory mismatch in {year}")
            for node, assignment in dictionary.items():
                annual.setdefault(node, []).extend(assignment)

            # Check continuity within each reporting year before exposing the intervals for date lookups.
            intervals = sorted(selected_rows(book["Node_Zone_History"], HISTORY_FIELDS))
            first = datetime.fromisoformat(receipt["period_first"]).replace(tzinfo=PACIFIC)
            end_date = date.fromisoformat(receipt["period_last"]) + timedelta(days=1)
            end = datetime.combine(end_date, datetime.min.time(), tzinfo=PACIFIC)
            ends = {}
            for row in intervals:
                node, start_text, end_text, zone, status = row[:5]
                start, until = datetime.fromisoformat(start_text), datetime.fromisoformat(end_text)
                if start != ends.get(node, first) or until <= start:
                    raise ValueError(f"Noncontiguous {node} history in {year}")
                if (zone in ZONES) != (status in {"DIRECT", "INFERRED"}):
                    raise ValueError(f"Inconsistent dated zone for {node} in {year}")
                ends[node] = until
            if ends.keys() != dictionary.keys() or any(t != end for t in ends.values()):
                raise ValueError(f"Incomplete dated history in {year}")
            dated.extend(intervals)
        finally:
            book.close()

    write_csv(results / "node_zones_by_year.csv", header, ([node, *annual[node]] for node in sorted(annual)))
    write_csv(results / "node_zone_history.csv", HISTORY_FIELDS, sorted(dated))


if __name__ == "__main__":
    main()
