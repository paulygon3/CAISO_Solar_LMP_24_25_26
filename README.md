# CAISO hourly zonal solar-weighted LMP

This repository calculates day-ahead solar-weighted prices and node-to-hub basis for the union of CAISO OASIS pricing locations from January 1, 2024 through November 18, 2026. The calendar uses Pacific delivery dates. Each of NP15, ZP26 and SP15 has a fixed, two-location modeled solar profile.

**Key metrics report** · [Read online](results/KEY_METRICS.md) · [Download the two-page PDF](https://raw.githubusercontent.com/paulygon3/CAISO_Solar_LMP_24_25_26/main/results/CAISO_Key_Metrics.pdf)

The report compares hub prices, solar capture rates, negative-price exposure and the same 5,332 pricing locations across three years. To regenerate the tables, download the release’s `CAISO_provenance.zip`, install the repository requirements and run `python src/key_metrics_report.py /path/to/CAISO_provenance.zip`.

## Find the zone for a pricing node

[Download the annual node-to-zone lookup (CSV)](https://raw.githubusercontent.com/paulygon3/CAISO_Solar_LMP_24_25_26/main/results/node_zones_by_year.csv) · [Download dated assignments and evidence (CSV)](https://raw.githubusercontent.com/paulygon3/CAISO_Solar_LMP_24_25_26/main/results/node_zone_history.csv)

Search the annual lookup for the exact `node_id`. It covers all 20,048 historical pricing IDs, including aggregate locations. Each reporting year has a zone and an evidence status. The 2026 window ends November 18. For a particular delivery hour, filter the dated file by the same ID and select the interval containing that hour. The start is inclusive and the end is exclusive, both in UTC.

| Status | What it means |
| --- | --- |
| DIRECT | The exact node appears in a dated CAISO trading-hub membership record, or the ID is the named reference hub itself. |
| INFERRED | Two internal CAISO ancillary-service regions place the node on the corresponding sides of Paths 15 and 26, or all nonzero load-distribution members of an aggregate resolve to one zone and the distribution factors account for the aggregate. |
| CONFLICTING | The evidence disagrees. The lookup leaves the zone blank. |
| UNRESOLVED | The study lacks sufficient evidence for part or all of the interval being summarized. The dated file can still contain supported intervals for an unresolved year. |
| OUTSIDE_THREE_ZONE_SCOPE | A dated record places the node in another published trading hub. |

Use DIRECT for confirmed hub membership. Use the dated assignments for a year marked VARIES. CAISO publishes trading-hub membership for a subset of pricing nodes. The study's inferred zones extend coverage for regional comparisons. Their accuracy has no independently measured percentage. Download the three released workbooks into `output/` and run `python src/node_zone_lookup.py` to reproduce both lookups. [CAISO membership file for May 2026 (ZIP)](https://oasis.caiso.com/oasisapi/SingleZip?queryname=ATL_PNODE_MAP&version=1&pnode_id=ALL&resultformat=6&startdatetime=20260501T07:00-0000&enddatetime=20260529T07:00-0000) · [Mapping rules and source limitations](DATA_CLEANING_AND_LESSONS.md)

## Download the workbooks

The completed release covers 25,272 Pacific delivery hours and 389,180,920 published prices. All three files passed written-workbook validation. Each download is a self-contained Excel file with 93 worksheets and the same 20,048 pricing locations.

| Workbook | Coverage | Observed prices | Size |
|---|---|---:|---:|
| [2024 Excel workbook](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/download/annual-workbooks-v1/CAISO_Solar_Weighted_LMP_2024.xlsx) | January 1–December 31 | 145,007,605 | 1.38 GB |
| [2025 Excel workbook](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/download/annual-workbooks-v1/CAISO_Solar_Weighted_LMP_2025.xlsx) | January 1–December 31 | 147,528,931 | 1.38 GB |
| [2026 Excel workbook](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/download/annual-workbooks-v1/CAISO_Solar_Weighted_LMP_2026.xlsx) | January 1–November 18 | 96,644,384 | 1.07 GB |

Start with **Node_Summary** for annual estimates or **Node_Dictionary** to locate a particular node’s hourly raw and weighted columns. Many historical locations lack a defensible zone for an entire reporting window. They remain in the workbook, with raw prices preserved and unsupported solar-weighted estimates blank. The matched-calendar balanced panel contains 5,332 nonreference locations.

[Read the results and coverage report](results/RUN_REPORT.md) · [Download the provenance, gap registers and balanced-node results](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/download/annual-workbooks-v1/CAISO_provenance.zip) · [View the successful build](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/actions/runs/44697262026)

## Files and publication

Each annual workbook includes hourly raw and weighted matrices, monthly and annual results, matched-calendar comparisons, all three hub comparisons, data issues and validation tables. The final report includes scope, mapping, classifications, file sizes and checksums. Machine-readable outcomes are in [completion.json](results/completion.json). All three public downloads were reopened and their SHA-256 checksums verified in the [published-file receipt](results/published_file_verification.json). The [release](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/tag/annual-workbooks-v1) contains exactly three Excel files and the supporting report and evidence archive.

The monthly-input release stores original CAISO archives and smaller checksummed analysis and reference packages. Each month publishes its completion manifest last. The original recovery checkpoint contains the six-day access pilot, raw model responses and independently obtained reference-hub data. [Download the checkpoint](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/download/checkpoint-v1/CAISO_resume.zip)

## Study design

The primary calculations use published hourly total LMP. A missing price remains blank. The scenario weights are PVWatts V8 hourly AC for six equally paired locations under fixed typical meteorological weather. The model has 100 MW equivalent AC capacity per location before the zonal average. UTC joins, local standard solar time, and February 29 handling are explicit. Each weighted estimate divides its observed price-times-weight sum by its matched weight-hours. Separate full calendar and solar denominators measure coverage. A retained estimate can remain below the project’s 90% threshold for display.

Reference memberships and their effective dates determine zone assignments. Inference, conflicts, unsupported classifications and source gaps carry separate flags. Basis uses the same node-zone weights and the same matched times for both prices. Component attribution is published only on complete, reconciled common support. [Frozen analysis specification](analysis_specification.json) · [Study change log](docs/study-change-log.md) · [Price and model configuration](config.json) · [Methods, limits and lessons](DATA_CLEANING_AND_LESSONS.md)

## Reproduce the study

Use Python 3.12, Git, the GitHub CLI and the Info-ZIP `zip` command. Install `requirements.txt`. The release workflow uses standard Ubuntu runners and archives month batches to conserve disk. Reading public CAISO and model data needs no paid subscription. A GitHub identity with repository write permission is needed for publication. For a clean checkout the following commands restore the exact source inputs and produce the three workbooks.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python src/pipeline.py restore
python src/pipeline.py inventory
python src/pipeline.py build --year 2024
python src/pipeline.py build --year 2025
python src/pipeline.py build --year 2026
python src/pipeline.py readback --year 2024
python src/pipeline.py readback --year 2025
python src/pipeline.py readback --year 2026
python src/pipeline.py documentation
```

`output/` holds exactly the three annual XLSX files. `staging/inventory/` holds the study population. `staging/support/` holds annual evidence, machine-readable gap registers, stage receipts, diagnostics and the final report. Readback reopens the specified file. Documentation refresh recalculates supporting reports from existing evidence and checks the sealed workbook hashes.

### Source refresh and failure recovery

- **Access and model preflight** — `python src/oasis.py pilot`, `python src/oasis.py reference`, and `python src/solar.py` recheck the official endpoint and model configuration. Model access can use the documented demo key or an environment-provided NLR key. Only the public model inputs are persisted. A refreshed compressed profile has its own output hash. Review a change to the frozen inputs before running a different study version.
- **Download and canonicalization** — `python src/acquire.py --release market-inputs-v1 --cleanup` validates cached daily inputs, reconciles source keys and resumes at completed months. `python src/zone_references.py --release market-inputs-v1` retrieves the dated regional and resource evidence. The Actions workflows include the verified recovery checkpoint. Raw price inputs use one trading date per all-location request.
- **Restore one year** — `python src/pipeline.py restore --year 2025` restores only its analysis and reference archives. The inventory stage checks internal gaps against separate named-node official requests with a positive-control hub. Newly recovered published prices are stored apart from original canonical data. The price-ID inventory still covers the entire study. The three annual assembly jobs can use the same verified global inventory independently.
- **Inspect an existing file** — `python src/pipeline.py readback --year 2025 --file /path/to/book.xlsx` checks the actual file against restored source data and the historical inventory. `python src/pipeline.py diagnostics` summarizes available retrieval logs without touching Excel.
- **Run through GitHub** — select **Actions → Acquire official CAISO market inputs** for a source run. The annual build starts after acquisition succeeds. A manual production run can also start from **Build and validate annual CAISO workbooks → Run workflow** with the integration-only option off. That option runs a separate two-day real-data validation.

[Original task](docs/task.txt) · [Added analytical requirements](docs/study-request.txt) · [Pilot reproduction](docs/checkpoint.txt) · [Reference-hub pilot results](results/verified_hub_periods.csv)
