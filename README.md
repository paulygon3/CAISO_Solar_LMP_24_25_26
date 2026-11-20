# CAISO hourly zonal solar-weighted LMP

This repository calculates day-ahead solar-weighted prices and node-to-hub basis for the union of CAISO OASIS pricing locations from January 1, 2024 through November 18, 2026. The calendar uses Pacific delivery dates. Each of NP15, ZP26 and SP15 has a fixed, two-location modeled solar profile.

[Follow the production run](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/actions) · [Releases and downloads](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases) · [Monthly source archives](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/tag/market-inputs-v1)

## Files and publication

The **annual-workbooks-v1** release is created after all three production files pass readback. Each year is a self-contained Excel file with the full historical node inventory, hourly raw and weighted matrices, monthly and annual results, matched-calendar comparisons, all three hub comparisons, data issues, and method and validation tables. The 2026 file stops on November 18. The accompanying run report gives coverage, mapping, classifications, file sizes and checksums. The provenance ZIP contains per-year analysis tables, detailed gap records, the balanced-node comparison and retrieval diagnostics.

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
