"""Build the key-metrics Markdown from a published CAISO_provenance.zip."""
import argparse
import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26"
ZONES = ("NP15", "ZP26", "SP15")


def table(headers, rows):
    def row(values):
        return "| " + " | ".join(map(str, values)) + " |"

    return "\n".join([row(headers), row(["---"] + ["---:"] * (len(headers) - 1)), *map(row, rows)])


def hub_section(years):
    with (ROOT / "results/verified_hub_periods.csv").open() as source:
        hubs = {(int(r["year"]), r["period"], r["solar_zone"]): r for r in csv.DictReader(source)}
    annual_rows = []
    trend_rows = []
    spreads = []
    for year in years:
        period = "YTD" if year == 2026 else "FULL_YEAR"
        matched = []
        for zone in ZONES:
            r = hubs[year, period, zone]
            annual_rows.append([
                f"{year}{' YTD' if period == 'YTD' else ''} · {zone}",
                f"{float(r['time_weighted_lmp_usd_per_mwh']):.2f}",
                f"{float(r['solar_weighted_lmp_usd_per_mwh']):.2f}",
                f"{float(r['solar_capture_rate']):.1%}",
                f"{int(r['negative_price_hours']):,}",
                f"{float(r['negative_price_solar_share']):.1%}",
            ])
            assert int(r["valid_price_hours"]) == int(r["expected_hours"])
            matched.append(float(hubs[year, "MATCHED_JAN01_NOV18", zone]["solar_weighted_lmp_usd_per_mwh"]))
        # This spread compares two hub benchmarks, each using its own zonal profile.
        spreads.append(matched[0] - matched[2])
        trend_rows.append([year, *[f"{v:.2f}" for v in matched], f"{spreads[-1]:.2f}"])
    return [
        "# CAISO solar-weighted price report",
        "Day-ahead trading hubs and pricing locations · Full years 2024–2025 and 2026 through November 18 · Pacific delivery dates",
        f"**The gap between northern and southern solar prices narrowed.** Over January 1–November 18, the NP15 solar-weighted price exceeded SP15 by \\${spreads[0]:.2f}/MWh in 2024 and \\${spreads[-1]:.2f}/MWh in 2026. Each hub uses its own zonal solar profile.",
        "## Trading hub results",
        "Prices are in USD per megawatt-hour. The all-hours price gives every delivery hour equal weight. The solar price gives more weight to hours with greater modeled solar output.",
        table(["Period · hub", "All-hours price", "Solar price", "Capture rate", "Negative hours", "Solar at negative prices"], annual_rows),
        "**Capture rate** is the solar price divided by the all-hours price. **Solar at negative prices** is the share of modeled generation during hours with a price below zero. Each hub had a published price in every hour.",
        "## How the hubs compare on the same dates",
        table(["January 1–November 18", "NP15 solar price", "ZP26 solar price", "SP15 solar price", "NP15 minus SP15"], trend_rows),
        "All four columns are in USD/MWh. The 2024 window includes February 29. These hub differences reflect both prices and solar timing. The workbooks also provide node-to-hub basis with identical weights on both prices.",
    ]


