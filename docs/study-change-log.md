# Study change log

The original scope and the additional analytical requirements are preserved in this directory. The table records decisions made during the production study. Git history retains the implementation details. The final year receipts identify the exact code commit and the SHA-256 digests of the analysis specification, price configuration, model profile and sealed workbook.

| Commit | Decision and reason | Affected data and outputs |
|---|---|---|
| `1688b81` | Froze the study specification after official downloads began and before production annual calculations. The user added a gap register, repair protocol, cross-year cohort and component attribution. | Quality-assessment, analytical and delivery layers |
| `bb0e672` | Reconstructed all calendar-aligned solar weights from the six original site outputs. Added period diagnostics, gap exposure, mutually eligible cohort selection and matched component differences. | Model audit, gap files, summary tables and report |
| `ef8d693` | A real-data integration test exposed archive-handle shadowing in the added written attribution check. Corrected the reader and reopened the existing candidate. | Written-file verification |
| `fea6e11` | An internally missing price can be investigated separately from a location’s entry or exit. Added named-node OASIS requests with a fully priced hub control and a source-preserving recovery layer. | Population, observed support and any recovered price-dependent result |
| `ee87e03` | Explicitly flag mutually exclusive internal path-region memberships and record quarterly scale and readback results. | Zone status and calculations requiring an accepted zone |
| `13ad26d` | Block affected estimates when total-price records conflict or component reconciliation fails. Added independent reconstruction of matched windows from disjoint month segments. | Primary price, display, component and basis fields, calculation validation |
| `f827300` | Compare reference-hub period results with the independent named-hub scalar analysis as a second implementation check. | Annual, monthly and matched hub QA |
| `f22e976`, `8856657` | A truncated August 2025 transfer exposed a missing transport exception handler. Added retries, checkpoints and a verified independent follow-up for the affected date. | Retrieval QA, restart behavior and source provenance |
| `8ff4459` | Stage large sealed Excel files in a private draft of the public repository release so all three can be checked together before publication. | File transport, checksums and public release |
