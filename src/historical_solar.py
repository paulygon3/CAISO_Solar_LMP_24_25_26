"""Join measured hourly zonal solar output to the study's independently retrieved day-ahead hub prices."""
import csv
import io
import json
import math
import zipfile
from collections import Counter
from datetime import datetime
from hashlib import sha256

import numpy as np
import pandas as pd

from common import C, HOUR, PACIFIC, ROOT, atomic, hours
from solar_actuals_source import END, FIRST, SOURCE_PATH, response_type, windows

ZONES = tuple(C["basis_hubs"])
OUT = ROOT / "results/historical_hourly"
HUB_PRICES = ROOT / "inputs/independent_hubs.parquet"


def published_solar(path, expected):
    values = {}
    seen_keys = set()
    duplicate_count = 0
    with zipfile.ZipFile(path) as outer:
        records = json.loads(outer.read("requests.json"))
        windows_done = {(r["start"], r["end_exclusive"]) for r in records}
        if any((str(a), str(b)) not in windows_done for a, b in windows()):
            raise ValueError("Missing acquisition request")
        for record in records:
            data = outer.read(record["file"])
            if sha256(data).hexdigest() != record["sha256"] or response_type(data) != record["result"]:
                raise ValueError(f"Invalid receipt: {record['file']}")
            if record["result"] != "CSV":
                continue
            with zipfile.ZipFile(io.BytesIO(data)) as inner:
                for member in inner.namelist():
                    with inner.open(member) as f:
                        for row in csv.DictReader(io.TextIOWrapper(f)):
                            zone = row["TRADING_HUB"]
                            if zone not in ZONES or row["RENEWABLE_TYPE"] != "Solar":
                                continue
                            if row["MARKET_RUN_ID"] != "ACTUAL" or row["XML_DATA_ITEM"] != "RENEW_FCST_ACT_MW":
                                raise ValueError("Unexpected series in actual production query")
                            t = datetime.fromisoformat(row["INTERVALSTARTTIME_GMT"])
                            end = datetime.fromisoformat(row["INTERVALENDTIME_GMT"])
                            if t.utcoffset() is None or end-t != HOUR or t.minute or t.second or t.microsecond:
                                raise ValueError("Invalid hourly interval")
                            if t not in expected:
                                continue  # query padding outside the study calendar
                            value = float(row["MW"]) if row["MW"].strip() else None
                            if value is not None and not math.isfinite(value):
                                raise ValueError(f"Invalid solar MW at {t}, {zone}")
                            key = (t, zone)
                            if key in seen_keys:
                                duplicate_count += 1
                            seen_keys.add(key)
                            if value is not None:
                                if key in values and values[key] != value:
                                    raise ValueError(f"Conflicting published solar MW at {t}, {zone}")
                                values[key] = value
    return values, seen_keys, duplicate_count, records


def price_frame(index):
    prices = pd.read_parquet(HUB_PRICES, columns=["utc_start", "NODE_ID", "LMP"])
    prices["LMP"] = pd.to_numeric(prices.LMP, errors="raise")
    hubs = prices.pivot(index="utc_start", columns="NODE_ID", values="LMP").rename(
        columns={hub: zone for zone, hub in C["basis_hubs"].items()})
    if set(hubs.columns) != set(ZONES) or not hubs.index.equals(index) or not np.isfinite(hubs.values).all():
        raise ValueError("Published hub price coverage differs from the study calendar")
    return hubs


def period_metrics(year, period, zone, g, p):
    observed = g.notna()
    net = g.loc[observed]
    price = p.loc[observed]
    energy = net.clip(lower=0)
    total = energy.sum()
    signed = net.sum()
    return dict(year=year, period=period, zone=zone, expected_hours=len(g), observed_hours=int(observed.sum()),
                missing_hours=int((~observed).sum()), negative_generation_hours=int((net < 0).sum()),
                observed_signed_net_mwh=signed if len(net) else None,
                observed_positive_export_mwh=total if len(net) else None,
                observed_positive_export_weighted_lmp_usd_per_mwh=(energy @ price)/total if total > 0 else None,
                observed_signed_net_weighted_lmp_usd_per_mwh=(net @ price)/signed if signed > 0 else None)



