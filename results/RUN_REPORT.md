# CAISO day-ahead solar-weighted prices

**COMPLETE**. Pacific delivery from January 1, 2024 through November 18, 2026. Each workbook retains the same 20,048 historical price identifiers, including the three named reference hubs.

| Year | First and last observed delivery date | Hours | Nonmissing node-hour prices | Sheets | File size (MiB) |
|---|---|---:|---:|---:|---:|
| 2024 | 2024-01-01 to 2024-12-31 | 8,784 | 145,007,605 | 93 | 1,318.9 |
| 2025 | 2025-01-01 to 2025-12-31 | 8,760 | 147,528,931 | 93 | 1,319.6 |
| 2026 | 2026-01-01 to 2026-11-18 | 7,728 | 96,644,384 | 93 | 1,024.7 |

## Effective mapping across each reporting window

| Category | 2024 | 2025 | 2026 YTD |
|---|---:|---:|---:|
| CONFLICTING | 26 | 27 | 27 |
| DIRECT | 1,760 | 1,858 | 1,889 |
| INFERRED | 4,302 | 4,300 | 3,786 |
| UNRESOLVED | 13,960 | 13,863 | 14,346 |
| OUTSIDE_THREE_ZONE_SCOPE for the entire reporting window | 0 | 0 | 0 |

## Dated node classifications

| Category | 2024 | 2025 | 2026 YTD |
|---|---:|---:|---:|
| APNODE | 2,393 | 2,391 | 1,874 |
| PNODE | 15,435 | 15,867 | 16,240 |
| UNKNOWN | 1,286 | 845 | 484 |
| VARIES (see Node_Zone_History) | 934 | 945 | 1,450 |

## Coverage and display layers

| Category | 2024 | 2025 | 2026 YTD |
|---|---:|---:|---:|
| HEATMAP | 6,059 | 6,155 | 5,672 |
| REFERENCE | 3 | 3 | 3 |
| UNMAPPED | 13,986 | 13,890 | 14,373 |
| LOW_COVERAGE | 0 | 0 | 0 |
| NO_ESTIMATE | 0 | 0 | 0 |

## Source coverage and readback

There were 0 missing market-wide hourly intervals and 0 quarantined conflicting source keys across the period. Exact intervals are recorded in the annual readback JSON and Daily_Source_QA.

Price retrievals span 2026-11-20T02:35:47.529810+00:00 through 2026-11-20T07:14:23.684418+00:00. The retrieval summary records cache hits, successful attempts and transport errors from the archived acquisition logs.

Each archive passed CRC validation and reopened with openpyxl. Following publication, all three files were downloaded from the public release, checked against their sealed SHA-256 digests, tested for ZIP integrity and reopened. The results are in [published_file_verification.json](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/blob/main/results/published_file_verification.json). The validator checked every matrix header, timestamp, nonmissing-cell total, dictionary address, summary key and display field. At the following sample sizes it compared individual raw prices and weighted numerators with dated canonical prices and mapping evidence.

- 2024 covered 280,672 raw and 280,672 weighted positions at 14 UTC timestamps. SHA-256 `1ac6f353881cada70cd09e213e3c8b57edc9344c3e34914b03a6a6d8f406e0cb`.
- 2025 covered 240,576 raw and 240,576 weighted positions at 12 UTC timestamps. SHA-256 `cfe102df8f62e55b2a0b50f65a8bd9d73854a3afe7dd13d11f4ebbc9a3596df0`.
- 2026 covered 200,480 raw and 200,480 weighted positions at 10 UTC timestamps. SHA-256 `1c05597c49f13f19ca558ec8a97176d0bbf6274ad6da1eaefb50e70dfe4afc78`.

The archived request logs contain 1,945 successful downloads, 11 validated cache hits and 37 failed attempts. Per-run errors and request keys are in retrieval-summary.json.

The final inventory used 169 named-node requests to check internal gaps in the all-location data. The request-log totals above include that inventory stage. An earlier, superseded inventory run completed 235 named checks before the verified batch size was increased. Those earlier checks are recorded separately in results/recovery_batch_preflight.json. They recovered 0 additional published hourly prices. The original all-location rows and named-source archives are preserved separately.

## Price availability and component exceptions

The annual files have 16,972, 17,359 and 19,578 locations with at least one observed price in 2024, 2025 and 2026 YTD, respectively. Each file still includes all 20,048 historical identifiers. The number of locations with a published price fell 46.47% on May 1, 2026. This figure measures a change in published coverage. The source data alone do not establish individual retirements or a common physical cause.

Component reconciliation exceeded the project's $0.00005/MWh numerical review threshold on 1,659 node-hours in 2024, 242 in 2025 and 784 in 2026 YTD. Published total prices were retained. The analytical tables flag the affected component results and protect node-to-hub attribution. The underlying records, common support counts and residual magnitudes are available in the source manifests and workbooks.

## Balanced-node comparison and coverage

5,332 nonreference locations held the same assigned zone and met both 90% coverage thresholds in all three January 1–November 18 periods. The per-node estimates are in balanced_node_matched_period.parquet. population_comparison.csv gives within-zone cross-node quantiles for full-year/YTD, matched-calendar and balanced populations.

- In 2024, Pacific hour 01 had the largest share of internally observable node-hours missing, 9,683 of 6,068,296 (0.160%). The gap-clustering tables also break out month, source batch, market regime, node type, zone and source market area.
- In 2025, Pacific hour 01 had the largest share of internally observable node-hours missing, 16,379 of 6,180,362 (0.265%). The gap-clustering tables also break out month, source batch, market regime, node type, zone and source market area.
- In 2026, Pacific hour 02 had the largest share of internally observable node-hours missing, 73,144 of 4,083,146 (1.791%). The gap-clustering tables also break out month, source batch, market regime, node type, zone and source market area.

## Observed, modeled and inferred

Hourly prices and components are published CAISO observations. All six site TMY AC series were complete. The three weighted zonal profiles are modeled, with zero statistical repairs. The 24 hours of February 29, 2024 use the prespecified calendar rule. Numerical results and heatmap eligibility are calculated. Dated inferred classifications and unresolved IDs are recorded separately.

Prices use official DAM OASIS data. The six-site, three-zone PVWatts scenario represents fixed typical weather. Effective membership differences, unsupported mappings and incomplete price coverage have separate fields. Missing prices remain blank. Direct and inferred mapping details, external locations, component tests and prior pilot issues are documented in each workbook and the repository lessons.

[Source archives](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/tag/market-inputs-v1) · [Source code and refresh instructions](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26)
