# How far to trust the LLM judges (reference rater: `claude`)

## Agreement with the reference rater

| judge | run | answers | verdict agreement | kappa | judge says usable / reference | mean score: judge / reference | judge − reference |
|---|---|---|---|---|---|---|---|
| judge-deepseek-flash | 20261009-101326_deepseek-flash | 135 | 84% | 0.00 | 84% / 100% | 4.81 / 4.85 | -0.04 |
| judge-deepseek-flash | 20261009-101342_qwen3.8-max | 135 | 82% | -0.04 | 84% / 98% | 4.83 / 4.82 | +0.01 |
| judge-qwen3.8-max | 20261009-101326_deepseek-flash | 135 | 68% | 0.00 | 68% / 100% | 4.54 / 4.85 | -0.31 |
| judge-qwen3.8-max | 20261009-101342_qwen3.8-max | 135 | 71% | -0.04 | 73% / 98% | 4.60 / 4.82 | -0.22 |

Self-preference shows as a judge whose gap (judge − reference) is larger on its own model's run than on the other run.

## Length

Correlation between answer length and the judge's excess score (judge − reference); positive means the judge rewards length that the reference rater did not.

| judge | answers | correlation |
|---|---|---|
| judge-deepseek-flash | 270 | +0.36 |
| judge-qwen3.8-max | 270 | +0.16 |

## Pairwise comparisons, both orders

| file | pairs judged both ways | same winner both ways | first position wins | a wins | b wins | ties |
|---|---|---|---|---|---|---|
| pairs_20261009-101342_qwen3.8-max__20261009-101326_deepseek-flash__judge-qwen3.8-max | 51 | 80% | 52% | 62 | 40 | 0 |

Without position bias, 'same winner both ways' is high and 'first position wins' is near 50% (apart from ties).

Length or self-preference? Judgments split by which answer was longer:

| file | judgments | longer answer wins | a wins when a is longer | a wins when b is longer |
|---|---|---|---|---|
| pairs_20261009-101342_qwen3.8-max__20261009-101326_deepseek-flash__judge-qwen3.8-max | 102 | 65% | 67% (76) | 42% (26) |

If 'a' keeps winning even when b is longer, that is preference for a's model, not for length.