# Eval report: deepseek-flash

- started 20261016-000341 · 12 tasks × n=2 runs · effort=None
- tools: scripture, rag · knowledge base plain-account.en.deepseek-flash (wiki 2a76ed541c62; compiled by deepseek/deepseek-flash, language en, compile cost $0.11)
- task set sha 22c8c4045697 · system prompt sha 32e133929fd5 · tools sha f44f38946673
- run outcomes: {'completed': 24} · grading: {'pass': 23, 'fail': 1}
- latency per run p50 38.0s · p95 60.9s · total cost $0.27
- tokens per run: prompt 59,835 (cache read 43,947) · output 5,342 · tool output 60,248 chars
- answers where the model wrote Simplified characters: 6 (converted to 繁體 before grading: 6)

| slice | tasks | pass rate | pass@2 | pass^2 |
|---|---|---|---|---|
| all | 12 | 96% | 100% | 92% |
| no fault | 12 | 96% | 100% | 92% |
| fault injected | 0 | – | – | – |
| category: lookup | 3 | 100% | 100% | 100% |
| category: pastoral | 1 | 100% | 100% | 100% |
| category: synthesis | 7 | 100% | 100% | 100% |
| category: trap | 1 | 50% | 100% | 0% |

## Tool usage

| tool | calls | per run | errors |
|---|---|---|---|
| fill_quote | 92 | 3.8 | 0 |
| lookup_verse | 97 | 4.0 | 0 |
| rag_search | 184 | 7.7 | 1 |

## Per task

| task | category | fault | passes | pass^2 | tool calls | prompt tok | output tok | latency | cost |
|---|---|---|---|---|---|---|---|---|---|
| pa-bishop-gibson | lookup |  | 2/2 | 100% | 5.0 | 16,158 | 2,256 | 20.7s | $0.0050 |
| pa-can-lose | synthesis |  | 2/2 | 100% | 20.5 | 65,527 | 4,940 | 34.2s | $0.0124 |
| pa-definition-1767 | synthesis |  | 2/2 | 100% | 14.5 | 38,448 | 4,099 | 26.8s | $0.0095 |
| pa-early-reading | lookup |  | 2/2 | 100% | 9.0 | 36,971 | 5,457 | 42.8s | $0.0104 |
| pa-first-conference | lookup |  | 2/2 | 100% | 9.0 | 21,273 | 3,386 | 23.4s | $0.0062 |
| pa-instant-gradual | synthesis |  | 2/2 | 100% | 10.5 | 22,432 | 3,490 | 25.0s | $0.0066 |
| pa-need-christ | synthesis |  | 2/2 | 100% | 17.5 | 39,204 | 4,803 | 34.9s | $0.0091 |
| pa-not-perfect | synthesis |  | 2/2 | 100% | 16.0 | 72,950 | 7,272 | 51.9s | $0.0154 |
| pa-pastoral-objection | pastoral |  | 2/2 | 100% | 19.5 | 61,028 | 7,542 | 50.3s | $0.0148 |
| pa-sin-distinction | synthesis |  | 2/2 | 100% | 23.0 | 144,184 | 8,494 | 59.0s | $0.0191 |
| pa-trap-predestination | trap |  | 1/2 | 0% | 21.5 | 135,566 | 6,042 | 43.1s | $0.0161 |
| pa-when | synthesis |  | 2/2 | 100% | 20.5 | 64,282 | 6,320 | 47.1s | $0.0128 |

## Failures

- `pa-trap-predestination` run 0 · `no_internal_words`: 內部用語：['下文第四點）。  以下我照規矩分三層交代：']

## What these numbers do not say

_Fill in by hand: what each grader actually checks, what it cannot see, and which biases make these numbers look better than the agent is._
