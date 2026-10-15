# Eval report: deepseek-flash

- started 20261016-005426 · 12 tasks × n=2 runs · effort=None
- tools: scripture, kb · knowledge base plain-account-pdf.en.deepseek-flash (wiki 146824003465; compiled by deepseek/deepseek-flash, language en, compile cost $0.09)
- task set sha 22c8c4045697 · system prompt sha e2ce07214c28 · tools sha 26e127ab70a1
- run outcomes: {'completed': 24} · grading: {'pass': 24}
- latency per run p50 41.3s · p95 65.2s · total cost $0.36
- tokens per run: prompt 108,991 (cache read 83,408) · output 5,802 · tool output 102,642 chars
- answers where the model wrote Simplified characters: 7 (converted to 繁體 before grading: 7)

| slice | tasks | pass rate | pass@2 | pass^2 |
|---|---|---|---|---|
| all | 12 | 100% | 100% | 100% |
| no fault | 12 | 100% | 100% | 100% |
| fault injected | 0 | – | – | – |
| category: lookup | 3 | 100% | 100% | 100% |
| category: pastoral | 1 | 100% | 100% | 100% |
| category: synthesis | 7 | 100% | 100% | 100% |
| category: trap | 1 | 100% | 100% | 100% |

## Tool usage

| tool | calls | per run | errors |
|---|---|---|---|
| fill_quote | 103 | 4.3 | 0 |
| kb_get_page_content | 86 | 3.6 | 0 |
| kb_read_file | 99 | 4.1 | 2 |
| lookup_verse | 114 | 4.8 | 0 |

kb_read_file by folder: concepts 35, entities 14, index 24, summaries 26 (only sources/ holds the original words)

## Per task

| task | category | fault | passes | pass^2 | tool calls | prompt tok | output tok | latency | cost |
|---|---|---|---|---|---|---|---|---|---|
| pa-bishop-gibson | lookup |  | 2/2 | 100% | 5.0 | 31,828 | 2,208 | 23.6s | $0.0062 |
| pa-can-lose | synthesis |  | 2/2 | 100% | 31.0 | 217,382 | 8,706 | 57.9s | $0.0237 |
| pa-definition-1767 | synthesis |  | 2/2 | 100% | 11.5 | 42,918 | 4,232 | 27.8s | $0.0091 |
| pa-early-reading | lookup |  | 2/2 | 100% | 14.5 | 41,883 | 4,694 | 37.7s | $0.0086 |
| pa-first-conference | lookup |  | 2/2 | 100% | 9.5 | 39,158 | 3,322 | 23.8s | $0.0075 |
| pa-instant-gradual | synthesis |  | 2/2 | 100% | 13.5 | 100,818 | 3,988 | 29.9s | $0.0116 |
| pa-need-christ | synthesis |  | 2/2 | 100% | 16.5 | 120,156 | 5,414 | 36.9s | $0.0151 |
| pa-not-perfect | synthesis |  | 2/2 | 100% | 22.5 | 150,378 | 7,808 | 57.4s | $0.0202 |
| pa-pastoral-objection | pastoral |  | 2/2 | 100% | 21.5 | 103,400 | 6,449 | 44.2s | $0.0163 |
| pa-sin-distinction | synthesis |  | 2/2 | 100% | 22.5 | 184,105 | 9,246 | 62.7s | $0.0236 |
| pa-trap-predestination | trap |  | 2/2 | 100% | 13.5 | 207,544 | 7,208 | 48.0s | $0.0254 |
| pa-when | synthesis |  | 2/2 | 100% | 19.5 | 68,320 | 6,356 | 43.7s | $0.0144 |

## What these numbers do not say

_Fill in by hand: what each grader actually checks, what it cannot see, and which biases make these numbers look better than the agent is._
