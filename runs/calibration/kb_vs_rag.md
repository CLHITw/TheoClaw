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

- **Groundedness** (`evals ground`, judge deepseek-flash; a simplified, single-call implementation modelled on RAGAS faithfulness and FActScore's atomic-fact decomposition (not the ragas library; statements are checked against what the agent retrieved, not the whole source; no TruLens context relevance and no ALCE citation check yet). The judge is the same model that answered, and it has not yet been checked against human judgments): faithfulness (share of the answer's statements supported by what the agent retrieved), fact recall (reference facts the answer states), context recall (reference facts present in what was retrieved), relevance.
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

---

# Re-run: the compile done the way OpenKB intends it (2026-10-16)

**What changed.** The first run's loss traced back to my own setup, so I ran the
comparison again with that fixed.

- **Before:** the PDF was turned into plain text (`to_text: true`) before compiling, so
  OpenKB treated the book as a short document. Our read tool's 100k-character cap then
  hid the second half of the book.
- **This time:** the PDF itself was compiled (profile `plain-account-pdf`). Because it is
  longer than 20 pages, OpenKB built a PageIndex page tree, and the agent reads the pages
  it needs with `kb_get_page_content`.
- **Compile cost:** 62 calls, $0.09.
- **New fourth arm, a hybrid:** the same page-indexed wiki plus `rag_search` (BM25 over
  the wiki's page text). This asks whether the compiled pages add anything on top of
  retrieval.

Same 12 tasks, 2 runs each, same answering model and evaluator.

| | kb, text-converted (first run) | rag | kb, PageIndex | hybrid (PageIndex + rag) |
|---|---|---|---|---|
| faithfulness | 87% | 88% | 89% | **92%** |
| fact recall | 81% | 92% | 93% | **96%** |
| context recall | 85% | 94% | 96% | **98%** |
| synthesis questions: fact recall | 72% | 93% | 91% | **94%** |
| unsupported statements (24 answers) | 31 | 30 | 28 | **17** |
| blind score on the 4 hardest tasks (8 answers each, 0–10) | 6.50 | 8.38 | 8.88 | 8.88 |
| cost per answer | $0.023 | $0.011 | $0.015 | $0.012 |
| median time per answer | 64 s | 38 s | 41 s | 40 s |
| compile (one-off) | $0.11 | none | $0.09 | $0.09 |

The 4 hardest tasks are the ones that separated the arms in the first run:
`pa-can-lose`, `pa-definition-1767`, `pa-when` and `pa-pastoral-objection`. The blind
scores for the two new arms were given without knowing which arm wrote which answer, but
only between those two arms, since I had already seen the first two.

**Paired over tasks, against rag (95% bootstrap interval):**

| | kb (PageIndex) − rag | hybrid − rag |
|---|---|---|
| faithfulness | +1.2 pp [−1.9, +4.4] | **+4.0 pp [+0.9, +6.9]** |
| fact recall | +1.2 pp [−5.1, +8.1] | +3.5 pp [−2.2, +11.0] |
| context recall | +2.7 pp [−3.3, +9.4] | +3.8 pp [−3.3, +12.1] |

## Conclusion, revised

1. **Done properly, the compiled wiki is as good as RAG.** Its interval overlaps rag on
   every metric, and it costs a little more per answer. The first run's loss was a
   setup error (text conversion plus the read cap), not a property of compiling.
2. **Compiled pages plus retrieval is the best of the four.** It is the only arm whose
   faithfulness gain over rag excludes zero. It has the fewest unsupported statements
   (17 against 28–31), and its cost and speed are about the same as rag.
   - Mechanism: the agent reads the summary and concept pages to see the book as a whole,
     then searches for the passage that backs each statement. Fewer statements end up
     resting on the compiled paraphrase alone.
3. **How long documents enter the knowledge base matters more than whether they are
   compiled.** A long book handled as one text file cost more and answered worse.
   Recommended default for TheoClaw: compile PDFs as PDFs (PageIndex) and give the agent
   search as well.

Limits are unchanged: one book, 12 tasks, model evaluator and model rater.
**Spent on this re-run:** ¥4.3 on DeepSeek, which used up the account's granted balance.
The topped-up ¥20 is untouched.
