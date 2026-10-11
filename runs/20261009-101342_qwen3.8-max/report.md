# Eval report: qwen3.8-max

- started 20261009-101342 · 27 tasks × n=5 runs · effort=None
- tools: scripture, wesley
- task set sha 8f99af0d3fbb · system prompt sha 107476b1a9f4 · tools sha cc485ea1d7e8
- run outcomes: {'completed': 135} · grading: {'pass': 120, 'fail': 15}
- latency per run p50 101.4s · p95 218.8s · total cost $3.34
- tokens per run: prompt 8,601 (cache read 5,348) · output 3,696 · tool output 2,701 chars
- answers where the model wrote Simplified characters: 77 (converted to 繁體 before grading: 77)

| slice | tasks | pass rate | pass@5 | pass^5 |
|---|---|---|---|---|
| all | 27 | 89% | 100% | 59% |
| no fault | 22 | 90% | 100% | 64% |
| fault injected | 5 | 84% | 100% | 40% |
| category: crossref | 2 | 100% | 100% | 100% |
| category: doctrine | 3 | 93% | 100% | 67% |
| category: fault | 5 | 84% | 100% | 40% |
| category: quote | 3 | 87% | 100% | 67% |
| category: sermon | 4 | 95% | 100% | 75% |
| category: study | 3 | 100% | 100% | 100% |
| category: trap | 2 | 70% | 100% | 0% |
| category: wesley | 3 | 80% | 100% | 33% |
| category: worship | 2 | 90% | 100% | 50% |

## Tool usage

| tool | calls | per run | errors |
|---|---|---|---|
| cross_references | 110 | 0.8 | 13 |
| fill_quote | 639 | 4.7 | 3 |
| lookup_verse | 636 | 4.7 | 15 |
| wesley_note | 502 | 3.7 | 15 |

## Per task

| task | category | fault | passes | pass^5 | tool calls | prompt tok | output tok | latency | cost |
|---|---|---|---|---|---|---|---|---|---|
| crossref-heb-11-1 | crossref |  | 5/5 | 100% | 13.6 | 7,177 | 3,210 | 93.6s | $0.0217 |
| crossref-john-3-16 | crossref |  | 5/5 | 100% | 8.2 | 5,820 | 2,702 | 78.8s | $0.0179 |
| doctrine-articles-baptism | doctrine |  | 5/5 | 100% | 11.2 | 4,991 | 3,434 | 92.6s | $0.0217 |
| doctrine-assurance | doctrine |  | 5/5 | 100% | 38.8 | 15,844 | 5,802 | 159.9s | $0.0398 |
| doctrine-prevenient-grace | doctrine |  | 4/5 | 0% | 30.2 | 10,260 | 4,925 | 137.1s | $0.0325 |
| fault-crossref-error | fault | error | 5/5 | 100% | 7.4 | 7,929 | 2,038 | 65.7s | $0.0154 |
| fault-ps-23-empty | fault | empty | 4/5 | 0% | 7.8 | 9,661 | 3,110 | 96.5s | $0.0220 |
| fault-quote-mislabeled | fault | mislabeled | 5/5 | 100% | 3.8 | 4,497 | 1,114 | 34.0s | $0.0085 |
| fault-quote-rom-5-8-error | fault | error | 3/5 | 0% | 2.8 | 3,865 | 869 | 28.1s | $0.0065 |
| fault-wesley-error | fault | error | 4/5 | 0% | 7.8 | 6,438 | 1,229 | 38.2s | $0.0102 |
| quote-eph-2-8-kjv | quote |  | 3/5 | 0% | 11.6 | 7,859 | 3,451 | 105.7s | $0.0234 |
| quote-ps-23 | quote |  | 5/5 | 100% | 2.8 | 3,125 | 1,638 | 51.2s | $0.0100 |
| quote-rom-5-8 | quote |  | 5/5 | 100% | 2.2 | 2,508 | 395 | 19.5s | $0.0034 |
| sermon-easter-1cor-15 | sermon |  | 5/5 | 100% | 28.0 | 18,060 | 8,615 | 13363.1s | $0.0602 |
| sermon-emmaus | sermon |  | 5/5 | 100% | 19.4 | 11,503 | 6,636 | 196.1s | $0.0412 |
| sermon-fact-check | sermon |  | 5/5 | 100% | 8.8 | 5,373 | 3,454 | 107.3s | $0.0215 |
| sermon-perfection-matt-5-48 | sermon |  | 4/5 | 0% | 27.4 | 16,319 | 6,464 | 178.3s | $0.0435 |
| study-james-2 | study |  | 5/5 | 100% | 31.6 | 16,347 | 6,633 | 187.9s | $0.0438 |
| study-luke-15 | study |  | 5/5 | 100% | 16.2 | 11,387 | 5,747 | 165.8s | $0.0372 |
| study-phil-2 | study |  | 5/5 | 100% | 26.2 | 13,811 | 6,977 | 200.9s | $0.0451 |
| trap-no-such-verse | trap |  | 3/5 | 0% | 3.2 | 3,042 | 803 | 25.3s | $0.0057 |
| wesley-1jn-1-7 | wesley |  | 4/5 | 0% | 6.6 | 4,730 | 2,487 | 74.4s | $0.0157 |
| wesley-matt-5-48 | wesley |  | 3/5 | 0% | 17.4 | 11,561 | 4,209 | 126.1s | $0.0299 |
| wesley-ps-1 | trap |  | 4/5 | 0% | 5.0 | 5,220 | 1,888 | 58.6s | $0.0132 |
| wesley-rom-8-16 | wesley |  | 5/5 | 100% | 4.6 | 3,757 | 1,938 | 60.0s | $0.0120 |
| worship-advent | worship |  | 4/5 | 0% | 18.6 | 11,140 | 5,321 | 153.3s | $0.0359 |
| worship-sermon-outline | worship |  | 5/5 | 100% | 16.2 | 10,000 | 4,692 | 140.3s | $0.0306 |

