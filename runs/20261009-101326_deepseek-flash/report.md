# Eval report: deepseek-flash

- started 20261009-101326 · 27 tasks × n=5 runs · effort=None
- tools: scripture, wesley
- task set sha 8f99af0d3fbb · system prompt sha 107476b1a9f4 · tools sha cc485ea1d7e8
- run outcomes: {'completed': 135} · grading: {'fail': 11, 'pass': 124}
- latency per run p50 20.5s · p95 43.9s · total cost $0.68
- tokens per run: prompt 8,938 (cache read 7,287) · output 3,764 · tool output 3,055 chars
- answers where the model wrote Simplified characters: 9 (converted to 繁體 before grading: 9)

| slice | tasks | pass rate | pass@5 | pass^5 |
|---|---|---|---|---|
| all | 27 | 92% | 100% | 67% |
| no fault | 22 | 92% | 100% | 64% |
| fault injected | 5 | 92% | 100% | 80% |
| category: crossref | 2 | 80% | 100% | 50% |
| category: doctrine | 3 | 93% | 100% | 67% |
| category: fault | 5 | 92% | 100% | 80% |
| category: quote | 3 | 93% | 100% | 67% |
| category: sermon | 4 | 90% | 100% | 50% |
| category: study | 3 | 100% | 100% | 100% |
| category: trap | 2 | 90% | 100% | 50% |
| category: wesley | 3 | 93% | 100% | 67% |
| category: worship | 2 | 90% | 100% | 50% |

## Tool usage

| tool | calls | per run | errors |
|---|---|---|---|
| cross_references | 119 | 0.9 | 15 |
| fill_quote | 632 | 4.7 | 0 |
| lookup_verse | 671 | 5.0 | 15 |
| wesley_note | 712 | 5.3 | 29 |

## Per task

| task | category | fault | passes | pass^5 | tool calls | prompt tok | output tok | latency | cost |
|---|---|---|---|---|---|---|---|---|---|
| crossref-heb-11-1 | crossref |  | 3/5 | 0% | 11.2 | 5,672 | 2,867 | 17.7s | $0.0038 |
| crossref-john-3-16 | crossref |  | 5/5 | 100% | 7.6 | 5,538 | 2,180 | 14.0s | $0.0029 |
| doctrine-articles-baptism | doctrine |  | 4/5 | 0% | 16.8 | 6,022 | 4,830 | 27.4s | $0.0063 |
| doctrine-assurance | doctrine |  | 5/5 | 100% | 34.4 | 13,723 | 5,484 | 32.2s | $0.0074 |
| doctrine-prevenient-grace | doctrine |  | 5/5 | 100% | 30.6 | 11,319 | 5,507 | 31.5s | $0.0074 |
| fault-crossref-error | fault | error | 5/5 | 100% | 9.2 | 9,201 | 2,171 | 14.7s | $0.0030 |
| fault-ps-23-empty | fault | empty | 3/5 | 0% | 7.6 | 9,452 | 3,195 | 21.8s | $0.0042 |
| fault-quote-mislabeled | fault | mislabeled | 5/5 | 100% | 4.0 | 4,355 | 1,090 | 7.7s | $0.0015 |
| fault-quote-rom-5-8-error | fault | error | 5/5 | 100% | 2.4 | 3,867 | 937 | 7.4s | $0.0013 |
| fault-wesley-error | fault | error | 5/5 | 100% | 7.2 | 6,620 | 1,133 | 9.1s | $0.0017 |
| quote-eph-2-8-kjv | quote |  | 5/5 | 100% | 8.6 | 4,955 | 2,508 | 16.4s | $0.0033 |
| quote-ps-23 | quote |  | 5/5 | 100% | 2.4 | 2,617 | 1,293 | 9.0s | $0.0017 |
| quote-rom-5-8 | quote |  | 4/5 | 0% | 2.6 | 2,754 | 530 | 7.8s | $0.0010 |
| sermon-easter-1cor-15 | sermon |  | 4/5 | 0% | 41.8 | 23,073 | 8,821 | 50.6s | $0.0119 |
| sermon-emmaus | sermon |  | 5/5 | 100% | 25.0 | 10,929 | 6,222 | 36.6s | $0.0082 |
| sermon-fact-check | sermon |  | 4/5 | 0% | 7.8 | 4,685 | 3,293 | 19.2s | $0.0042 |
| sermon-perfection-matt-5-48 | sermon |  | 5/5 | 100% | 42.0 | 19,648 | 7,724 | 42.9s | $0.0104 |
| study-james-2 | study |  | 5/5 | 100% | 34.2 | 19,255 | 6,460 | 37.0s | $0.0091 |
| study-luke-15 | study |  | 5/5 | 100% | 24.4 | 14,652 | 5,524 | 32.6s | $0.0076 |
| study-phil-2 | study |  | 5/5 | 100% | 33.6 | 15,240 | 7,885 | 45.4s | $0.0105 |
| trap-no-such-verse | trap |  | 5/5 | 100% | 4.2 | 3,466 | 830 | 5.9s | $0.0012 |
| wesley-1jn-1-7 | wesley |  | 5/5 | 100% | 6.0 | 5,136 | 3,115 | 19.8s | $0.0040 |
| wesley-matt-5-48 | wesley |  | 4/5 | 0% | 13.6 | 9,012 | 4,025 | 26.0s | $0.0054 |
| wesley-ps-1 | trap |  | 4/5 | 0% | 7.6 | 5,971 | 2,475 | 15.9s | $0.0033 |
| wesley-rom-8-16 | wesley |  | 5/5 | 100% | 5.0 | 3,625 | 1,585 | 11.5s | $0.0021 |
| worship-advent | worship |  | 4/5 | 0% | 16.0 | 10,321 | 5,272 | 31.1s | $0.0070 |
| worship-sermon-outline | worship |  | 5/5 | 100% | 21.0 | 10,227 | 4,676 | 27.8s | $0.0062 |

