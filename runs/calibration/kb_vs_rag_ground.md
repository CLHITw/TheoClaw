# Groundedness (simplified, modelled on RAGAS faithfulness and FActScore), evaluator `deepseek-flash`

| arm | answers | faithfulness | fact recall | context recall | relevance (0–10) | unsupported statements |
|---|---|---|---|---|---|---|
| 20261016-000341_deepseek-flash_plain-account.en.deepseek-flash_kbvsrag-rag | 24 | 88% | 92% | 94% | 9.5 | 30 |
| 20261016-000125_deepseek-flash_plain-account.en.deepseek-flash_kbvsrag-kb | 24 | 87% | 81% | 85% | 9.0 | 31 |

By category (fact recall / faithfulness):

| category | 20261016-000341_deepseek-flash_plain-account.en.deepseek-flash_kbvsrag-rag | 20261016-000125_deepseek-flash_plain-account.en.deepseek-flash_kbvsrag-kb |
|---|---|---|
| lookup | 100% / 82% | 98% / 92% |
| pastoral | 50% / 92% | 75% / 93% |
| synthesis | 93% / 92% | 72% / 88% |
| trap | 100% / 70% | 100% / 65% |

Difference 20261016-000125_deepseek-flash_plain-account.en.deepseek-flash_kbvsrag-kb − 20261016-000341_deepseek-flash_plain-account.en.deepseek-flash_kbvsrag-rag, paired over tasks, 95% bootstrap interval:

| metric | difference | 95% interval |
|---|---|---|
| faithfulness | -0.6 pp | [-5.5 pp, +4.1 pp] |
| fact_recall | -11.1 pp | [-24.4 pp, +0.5 pp] |
| context_recall | -9.2 pp | [-20.0 pp, +0.8 pp] |
| relevance | -0.50 | [-1.29, +0.00] |
