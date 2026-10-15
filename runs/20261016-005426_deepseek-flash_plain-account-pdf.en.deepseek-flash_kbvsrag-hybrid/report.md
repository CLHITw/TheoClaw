# Eval report: deepseek-flash

- started 20261016-005426 · 12 tasks × n=2 runs · effort=None
- tools: scripture, kb, rag · knowledge base plain-account-pdf.en.deepseek-flash (wiki 146824003465; compiled by deepseek/deepseek-flash, language en, compile cost $0.09)
- task set sha 22c8c4045697 · system prompt sha ac2998c22f93 · tools sha 69b1b9cb371b
- run outcomes: {'completed': 24} · grading: {'pass': 23, 'fail': 1}
- latency per run p50 40.1s · p95 67.5s · total cost $0.29
- tokens per run: prompt 77,880 (cache read 61,200) · output 5,436 · tool output 64,948 chars
- answers where the model wrote Simplified characters: 4 (converted to 繁體 before grading: 4)

| slice | tasks | pass rate | pass@2 | pass^2 |
|---|---|---|---|---|
| all | 12 | 96% | 100% | 92% |
| no fault | 12 | 96% | 100% | 92% |
| fault injected | 0 | – | – | – |
| category: lookup | 3 | 100% | 100% | 100% |
| category: pastoral | 1 | 100% | 100% | 100% |
| category: synthesis | 7 | 93% | 100% | 86% |
| category: trap | 1 | 100% | 100% | 100% |

## Tool usage

| tool | calls | per run | errors |
|---|---|---|---|
| fill_quote | 94 | 3.9 | 0 |
| kb_get_page_content | 39 | 1.6 | 0 |
| kb_read_file | 77 | 3.2 | 1 |
| lookup_verse | 104 | 4.3 | 0 |
| rag_search | 106 | 4.4 | 0 |

kb_read_file by folder: concepts 28, entities 10, index 24, summaries 15 (only sources/ holds the original words)

## Per task

| task | category | fault | passes | pass^2 | tool calls | prompt tok | output tok | latency | cost |
|---|---|---|---|---|---|---|---|---|---|
| pa-bishop-gibson | lookup |  | 2/2 | 100% | 3.5 | 15,536 | 1,788 | 19.4s | $0.0042 |
| pa-can-lose | synthesis |  | 2/2 | 100% | 28.5 | 139,860 | 8,722 | 61.0s | $0.0192 |
| pa-definition-1767 | synthesis |  | 2/2 | 100% | 12.0 | 45,214 | 3,838 | 25.9s | $0.0089 |
| pa-early-reading | lookup |  | 2/2 | 100% | 15.0 | 35,500 | 4,980 | 38.8s | $0.0097 |
| pa-first-conference | lookup |  | 2/2 | 100% | 9.0 | 23,404 | 2,788 | 19.5s | $0.0052 |
| pa-instant-gradual | synthesis |  | 2/2 | 100% | 11.5 | 33,378 | 2,926 | 23.0s | $0.0060 |
| pa-need-christ | synthesis |  | 1/2 | 0% | 15.0 | 33,760 | 4,108 | 28.7s | $0.0082 |
| pa-not-perfect | synthesis |  | 2/2 | 100% | 23.0 | 120,054 | 6,694 | 49.7s | $0.0167 |
| pa-pastoral-objection | pastoral |  | 2/2 | 100% | 24.5 | 126,693 | 7,850 | 54.5s | $0.0163 |
| pa-sin-distinction | synthesis |  | 2/2 | 100% | 23.5 | 158,676 | 8,290 | 56.4s | $0.0181 |
| pa-trap-predestination | trap |  | 2/2 | 100% | 19.5 | 110,759 | 6,685 | 44.7s | $0.0154 |
| pa-when | synthesis |  | 2/2 | 100% | 25.0 | 91,721 | 6,564 | 47.7s | $0.0148 |

## Failures

- `pa-need-christ` run 1 · `no_misquotes`: 引錯：['離了他就不能做甚麼']

## What these numbers do not say

_Fill in by hand: what each grader actually checks, what it cannot see, and which biases make these numbers look better than the agent is._
