# Decision: replace `20261009-101342_qwen3.8-max` with `20261009-101326_deepseek-flash`?

Rule (fixed before looking): switch if the candidate is cheaper or faster (interval below 0) and every quality metric is better or not worse by more than its margin. Human scores: rater `claude`.

| metric | current | candidate | difference [95% interval] | margin | verdict |
|---|---|---|---|---|---|
| human mean score (1-5) | 4.82 | 4.85 | +0.03 [-0.04, +0.09] | 0.2 | not worse |
| human: usable as is | 97.8% | 100.0% | +2.2 pp [0.0 pp, +7.4 pp] | 5 pp | not worse |
| human: answer with a clear flaw | 11.1% | 5.9% | -5.2 pp [-12.6 pp, +2.2 pp] | 5 pp | not worse |
| rule graders pass | 88.9% | 91.9% | +3.0 pp [-6.7 pp, +12.6 pp] | 5 pp | unclear |
| cost per answer (USD) | $0.0248 | $0.0051 | -0.0197 [-0.0241, -0.0154] | – | better |
| time per answer (s) | 594.0 | 22.9 | -571.1 [-1676.4, -67.8] | – | better |

27 tasks; answers per arm 135 / 135. Two-stage bootstrap: tasks resampled, then runs within each task.

**Decision: do not switch yet (not enough evidence).**

## When would the evidence have been enough?

| runs per task used | decision | human mean score (1-5) | human: usable as is | human: answer with a clear flaw | rule graders pass |
|---|---|---|---|---|---|
| 1 | wait | not worse | not worse | not worse | unclear |
| 2 | wait | not worse | not worse | unclear | unclear |
| 3 | wait | not worse | not worse | unclear | unclear |
| 4 | wait | not worse | not worse | not worse | unclear |
| 5 | wait | not worse | not worse | not worse | unclear |

First number of runs from which the decision stays 'switch': none.

## Planning the next comparison

Share of simulated comparisons that would show non-inferiority, if the two arms differ as they did here (tasks resampled from these ones; answers from each task's observed answers):

**human mean score (1-5)**, margin 0.2

| tasks \ runs | 1 | 3 | 5 | 10 |
|---|---|---|---|---|
| 27 | 99% | 100% | 100% | 100% |
| 54 | 100% | 100% | 100% | 100% |
| 108 | 100% | 100% | 100% | 100% |

**human: usable as is**, margin 5 pp

| tasks \ runs | 1 | 3 | 5 | 10 |
|---|---|---|---|---|
| 27 | 100% | 100% | 100% | 100% |
| 54 | 100% | 100% | 100% | 100% |
| 108 | 100% | 100% | 100% | 100% |

**human: answer with a clear flaw**, margin 5 pp

| tasks \ runs | 1 | 3 | 5 | 10 |
|---|---|---|---|---|
| 27 | 41% | 64% | 76% | 90% |
| 54 | 51% | 91% | 98% | 100% |
| 108 | 83% | 100% | 100% | 100% |

**rule graders pass**, margin 5 pp

| tasks \ runs | 1 | 3 | 5 | 10 |
|---|---|---|---|---|
| 27 | 23% | 32% | 40% | 52% |
| 54 | 29% | 54% | 63% | 73% |
| 108 | 53% | 82% | 88% | 94% |

Caveats: the human metrics are only as good as the rater (one rater here unless stated); tasks are not a random sample of real questions, so the interval covers this task set, not all use.