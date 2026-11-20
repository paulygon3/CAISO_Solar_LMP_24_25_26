# CAISO solar-weighted price report

Day-ahead trading hubs and pricing locations · Full years 2024–2025 and 2026 through November 18 · Pacific delivery dates

**The gap between northern and southern solar prices narrowed.** Over January 1–November 18, the NP15 solar-weighted price exceeded SP15 by \$17.21/MWh in 2024 and \$8.67/MWh in 2026. Each hub uses its own zonal solar profile.

## Trading hub results

Prices are in USD per megawatt-hour. The all-hours price gives every delivery hour equal weight. The solar price gives more weight to hours with greater modeled solar output.

| Period · hub | All-hours price | Solar price | Capture rate | Negative hours | Solar at negative prices |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2024 · NP15 | 40.67 | 27.89 | 68.6% | 271 | 9.0% |
| 2024 · ZP26 | 32.09 | 11.00 | 34.3% | 1,151 | 33.3% |
| 2024 · SP15 | 32.68 | 10.88 | 33.3% | 1,169 | 34.9% |
| 2025 · NP15 | 38.23 | 26.40 | 69.0% | 288 | 8.7% |
| 2025 · ZP26 | 32.50 | 14.11 | 43.4% | 952 | 26.5% |
| 2025 · SP15 | 32.22 | 14.07 | 43.7% | 976 | 28.2% |
| 2026 YTD · NP15 | 32.84 | 23.08 | 70.3% | 385 | 12.5% |
| 2026 YTD · ZP26 | 28.99 | 14.87 | 51.3% | 974 | 31.1% |
| 2026 YTD · SP15 | 29.14 | 14.41 | 49.4% | 1,022 | 33.5% |

**Capture rate** is the solar price divided by the all-hours price. **Solar at negative prices** is the share of modeled generation during hours with a price below zero. Each hub had a published price in every hour.

## How the hubs compare on the same dates

| January 1–November 18 | NP15 solar price | ZP26 solar price | SP15 solar price | NP15 minus SP15 |
| --- | ---: | ---: | ---: | ---: |
| 2024 | 27.07 | 10.21 | 9.86 | 17.21 |
| 2025 | 25.76 | 12.95 | 12.97 | 12.79 |
| 2026 | 23.08 | 14.87 | 14.41 | 8.67 |

All four columns are in USD/MWh. The 2024 window includes February 29. These hub differences reflect both prices and solar timing. The workbooks also provide node-to-hub basis with identical weights on both prices.

## Market coverage and negative prices

| Period | Delivery hours | IDs with a price | Valid hourly prices | Price coverage | Eligible nodes |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | 8,784 | 16,972 | 145,007,605 | 82.3% | 6,059 |
| 2025 | 8,760 | 17,359 | 147,528,931 | 84.0% | 6,155 |
| 2026 YTD | 7,728 | 19,578 | 96,644,384 | 62.4% | 5,672 |

**Price coverage** uses all 20,048 historical IDs times the delivery hours in that period. **Eligible nodes** have a supported zone assignment and prices for at least 90% of their modeled solar output. The three reference hubs are counted separately from eligible nodes.

| Period | Negative hours, all IDs | Zero hours, all IDs | Negative hours, eligible nodes | Solar at negative prices, eligible nodes |
| --- | ---: | ---: | ---: | ---: |
| 2024 | 7.4% | 2.1% | 8.2% | 22.0% |
| 2025 | 5.7% | 1.9% | 7.3% | 18.1% |
| 2026 YTD | 8.4% | 3.3% | 9.2% | 22.2% |

The first three percentages count priced node-hours. The last pools matched modeled output across eligible nodes. For 2026 YTD, negative prices occurred during 9.2% of those nodes’ priced hours and coincided with 22.2% of their matched modeled solar output.

## Prices across the same 5,332 nodes

Median node-level solar price, USD/MWh. Each column uses January 1–November 18. Each node counts once and keeps the same zone in all three years, with at least 90% coverage of both hours and modeled solar output in each window.

| Zone | Nodes | 2024 | 2025 | 2026 |
| --- | ---: | ---: | ---: | ---: |
| NP15 | 2,684 | 32.11 | 28.87 | 24.69 |
| ZP26 | 472 | 10.95 | 14.22 | 16.30 |
| SP15 | 2,176 | 12.86 | 17.32 | 19.18 |

## Sources and confidence

CAISO OASIS published the hourly day-ahead prices. Separate named-hub downloads verified all three hub price histories. The study weights prices with PVWatts V8 modeled output from two equally weighted sites per zone under typical weather. Actual plant revenue depends on delivered generation and settlement terms.

Dated CAISO memberships support direct node assignments. Some zones are inferred from other market records. For 2026 YTD, 14,346 IDs had unresolved assignments and 27 had conflicting evidence. Raw prices remain available for those IDs wherever CAISO published them.

[Verified hub results](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/blob/main/results/verified_hub_periods.csv) · [Coverage and validation](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/blob/main/results/RUN_REPORT.md) · [Node results and provenance](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/releases/download/annual-workbooks-v1/CAISO_provenance.zip) · [Solar model inputs](https://github.com/paulygon3/CAISO_Solar_LMP_24_25_26/blob/main/inputs/pvwatts_sources.json)