def location_section(archive, receipts):
    rows = []
    exposure = []
    cols = ["heatmap_layer", "valid_price_hours", "negative_price_hours", "zero_price_hours",
            "matched_weight_hours", "negative_weight_hours"]
    for r in receipts:
        year = r["year"]
        frame = pq.read_table(io.BytesIO(archive.read(f"{year}/Node_Summary.parquet")), columns=cols).to_pandas()
        comparable = frame.loc[frame.heatmap_layer.eq("HEATMAP")]
        priced = int(frame.valid_price_hours.sum())
        hours = int(r["hours"])
        eligible = len(comparable)
        assert priced == r["valid_prices"] and eligible == r["heatmap_layers"]["HEATMAP"]
        rows.append([f"{year}{' YTD' if year == 2026 else ''}", f"{hours:,}",
                     f"{frame.valid_price_hours.gt(0).sum():,}", f"{priced:,}",
                     f"{priced/(len(frame)*hours):.1%}", f"{eligible:,}"])
        exposure.append([f"{year}{' YTD' if year == 2026 else ''}",
                         f"{frame.negative_price_hours.sum()/priced:.1%}",
                         f"{frame.zero_price_hours.sum()/priced:.1%}",
                         f"{comparable.negative_price_hours.sum()/comparable.valid_price_hours.sum():.1%}",
                         f"{comparable.negative_weight_hours.sum()/comparable.matched_weight_hours.sum():.1%}"])
    populations = {}
    with archive.open("population_comparison.csv") as source:
        for r in csv.DictReader(io.TextIOWrapper(source)):
            if r["population"] == "BALANCED_MATCHED_SAME_NODES":
                populations[int(r["year"]), r["zone"]] = r
    years = [r["year"] for r in receipts]
    medians = []
    for zone in ZONES:
        window = [populations[y, zone] for y in years]
        assert len({r["nodes"] for r in window}) == 1
        medians.append([zone, f"{int(window[0]['nodes']):,}",
                        *[f"{float(r['median_solar_weighted_lmp_usd_per_mwh']):.2f}" for r in window]])
    balanced_count = sum(int(populations[years[-1], zone]["nodes"]) for zone in ZONES)
    last_mapping = receipts[-1]["mapping_counts"]
    return [
        "## Market coverage and negative prices",
        table(["Period", "Delivery hours", "IDs with a price", "Valid hourly prices", "Price coverage", "Eligible nodes"], rows),
        "**Price coverage** uses all 20,048 historical IDs times the delivery hours in that period. **Eligible nodes** have a supported zone assignment and prices for at least 90% of their modeled solar output. The three reference hubs are counted separately from eligible nodes.",
        table(["Period", "Negative hours, all IDs", "Zero hours, all IDs", "Negative hours, eligible nodes", "Solar at negative prices, eligible nodes"], exposure),
        f"The first three percentages count priced node-hours. The last pools matched modeled output across eligible nodes. For {years[-1]} YTD, negative prices occurred during {exposure[-1][3]} of those nodes’ priced hours and coincided with {exposure[-1][4]} of their matched modeled solar output.",
        f"## Prices across the same {balanced_count:,} nodes",
        "Median node-level solar price, USD/MWh. Each column uses January 1–November 18. Each node counts once and keeps the same zone in all three years, with at least 90% coverage of both hours and modeled solar output in each window.",
        table(["Zone", "Nodes", *years], medians),
        "## Sources and confidence",
        "CAISO OASIS published the hourly day-ahead prices. Separate named-hub downloads verified all three hub price histories. The study weights prices with PVWatts V8 modeled output from two equally weighted sites per zone under typical weather. Actual plant revenue depends on delivered generation and settlement terms.",
        f"Dated CAISO memberships support direct node assignments. Some zones are inferred from other market records. For {years[-1]} YTD, {last_mapping['UNRESOLVED']:,} IDs had unresolved assignments and {last_mapping['CONFLICTING']:,} had conflicting evidence. Raw prices remain available for those IDs wherever CAISO published them.",
        f"[Verified hub results]({REPO}/blob/main/results/verified_hub_periods.csv) · [Coverage and validation]({REPO}/blob/main/results/RUN_REPORT.md) · [Node results and provenance]({REPO}/releases/download/annual-workbooks-v1/CAISO_provenance.zip) · [Solar model inputs]({REPO}/blob/main/inputs/pvwatts_sources.json)",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provenance", type=Path)
    args = parser.parse_args()
    receipts = json.loads((ROOT / "results/completion.json").read_text())["years"]
    with ZipFile(args.provenance) as archive:
        sections = hub_section([r["year"] for r in receipts]) + location_section(archive, receipts)
    (ROOT / "results/KEY_METRICS.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
