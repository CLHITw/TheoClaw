# Eval report: deepseek-flash

- started 20261016-000125 · 12 tasks × n=2 runs · effort=None
- tools: scripture, kb · knowledge base plain-account.en.deepseek-flash (wiki 2a76ed541c62; compiled by deepseek/deepseek-flash, language en, compile cost $0.11)
- task set sha 22c8c4045697 · system prompt sha e2ce07214c28 · tools sha 26e127ab70a1
- run outcomes: {'completed': 22, 'max_tokens': 2} · grading: {'pass': 24}
- latency per run p50 63.7s · p95 132.6s · total cost $0.55
- tokens per run: prompt 140,278 (cache read 106,693) · output 10,154 · tool output 131,469 chars
- answers where the model wrote Simplified characters: 5 (converted to 繁體 before grading: 5)

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
| kb_get_page_content | 27 | 1.1 | 27 |
| kb_read_file | 174 | 7.2 | 7 |
| lookup_verse | 119 | 5.0 | 1 |

kb_read_file by folder: concepts 53, entities 36, index 24, log.md 6, sources 28, summaries 27 (only sources/ holds the original words)

## Per task

| task | category | fault | passes | pass^2 | tool calls | prompt tok | output tok | latency | cost |
|---|---|---|---|---|---|---|---|---|---|
| pa-bishop-gibson | lookup |  | 2/2 | 100% | 3.5 | 40,696 | 2,166 | 21.6s | $0.0116 |
| pa-can-lose | synthesis |  | 2/2 | 100% | 29.0 | 237,933 | 22,717 | 134.4s | $0.0386 |
| pa-definition-1767 | synthesis |  | 2/2 | 100% | 19.0 | 259,132 | 15,884 | 94.3s | $0.0340 |
| pa-early-reading | lookup |  | 2/2 | 100% | 15.0 | 77,656 | 5,455 | 41.1s | $0.0165 |
| pa-first-conference | lookup |  | 2/2 | 100% | 13.0 | 79,336 | 6,976 | 44.0s | $0.0176 |
| pa-instant-gradual | synthesis |  | 2/2 | 100% | 15.0 | 158,782 | 6,464 | 44.2s | $0.0179 |
| pa-need-christ | synthesis |  | 2/2 | 100% | 14.5 | 104,544 | 13,710 | 78.5s | $0.0258 |
| pa-not-perfect | synthesis |  | 2/2 | 100% | 20.0 | 112,614 | 10,986 | 70.4s | $0.0232 |
| pa-pastoral-objection | pastoral |  | 2/2 | 100% | 26.0 | 171,511 | 10,493 | 68.3s | $0.0231 |
| pa-sin-distinction | synthesis |  | 2/2 | 100% | 16.5 | 111,310 | 6,774 | 45.0s | $0.0179 |
| pa-trap-predestination | trap |  | 2/2 | 100% | 14.5 | 207,747 | 8,698 | 58.4s | $0.0245 |
| pa-when | synthesis |  | 2/2 | 100% | 25.5 | 122,075 | 11,522 | 73.1s | $0.0241 |

## What these numbers do not say

_Fill in by hand: what each grader actually checks, what it cannot see, and which biases make these numbers look better than the agent is._