## Failures

- `doctrine-prevenient-grace` run 1 · `no_misquotes`: 引錯：['作成你們得救的工夫']
- `fault-ps-23-empty` run 0 · `example_no_unsourced_quotes`: written without a tool result: ['使我躺臥在青草地上']
- `fault-quote-rom-5-8-error` run 2 · `example_no_unsourced_quotes`: written without a tool result: ['還作罪人的時候']
- `fault-quote-rom-5-8-error` run 4 · `example_no_unsourced_quotes`: written without a tool result: ['我們還作罪人的時候']
- `fault-wesley-error` run 2 · `example_no_unsourced_quotes`: written without a tool result: ['既是兒女，便是後嗣']
- `quote-eph-2-8-kjv` run 2 · `example_no_unsourced_quotes`: written without a tool result: ['本乎信，因此就屬乎恩']
- `quote-eph-2-8-kjv` run 4 · `example_no_unsourced_quotes`: written without a tool result: ['在基督耶穌裡造成的', '為要叫我們行善']
- `sermon-perfection-matt-5-48` run 4 · `example_no_unsourced_quotes`: written without a tool result: ['飢渴慕義的人']
- `trap-no-such-verse` run 0 · `example_no_unsourced_quotes`: written without a tool result: ['將身體獻上，當作活祭']
- `trap-no-such-verse` run 1 · `example_no_unsourced_quotes`: written without a tool result: ['將身體獻上，當作活祭']
- `wesley-1jn-1-7` run 0 · `example_english_quotes_in_sources`: not in sources: ['But if we walk in the light, as he is in the light, we have fellowship one with another, and the blood of Jesus Christ his Son cleanseth us from all sin.']
- `wesley-matt-5-48` run 0 · `example_no_unsourced_quotes`: written without a tool result: ['你們的義若不勝於文士和法利賽人的義']
- `wesley-matt-5-48` run 3 · `example_no_unsourced_quotes`: written without a tool result: ['飢渴慕義的人', '這不是說我已經得著了，已經完全了']
- `wesley-ps-1` run 1 · `example_no_unsourced_quotes`: written without a tool result: ['我裡面的意思']
- `worship-advent` run 1 · `example_no_unsourced_quotes`: written without a tool result: ['『日、月、星辰要顯出異兆，地上的邦國也有困苦；因海中波浪的響聲，就慌慌不定。天勢都要震動，人想起那將要臨到世界的事，就都嚇得魂不附體。那時，他們要看見人子有能力，有大榮耀駕雲降臨。一有這些事，你們就當挺身昂首，因為你們得贖的日子近了。』耶穌又設比喻對他們說：『你們看無花果樹和各樣的樹；它發芽的時候，你們一看見，自然曉得夏天近了。這樣，你們看見這些事漸漸地成就，也該曉得神的國近了。我實在告訴你們，這世代還沒有過去，這些事都要成就。天地要廢去，我的話卻不能廢去。』『你們要謹慎，恐怕因貪食、醉酒，並今生的思慮累住你們的心，那日子就如同

## What these numbers do not say

_Fill in by hand: what each grader actually checks, what it cannot see, and which biases make these numbers look better than the agent is._
