# Eval report: deepseek-flash

- started 20261009-164051 · 27 tasks × n=5 runs · effort=None
- tools: scripture, wesley
- task set sha 8f99af0d3fbb · system prompt sha b7760ea874bf · tools sha cc485ea1d7e8
- run outcomes: {'completed': 135} · grading: {'pass': 127, 'fail': 8}
- latency per run p50 22.8s · p95 47.5s · total cost $0.77
- tokens per run: prompt 9,376 (cache read 7,803) · output 4,295 · tool output 3,009 chars
- answers where the model wrote Simplified characters: 11 (converted to 繁體 before grading: 11)

| slice | tasks | pass rate | pass@5 | pass^5 |
|---|---|---|---|---|
| all | 27 | 94% | 100% | 70% |
| no fault | 22 | 94% | 100% | 68% |
| fault injected | 5 | 96% | 100% | 80% |
| category: crossref | 2 | 100% | 100% | 100% |
| category: doctrine | 3 | 93% | 100% | 67% |
| category: fault | 5 | 96% | 100% | 80% |
| category: quote | 3 | 100% | 100% | 100% |
| category: sermon | 4 | 100% | 100% | 100% |
| category: study | 3 | 93% | 100% | 67% |
| category: trap | 2 | 90% | 100% | 50% |
| category: wesley | 3 | 87% | 100% | 33% |
| category: worship | 2 | 80% | 100% | 0% |

## Tool usage

| tool | calls | per run | errors |
|---|---|---|---|
| cross_references | 106 | 0.8 | 12 |
| fill_quote | 526 | 3.9 | 0 |
| lookup_verse | 639 | 4.7 | 14 |
| wesley_note | 712 | 5.3 | 20 |

## Per task

| task | category | fault | passes | pass^5 | tool calls | prompt tok | output tok | latency | cost |
|---|---|---|---|---|---|---|---|---|---|
| crossref-heb-11-1 | crossref |  | 5/5 | 100% | 14.6 | 8,343 | 3,497 | 18.9s | $0.0047 |
| crossref-john-3-16 | crossref |  | 5/5 | 100% | 7.6 | 6,206 | 2,233 | 12.6s | $0.0030 |
| doctrine-articles-baptism | doctrine |  | 4/5 | 0% | 12.4 | 6,771 | 6,436 | 34.3s | $0.0081 |
| doctrine-assurance | doctrine |  | 5/5 | 100% | 31.4 | 10,487 | 5,429 | 29.1s | $0.0073 |
| doctrine-prevenient-grace | doctrine |  | 5/5 | 100% | 31.0 | 11,393 | 5,340 | 28.9s | $0.0071 |
| fault-crossref-error | fault | error | 5/5 | 100% | 10.8 | 8,782 | 3,136 | 17.6s | $0.0042 |
| fault-ps-23-empty | fault | empty | 4/5 | 0% | 8.2 | 11,048 | 3,915 | 23.8s | $0.0051 |
| fault-quote-mislabeled | fault | mislabeled | 5/5 | 100% | 3.6 | 4,114 | 1,135 | 7.6s | $0.0016 |
| fault-quote-rom-5-8-error | fault | error | 5/5 | 100% | 2.6 | 4,017 | 1,263 | 8.8s | $0.0017 |
| fault-wesley-error | fault | error | 5/5 | 100% | 5.8 | 6,180 | 1,559 | 10.8s | $0.0022 |
| quote-eph-2-8-kjv | quote |  | 5/5 | 100% | 10.0 | 6,577 | 2,890 | 16.9s | $0.0038 |
| quote-ps-23 | quote |  | 5/5 | 100% | 2.4 | 3,275 | 1,693 | 10.1s | $0.0022 |
| quote-rom-5-8 | quote |  | 5/5 | 100% | 2.8 | 2,717 | 407 | 6.4s | $0.0009 |
| sermon-easter-1cor-15 | sermon |  | 5/5 | 100% | 32.6 | 24,177 | 10,148 | 54.5s | $0.0134 |
| sermon-emmaus | sermon |  | 5/5 | 100% | 22.6 | 11,808 | 6,032 | 32.6s | $0.0079 |
| sermon-fact-check | sermon |  | 5/5 | 100% | 6.8 | 5,753 | 3,776 | 20.2s | $0.0048 |
| sermon-perfection-matt-5-48 | sermon |  | 5/5 | 100% | 37.4 | 19,408 | 8,397 | 43.1s | $0.0112 |
| study-james-2 | study |  | 5/5 | 100% | 37.4 | 19,545 | 8,443 | 42.6s | $0.0115 |
| study-luke-15 | study |  | 5/5 | 100% | 18.4 | 10,202 | 5,203 | 27.6s | $0.0070 |
| study-phil-2 | study |  | 4/5 | 0% | 25.4 | 18,480 | 8,898 | 46.2s | $0.0116 |
| trap-no-such-verse | trap |  | 5/5 | 100% | 7.6 | 6,467 | 1,944 | 11.8s | $0.0026 |
| wesley-1jn-1-7 | wesley |  | 5/5 | 100% | 3.6 | 3,711 | 1,912 | 11.5s | $0.0025 |
| wesley-matt-5-48 | wesley |  | 4/5 | 0% | 14.6 | 10,136 | 5,409 | 30.1s | $0.0070 |
| wesley-ps-1 | trap |  | 4/5 | 0% | 8.6 | 8,016 | 3,733 | 20.9s | $0.0049 |
| wesley-rom-8-16 | wesley |  | 4/5 | 0% | 4.8 | 4,485 | 1,904 | 11.9s | $0.0025 |
| worship-advent | worship |  | 4/5 | 0% | 12.2 | 7,328 | 5,090 | 27.1s | $0.0066 |
| worship-sermon-outline | worship |  | 4/5 | 0% | 21.4 | 13,721 | 6,131 | 31.5s | $0.0080 |

## Failures

- `doctrine-articles-baptism` run 0 · `example_no_unsourced_quotes`: written without a tool result: ['從水和聖靈生']
- `fault-ps-23-empty` run 3 · `example_no_unsourced_quotes`: written without a tool result: ['耶和華是我的牧者']
- `study-phil-2` run 3 · `example_quotes_expected_verbatim`: misquoted: ['是神榮耀所發的光輝，是神本體的真像']
- `study-phil-2` run 3 · `no_misquotes`: 引錯：['我的僕人行事必有智慧，必被高舉上升，且成為至高。']
- `wesley-matt-5-48` run 1 · `example_no_unsourced_quotes`: written without a tool result: ['我們若說自己無罪']
- `wesley-ps-1` run 0 · `example_no_unsourced_quotes`: written without a tool result: ['聽神之道而遵守的人']
- `wesley-rom-8-16` run 1 · `example_no_unsourced_quotes`: written without a tool result: ['你們所受的，不是奴僕的心，仍舊害怕']
- `worship-advent` run 4 · `no_misquotes`: 引錯：['得救比初信的時候更近了']
- `worship-sermon-outline` run 3 · `example_no_unsourced_quotes`: written without a tool result: ['外體雖然毀壞，內心卻一天新似一天']

## What these numbers do not say

_Fill in by hand: what each grader actually checks, what it cannot see, and which biases make these numbers look better than the agent is._