def write_report(summary, audit):
    base = "https://raw.githubusercontent.com/paulygon3/CAISO_Solar_LMP_24_25_26/main/results/historical_hourly/"
    lines = [
        "# Historical hourly solar generation and day-ahead hub prices",
        "",
        f"[Download the hourly CSV]({base}hourly_solar_and_hub_prices.csv) · [Download the monthly and annual hub results]({base}hub_periods.csv)",
        "",
        f"The file has one row for each of {audit['expected_delivery_hours']:,} Pacific delivery hours from {audit['first_delivery']} through {audit['last_delivery']}. CAISO OASIS supplied {audit['observed_solar_zone_hours']:,} of {audit['expected_solar_zone_hours']:,} hourly solar readings across NP15, ZP26 and SP15 and all {audit['valid_day_ahead_zone_hours']:,} day-ahead hub prices. Blank production cells identify missing published readings. A numeric zero is an observed value. [Missing hours](missing_hours.csv)",
        "",
        "## How to read an hour",
        "",
        "UTC start and end identify the exact one-hour delivery interval. The Pacific start includes the offset so the repeated fall hour remains identifiable. Each zone has three columns.",
        "",
        "| Column ending | Meaning |",
        "| --- | --- |",
        "| actual_solar_mw | CAISO-reported average solar power for the hour, in MW, for the trading hub's reporting resources. All signed values are preserved. |",
        "| positive_export_mwh | Positive hourly production used as the weight, in MWh. For these one-hour intervals this equals the larger of reported MW and zero. Missing production remains blank. |",
        "| day_ahead_lmp_usd_per_mwh | Published total day-ahead price for that generation trading hub, in USD/MWh. |",
        "",
        "## Day-ahead prices weighted by reported positive solar production",
        "",
        "| Pacific delivery period | NP15 ($/MWh) | ZP26 ($/MWh) | SP15 ($/MWh) | Solar hours observed per zone |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    annual = summary.loc[summary.period.isin(["FULL_YEAR","YTD"])]
    for year, data in annual.groupby("year"):
        data = data.set_index("zone").loc[list(ZONES)]
        coverage = ", ".join(dict.fromkeys(f"{int(r.observed_hours):,}/{int(r.expected_hours):,}" for r in data.itertuples()))
        label = f"{year} through Nov 18" if year == END.year else str(year)
        amounts = [f"{v:.2f}" for v in data.observed_positive_export_weighted_lmp_usd_per_mwh]
        lines.append("| " + " | ".join([label, *amounts, coverage]) + " |")
    lines += [
        "",
        "Each price equals the sum of hourly price times positive exported MWh divided by observed positive exported MWh. The period CSV also gives the alternative signed-net result, which includes negative reported MW. Both calculations use only observed price and production pairs. A missing hour leaves its generation and value unknown. The JAN01_NOV18 rows in the period CSV compare the same calendar dates each year.",
        "",
        "A hub price applies the area's reported production to its day-ahead hub LMP. A plant's own hourly production and settlement prices determine its realized revenue. For a node-level benchmark, match the node's dated zone and UTC delivery hour, then apply that zone's generation weights to the node's own price. [Dated node-zone mapping](../node_zone_history.csv)",
        "",
        "## Data and checks",
        "",
        "The solar series comes from OASIS SLD_REN_FCST v1, market run ACTUAL, renewable type Solar, data item RENEW_FCST_ACT_MW. The requests specify the trading-hub and renewable-type filters. CAISO describes this report as covering eligible intermittent resources. The price series comes from the OASIS PRC_LMP day-ahead total LMP for each named hub. The original annual workbooks use the separate PVWatts typical-weather scenario. [CAISO OASIS API FAQ, question 7](https://www.caiso.com/documents/oasis-frequently-asked-questions.pdf) · [Original solar responses and dated request URLs](../../inputs/historical_solar_actuals_oasis.zip) · [Hub price source receipts](../../inputs/independent_hubs.json)",
        "",
        "Overlapping requests cover the calendar boundaries and provide repeated observations to check for disagreements. Named-hub requests check missing intervals. Every UTC hour in the saved CSV, its reported solar MW, its signed-to-positive conversion and its day-ahead price were checked against the source inputs. [Validation totals](source_check.json)",
        "",
        "To rebuild the files from the bundled inputs, install the repository requirements and run `python src/historical_solar.py`. To retrieve fresh OASIS data, first run `python src/solar_actuals_source.py`, then `python src/historical_solar.py`. If the gap list contains records, run `python src/solar_actuals_source.py --gap-file results/historical_hourly/missing_hours.csv` and rebuild.",
    ]
    atomic(OUT / "README.md", ("\n".join(lines) + "\n").encode())

def main():
    index = pd.DatetimeIndex(hours(FIRST, END))
    solar, seen, duplicates, records = published_solar(SOURCE_PATH, set(index))
    prices = price_frame(index)
    frame = pd.DataFrame(index=index)
    frame["utc_start"] = index.strftime("%Y-%m-%dT%H:%M:%SZ")
    frame["utc_end"] = (index + HOUR).strftime("%Y-%m-%dT%H:%M:%SZ")
    local = index.tz_convert(PACIFIC)
    frame["pacific_start_with_offset"] = [t.isoformat() for t in local]
    metrics = []
    for z in ZONES:
        g = pd.Series([solar.get((t,z), np.nan) for t in index], index=index, dtype=float)
        p = prices[z]
        frame[f"{z}_actual_solar_mw"] = g
        frame[f"{z}_positive_export_mwh"] = g.clip(lower=0)
        frame[f"{z}_day_ahead_lmp_usd_per_mwh"] = p
        for year in sorted(set(local.year)):
            mask = local.year == year
            labels = {"YTD" if year == END.year else "FULL_YEAR": mask,
                      "JAN01_NOV18": mask & ((local.month < 11) | ((local.month == 11) & (local.day <= 18)))}
            for month in sorted(set(local[mask].month)):
                labels[f"{year}-{month:02}"] = mask & (local.month == month)
            for label, select in labels.items():
                metrics.append(period_metrics(year, label, z, g[select], p[select]))
    OUT.mkdir(parents=True, exist_ok=True)
    atomic(OUT / "hourly_solar_and_hub_prices.csv", frame.to_csv(index=False).encode())
    summary = pd.DataFrame(metrics).sort_values(["year","period","zone"])
    atomic(OUT / "hub_periods.csv", summary.to_csv(index=False).encode())
    gaps = []
    for z in ZONES:
        for t in index[frame[f"{z}_actual_solar_mw"].isna()]:
            gaps.append(dict(zone=z, utc_start=t.isoformat(), pacific_start=t.tz_convert(PACIFIC).isoformat(),
                             source_status="BLANK_MW" if (t,z) in seen else "NO_MATCHING_ROW"))
    atomic(OUT / "missing_hours.csv", pd.DataFrame(gaps, columns=["zone","utc_start","pacific_start","source_status"]).to_csv(index=False).encode())
    audit = dict(first_delivery=str(FIRST), last_delivery=str((index[-1].tz_convert(PACIFIC)).date()),
                 expected_delivery_hours=len(index), observed_solar_zone_hours=len(solar), expected_solar_zone_hours=len(index)*len(ZONES),
                 valid_day_ahead_zone_hours=prices.size, missing_solar_zone_hours=len(gaps),
                 duplicate_keys_across_retrievals=duplicates, source_response_types=dict(Counter(r["result"] for r in records)),
                 raw_archive_sha256=sha256(SOURCE_PATH.read_bytes()).hexdigest(),
                 day_ahead_price_input_sha256=sha256(HUB_PRICES.read_bytes()).hexdigest())
    atomic(OUT / "source_check.json", (json.dumps(audit, indent=2)+"\n").encode())
    write_report(summary, audit)
    print(summary.loc[summary.period.isin(["FULL_YEAR","YTD"])].to_string(index=False), flush=True)
    print(json.dumps(audit), flush=True)


if __name__ == "__main__":
    main()
