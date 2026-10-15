# Does compiling help? OpenKB wiki vs plain RAG (2026-10-16)

**Question.** For the same source text and the same answering model, does compiling the
text into an OpenKB wiki ahead of time give better answers than retrieving from the raw
text at question time?

## Setup

| | kb (compiled) | rag (not compiled) |
|---|---|---|
| source | Wesley, *A Plain Account of Christian Perfection* (75 pages, 190k characters, English) | same file (`wiki/sources/`) |
| what the agent gets | `kb_read_file` over the wiki: index, 1 summary, 3 concept pages, 10 entity pages, and the converted source | `rag_search`: BM25 over 1,200-character chunks (200 overlap) of the same source; the agent writes its own English queries |
| preparation | OpenKB compile with deepseek-flash: 16 calls, $0.11, once | none ($0) |
| answering model | deepseek-flash, thinking on | same |
| tasks | `tasks/kb_vs_rag.yaml`: 12 questions in Chinese (3 lookup, 7 synthesis, 1 pastoral, 1 trap) with reference facts from the text | same |
| runs | 2 per task, 24 answers | same |

There is no embedding search because DeepSeek offers no embedding API and a local model
would mean a large download; BM25 with agent-written queries is the baseline.

## Evaluation

- **Groundedness** (`evals ground`, RAGAS / FActScore style, judge deepseek-flash): faithfulness (share of the answer's statements supported by what the agent retrieved), fact recall (reference facts the answer states), context recall (reference facts present in what was retrieved), relevance.
- **Blind 0–10 score** by rater `claude` on all 48 answers, shuffled, arm hidden. Not fully blind: kb answers often cite wiki paths, rag answers cite "段落 N".

## Results

| | kb (compiled) | rag | kb − rag, paired over tasks [95% interval] |
|---|---|---|---|
| blind score, mean (0–10) | 8.08 | 8.75 | −0.67 [−1.58, 0.00] |
| usable (score ≥ 7) | 21 / 24 | 24 / 24 | |
| faithfulness | 87% | 88% | −0.6 pp [−5.5, +4.1] |
| fact recall | 81% | 92% | −11.1 pp [−24.4, +0.5] |
| context recall | 85% | 94% | −9.2 pp [−20.0, +0.8] |
| synthesis questions: fact recall | 72% | 93% | |
| lookup questions: fact recall | 98% | 100% | |
| cost per answer | $0.023 | $0.011 | +100% [+57%, +153%] |
| median time per answer | 60 s | 35 s | |
| answers cut off (max_tokens) | 2 | 0 | |

**Total cost**, including the one-off compile for the kb arm:

| questions | kb | rag |
|---|---|---|
| 100 | $2.40 | $1.14 |
| 1,000 | $23.0 | $11.4 |

(`evals cost` adds the $0.11 compile cost to both arms because both read the same knowledge-base folder. The rag arm needs no compile, so its real total is lower by $0.11.)

## Why the compiled arm lost

The kb answers fell short on the synthesis questions that need the last third of the
book, such as when perfection can be lost (`pa-can-lose`, kb −3.0 points) and the 1767
definition (`pa-definition-1767`, −4.5).

- **The source was cut in half.** OpenKB classed the 190k-character file as a "short"
  document, so it was not split into pages. The wiki's read tool returns at most 100k
  characters, so every kb answer saw only the first half of the book (24/24 answers).
  The 1764 propositions, the 1767 *Brief Thoughts* and Q&A 29–31 are in the second half.
- **The agent trusted the paraphrase.** The compiled concept pages mention those
  passages, but only as summaries. Some answers then said, wrongly, that Wesley "never
  changed his view" on losing perfection. Others honestly said "I could not read the
  original".
- **Cost doubled.** Reading 100k characters per answer doubled the prompt tokens, and in
  two answers the model ran out of output tokens.

RAG retrieves 1,200-character pieces from anywhere in the book, so it never had this
problem.

## Conclusion

On this book, with this model, compiling did not pay off. Plain RAG was at least as
faithful, recalled more of the reference facts (above all on synthesis questions), and
cost half as much per answer. The blind scores agree: 3 of 24 compiled answers were not
usable, against none for RAG.

What the result does **not** show:

- **It is not a verdict on compiled wikis in general.** The loss traces mostly to one
  handling detail: a long document classed as short, plus a read cap. Splitting the
  source into pages (PageIndex) or raising the cap would test the compile itself.
- **It covers one book and 12 questions.** Compiled pages might help where an answer
  has to combine several documents. Here one book's own structure, read through search,
  was enough.
- **The intervals are wide.** Only the cost difference excludes zero. Fact recall and
  the blind score lean toward RAG, but their intervals touch zero.
- **One evaluator and one rater, both models.** The groundedness judge (deepseek-flash)
  and the blind rater (`claude`) agree on the direction. No human has rated these
  answers yet.

**Spent:** about ¥5.4 on DeepSeek in total (compile, 48 answers, groundedness checks),
all from the account's granted balance.