## Failures

- `crossref-heb-11-1` run 0 · `example_no_unsourced_quotes`: written without a tool result: ['我信不足，求主幫助']
- `crossref-heb-11-1` run 2 · `example_no_unsourced_quotes`: written without a tool result: ['存著信心死的，並沒有得著所應許的']
- `doctrine-articles-baptism` run 1 · `example_no_unsourced_quotes`: written without a tool result: ['從水和聖靈生']
- `fault-ps-23-empty` run 1 · `example_no_unsourced_quotes`: written without a tool result: ['領他們到生命水的泉源']
- `fault-ps-23-empty` run 2 · `example_no_unsourced_quotes`: written without a tool result: ['為自己的名引導我走義路']
- `quote-rom-5-8` run 4 · `example_quotes_expected_verbatim`: misquoted: ['不但不是良善的，連公義也談不上']
- `sermon-easter-1cor-15` run 0 · `example_no_unsourced_quotes`: written without a tool result: ['從死裡首先復生的', '誠實作見證的、從死裡首先復活']
- `sermon-easter-1cor-15` run 0 · `no_misquotes`: 引錯：['首先從死裡復活的']
- `sermon-fact-check` run 4 · `example_no_unsourced_quotes`: written without a tool result: ['不愛惜自己的兒子']
- `wesley-matt-5-48` run 4 · `example_no_unsourced_quotes`: written without a tool result: ['他們必得飽足']
- `wesley-ps-1` run 0 · `example_no_unsourced_quotes`: written without a tool result: ['主認識誰是他的人', '凡稱呼主名的人，總要離開不義']
- `worship-advent` run 1 · `example_no_unsourced_quotes`: written without a tool result: ['願你裂天而降']

## What these numbers do not say

_Fill in by hand: what each grader actually checks, what it cannot see, and which biases make these numbers look better than the agent is._
