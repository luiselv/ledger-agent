# Evaluation results

_20 labeled synthetic invoices · generated 2026-08-08 05:40 UTC · temperature 0_

## Comparison

| config | posted | 1st-try post | exact match | macro F1 | mean iters | tokens |
|---|---|---|---|---|---|---|
| haiku, no validator | 100% | 100% | 95% | 0.972 | 2.00 | 79,309 |
| haiku, with validator | 100% | 100% | 95% | 0.972 | 2.95 | 151,248 |
| sonnet, no validator | 100% | 100% | 90% | 0.944 | 2.00 | 78,873 |
| sonnet, with validator | 100% | 100% | 95% | 0.972 | 2.05 | 100,828 |

**Reading this table.** `posted` is the share of invoices that produced an entry the ledger accepted. `1st-try post` is the share that got there without a rejected attempt first — the number that actually varies, since a posted entry balances by construction. `exact match` is the share whose entry used exactly the expected set of accounts, the strict measure: one spurious line fails the case. `macro F1` averages per-account F1 across accounts that appear in the labels, so a rare account counts as much as a common one.

## Per-configuration detail

### haiku, no validator  (`claude-haiku-4-5-20251001`)

- cases: 20  (errored: 0)
- posted a valid entry: 100%
- posted on the first attempt: 100%
- exact account match: 95%
- macro F1 over accounts: 0.972
- mean iterations: 2.00
- mean validation calls: 0.00
- total tokens: 79,309

| account | precision | recall | F1 | support |
|---|---|---|---|---|
| 1400 | 1.00 | 1.00 | 1.00 | 2 |
| 1500 | 1.00 | 1.00 | 1.00 | 2 |
| 2010 | 1.00 | 1.00 | 1.00 | 20 |
| 2200 | 1.00 | 1.00 | 1.00 | 7 |
| 5010 | 1.00 | 1.00 | 1.00 | 1 |
| 6010 | 1.00 | 1.00 | 1.00 | 4 |
| 6020 | 1.00 | 1.00 | 1.00 | 4 |
| 6030 | 1.00 | 1.00 | 1.00 | 2 |
| 6040 | 1.00 | 0.50 | 0.67 | 2 |
| 6050 | 1.00 | 1.00 | 1.00 | 2 |
| 6060 | 1.00 | 1.00 | 1.00 | 2 |
| 6070 | 1.00 | 1.00 | 1.00 | 2 |

<details><summary>Cases that did not match exactly</summary>

- `case_013_mixed_equipment_and_supplies`: missing ['6040'], spurious -

</details>

### haiku, with validator  (`claude-haiku-4-5-20251001`)

- cases: 20  (errored: 0)
- posted a valid entry: 100%
- posted on the first attempt: 100%
- exact account match: 95%
- macro F1 over accounts: 0.972
- mean iterations: 2.95
- mean validation calls: 1.00
- total tokens: 151,248

| account | precision | recall | F1 | support |
|---|---|---|---|---|
| 1400 | 1.00 | 1.00 | 1.00 | 2 |
| 1500 | 1.00 | 1.00 | 1.00 | 2 |
| 2010 | 1.00 | 1.00 | 1.00 | 20 |
| 2200 | 1.00 | 1.00 | 1.00 | 7 |
| 5010 | 1.00 | 1.00 | 1.00 | 1 |
| 6010 | 1.00 | 1.00 | 1.00 | 4 |
| 6020 | 1.00 | 1.00 | 1.00 | 4 |
| 6030 | 1.00 | 1.00 | 1.00 | 2 |
| 6040 | 1.00 | 0.50 | 0.67 | 2 |
| 6050 | 1.00 | 1.00 | 1.00 | 2 |
| 6060 | 1.00 | 1.00 | 1.00 | 2 |
| 6070 | 1.00 | 1.00 | 1.00 | 2 |

<details><summary>Cases that did not match exactly</summary>

- `case_013_mixed_equipment_and_supplies`: missing ['6040'], spurious -

</details>

### sonnet, no validator  (`claude-sonnet-4-5-20250929`)

- cases: 20  (errored: 0)
- posted a valid entry: 100%
- posted on the first attempt: 100%
- exact account match: 90%
- macro F1 over accounts: 0.944
- mean iterations: 2.00
- mean validation calls: 0.00
- total tokens: 78,873

| account | precision | recall | F1 | support |
|---|---|---|---|---|
| 1400 | 0.67 | 1.00 | 0.80 | 2 |
| 1500 | 1.00 | 1.00 | 1.00 | 2 |
| 2010 | 1.00 | 1.00 | 1.00 | 20 |
| 2200 | 1.00 | 1.00 | 1.00 | 7 |
| 5010 | 1.00 | 1.00 | 1.00 | 1 |
| 6010 | 1.00 | 0.75 | 0.86 | 4 |
| 6020 | 1.00 | 1.00 | 1.00 | 4 |
| 6030 | 1.00 | 1.00 | 1.00 | 2 |
| 6040 | 1.00 | 0.50 | 0.67 | 2 |
| 6050 | 1.00 | 1.00 | 1.00 | 2 |
| 6060 | 1.00 | 1.00 | 1.00 | 2 |
| 6070 | 1.00 | 1.00 | 1.00 | 2 |

<details><summary>Cases that did not match exactly</summary>

- `case_005_mixed_software_and_consulting`: missing ['6010'], spurious ['1400']
- `case_013_mixed_equipment_and_supplies`: missing ['6040'], spurious -

</details>

### sonnet, with validator  (`claude-sonnet-4-5-20250929`)

- cases: 20  (errored: 0)
- posted a valid entry: 100%
- posted on the first attempt: 100%
- exact account match: 95%
- macro F1 over accounts: 0.972
- mean iterations: 2.05
- mean validation calls: 0.05
- total tokens: 100,828

| account | precision | recall | F1 | support |
|---|---|---|---|---|
| 1400 | 1.00 | 1.00 | 1.00 | 2 |
| 1500 | 1.00 | 1.00 | 1.00 | 2 |
| 2010 | 1.00 | 1.00 | 1.00 | 20 |
| 2200 | 1.00 | 1.00 | 1.00 | 7 |
| 5010 | 1.00 | 1.00 | 1.00 | 1 |
| 6010 | 1.00 | 1.00 | 1.00 | 4 |
| 6020 | 1.00 | 1.00 | 1.00 | 4 |
| 6030 | 1.00 | 1.00 | 1.00 | 2 |
| 6040 | 1.00 | 0.50 | 0.67 | 2 |
| 6050 | 1.00 | 1.00 | 1.00 | 2 |
| 6060 | 1.00 | 1.00 | 1.00 | 2 |
| 6070 | 1.00 | 1.00 | 1.00 | 2 |

<details><summary>Cases that did not match exactly</summary>

- `case_013_mixed_equipment_and_supplies`: missing ['6040'], spurious -

</details>
