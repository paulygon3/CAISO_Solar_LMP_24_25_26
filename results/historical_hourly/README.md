# Historical hourly solar generation and day-ahead hub prices

[Download the hourly CSV](https://raw.githubusercontent.com/paulygon3/CAISO_Solar_LMP_24_25_26/main/results/historical_hourly/hourly_solar_and_hub_prices.csv) · [Download the monthly and annual hub results](https://raw.githubusercontent.com/paulygon3/CAISO_Solar_LMP_24_25_26/main/results/historical_hourly/hub_periods.csv)

The file has one row for each of 25,272 Pacific delivery hours from 2024-01-01 through 2026-11-18. CAISO OASIS supplied 75,810 of 75,816 hourly solar readings across NP15, ZP26 and SP15 and all 75,816 day-ahead hub prices. Blank production cells identify missing published readings. A numeric zero is an observed value. [Missing hours](missing_hours.csv)

## How to read an hour

UTC start and end identify the exact one-hour delivery interval. The Pacific start includes the offset so the repeated fall hour remains identifiable. Each zone has three columns.

| Column ending | Meaning |
| --- | --- |
| actual_solar_mw | CAISO-reported average solar power for the hour, in MW, for the trading hub's reporting resources. All signed values are preserved. |
| positive_export_mwh | Positive hourly production used as the weight, in MWh. For these one-hour intervals this equals the larger of reported MW and zero. Missing production remains blank. |
| day_ahead_lmp_usd_per_mwh | Published total day-ahead price for that generation trading hub, in USD/MWh. |

## Day-ahead prices weighted by reported positive solar production

| Pacific delivery period | NP15 ($/MWh) | ZP26 ($/MWh) | SP15 ($/MWh) | Solar hours observed per zone |
| --- | ---: | ---: | ---: | --- |
| 2024 | 28.95 | 11.65 | 12.04 | 8,782/8,784 |
| 2025 | 27.31 | 14.80 | 13.88 | 8,760/8,760 |
| 2026 through Nov 18 | 23.22 | 16.04 | 15.04 | 7,728/7,728 |

Each price equals the sum of hourly price times positive exported MWh divided by observed positive exported MWh. The period CSV also gives the alternative signed-net result, which includes negative reported MW. Both calculations use only observed price and production pairs. A missing hour leaves its generation and value unknown. The JAN01_NOV18 rows in the period CSV compare the same calendar dates each year.

A hub price applies the area's reported production to its day-ahead hub LMP. A plant's own hourly production and settlement prices determine its realized revenue. For a node-level benchmark, match the node's dated zone and UTC delivery hour, then apply that zone's generation weights to the node's own price. [Dated node-zone mapping](../node_zone_history.csv)

## Data and checks

The solar series comes from OASIS SLD_REN_FCST v1, market run ACTUAL, renewable type Solar, data item RENEW_FCST_ACT_MW. The requests specify the trading-hub and renewable-type filters. CAISO describes this report as covering eligible intermittent resources. The price series comes from the OASIS PRC_LMP day-ahead total LMP for each named hub. The original annual workbooks use the separate PVWatts typical-weather scenario. [CAISO OASIS API FAQ, question 7](https://www.caiso.com/documents/oasis-frequently-asked-questions.pdf) · [Original solar responses and dated request URLs](../../inputs/historical_solar_actuals_oasis.zip) · [Hub price source receipts](../../inputs/independent_hubs.json)

Overlapping requests cover the calendar boundaries and provide repeated observations to check for disagreements. Named-hub requests check missing intervals. Every UTC hour in the saved CSV, its reported solar MW, its signed-to-positive conversion and its day-ahead price were checked against the source inputs. [Validation totals](source_check.json)

To rebuild the files from the bundled inputs, install the repository requirements and run `python src/historical_solar.py`. To retrieve fresh OASIS data, first run `python src/solar_actuals_source.py`, then `python src/historical_solar.py`. If the gap list contains records, run `python src/solar_actuals_source.py --gap-file results/historical_hourly/missing_hours.csv` and rebuild.
