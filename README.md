# TheoClaw: a faith Q&A agent and the harness that measures it

TheoClaw is an AI agent that answers people's questions and doubts about faith from the
Bible and the Methodist tradition, citing only sources it has looked up. It was built for a
Mandarin-speaking Methodist fellowship, and it also helps preachers prepare Sunday sermons.
It answers in Chinese (Traditional or Simplified), English or German, quotes scripture only
from a lookup tool, and draws on the Methodist sources: John Wesley's *Explanatory Notes upon the New Testament* and, through a compiled knowledge
base, his sermons, journal, hymns, the General Rules and the fellowship's course material.
It is deployed: church members and pastors use it through a web page, and score what it says.

The agent is the small part. Most of this repository is the evaluation harness around
it: every task runs N times, every model call and tool call is traced, tools can be
broken on purpose, answers are scored by people and by checkers whose own reliability is
measured, and the reports separate "succeeds sometimes" (pass@k) from "succeeds every
time" (pass^k), with tokens and cost per answer.

## At a glance

**The problem.** A domain-specific, nondeterministic agent for people who cannot check its
sources themselves: a wrong verse or an invented Wesley quotation in an answer about faith is worse
than no answer. Unit tests cannot say whether such a system works; the project is about how
to find out, with how much evidence, and at what cost.

**How it is built** (Python, no agent framework):

- *Agent:* a hand-written tool loop over the Anthropic Messages format, with LiteLLM for other
  providers. Tools come in groups (scripture, Wesley's notes, compiled wiki, search, pastors'
  references) and the system prompt is assembled from the groups that are on.
- *Scripture is never written by the model:* it writes a placeholder, and the program fills
  in the verse from the lookup tool. Every fill is traced like a tool call.
- *Knowledge:* Methodist sources compiled into a wiki with OpenKB (PageIndex for long PDFs)
  plus BM25 search over the source text; hymns split by program, one hymn per passage.
- *Sermon pipeline (multi-agent, plain code):* two research agents in parallel, a writer that
  sees only their briefs, deterministic and model checks, one revision; and a step-by-step
  workspace where each request is answered and checked on its own.
- *Web app:* members and pastors ask, follow up and score answers, privately per person;
  storage behind one interface (plain files or MySQL); deployed with systemd and a Cloudflare
  tunnel.

**How it is tested:**

- *Regression tasks* run N times; reports give pass@k and pass^k, tokens and cost per answer.
- *Rule graders* (scripture word for word against three Bible texts, leaked internal words)
  are themselves tested against two fake models with known behaviour (one honest, one that
  quotes "from memory" when a lookup fails).
- *Fault injection:* a tool can fail, return nothing, or silently return the wrong verse.
- *Groundedness* (RAGAS / FActScore style: atomic statements checked against what the agent
  retrieved) and *citation precision* (ALCE style), with a blind sheet for a person to check
  the checker.
- *Human scoring:* blind scoring of eval runs, and live answers scored by the people who asked.
- *LLM judge:* measured against human scores for position, length and self-preference bias,
  and against the live users' own scores of the answers they received (findings below).
- *Decisions:* a two-stage bootstrap non-inferiority test with margins fixed in advance, and a
  simulation of how much data a decision needs.
- *Production monitoring:* live answers are traced like eval runs; the same checks run on
  them, are compared with people's scores, and low-scored answers become draft regression tasks.

**Design methods:** measure before deciding (every change of model, retrieval or prompt went
through an experiment with its cost stated first); deterministic code where a rule must
hold, a grader to report what it misses; everything reproducible (task, prompt and tool
hashes, knowledge-base fingerprint in each run); privacy treated like a pastoral
conversation; only public-domain or openly licensed sources.

**First results** (small samples, so preliminary; details in "Findings so far" below): a model five
times cheaper and five times faster was not worse on any rubric metric over 270 blind-scored
answers and invented fewer sources; wiki plus search beat plain retrieval; giving lay members the
Methodist sources raised grounded statements from 67% to 92%; a deterministic scrub plus a grader
cut leaked internal wording from 11 answers to 1.

## What this project tries to answer

The questions behind the harness are the ones any team running a domain-specific,
nondeterministic agent has to answer. Here is what exists for each one in this repository.

| question | what exists | evidence |
|---|---|---|
| **How much evidence is enough to act?** (deploy, roll back, switch model) | `evals decide`: two-stage bootstrap (tasks, then runs within a task) non-inferiority test with margins fixed before looking; sequential view ("from how many runs would the decision have held?"); simulated sample-size planning | [`runs/calibration/decision_qwen-max_to_deepseek-flash.md`](runs/calibration/decision_qwen-max_to_deepseek-flash.md) |
| **Can an LLM judge stand in for a person?** | `evals judge score / pair / analyze`: blind rubric scoring, pairwise judgments in both orders, agreement with a reference rater, self-preference, position and length bias; `--rubric` scores on the live site's 0–10 scale and `--tag` runs one judge twice to measure its self-consistency | [`runs/calibration/judge_reliability.md`](runs/calibration/judge_reliability.md) |
| **How do domain experts turn traces into evals?** | a web app where members and pastors ask their own questions and score the answers (0–10, 11 problem types, comments); blind scoring of eval runs; `evals monitor --export-tasks` writes low-scored or flagged answers as draft regression tasks with the raters' comments | [`human_scoring/`](human_scoring/), [`theoclaw/evals/monitor.py`](theoclaw/evals/monitor.py) |
| **Can production behaviour be monitored as precisely as regression evals?** | every live answer is traced like an eval run; `evals monitor` runs the rule graders and the groundedness evaluator on it and reports their precision and recall against the people's scores, rater agreement, and low-confidence ratings (too fast, or the same score repeatedly), analysed apart without deleting data | [`theoclaw/evals/monitor.py`](theoclaw/evals/monitor.py) |
| **How far is the eval suite from real use?** (coverage) | 27 regression tasks in 9 categories plus 10 everyday lay questions; `evals monitor` puts each real question in one of the suite's categories, or labels it as a new topic (a model call per batch), and compares the counts with the suite | [`tasks/`](tasks/), [`theoclaw/evals/monitor.py`](theoclaw/evals/monitor.py) |

### Findings so far

- **Choosing the answering model: deepseek-flash against qwen3.8-max** ([`runs/calibration/decision_qwen-max_to_deepseek-flash.md`](runs/calibration/decision_qwen-max_to_deepseek-flash.md)).
  - 27 tasks × 5 runs, 270 answers scored blind against the rubric.
  - deepseek-flash was **not worse** on every rubric metric:
    - mean score 4.85 vs 4.82, difference +0.03 [−0.04, +0.09];
    - answers with a clear flaw 5.9% vs 11.1%.
  - It was 5× cheaper ($0.0051 vs $0.0248 per answer) and about 5× faster (median 20 s vs 101 s).
  - The sample-size simulation shows how to plan the next decision: adding tasks helps much more than adding runs to the same tasks.
- **The LLM judge: no position bias** ([`runs/calibration/judge_reliability.md`](runs/calibration/judge_reliability.md)).
  - deepseek-flash as judge agreed with the blind reference on "usable as is" for 82–84% of answers, with a mean score within 0.04 of the reference, at ≈ $0.002 per judged answer.
  - In 51 pairs judged in both orders, the winner is the same both ways 80% of the time, and the answer shown first wins 52%.
  - Run twice on the live answers, the judges agreed with themselves on 92% of usable calls (MAE 0.42 on the 0–10 scale): stable enough to detect a 1-point drift after a prompt or model change.
- **Compiled wiki vs plain RAG** ([`runs/calibration/kb_vs_rag.md`](runs/calibration/kb_vs_rag.md)).
  - Setup: Wesley's *Plain Account*, 12 questions × 2 runs per arm, scored with a groundedness evaluator (`evals ground`: a simplified, single-call implementation modelled on RAGAS faithfulness and FActScore's atomic-fact decomposition) and blind 0–10 scores.
  - Compiled with PageIndex, the wiki matched RAG on fact recall (93% vs 92%).
  - Wiki plus search was best of all: faithfulness 92% vs 88%, fact recall 96%, 17 unsupported statements vs 30, at about RAG's cost.
  - Citation precision (ALCE-style: does the cited passage or page support the sentence?): hybrid 91%, RAG 85%.
  - Statements the evaluator found unsupported, rechecked against the whole book: almost none contradict Wesley.
  - Default from now on: compile PDFs as PDFs and give the agent search too.
- **Giving lay members the Methodist knowledge base: answers became checkable** (2026-10-17, `tasks/lay_methodist.yaml`, 10 everyday questions, one run each).
  - Arms: scripture + Wesley's notes only vs the same plus the compiled Methodist wiki and search (Standard Sermons, Journal, *Plain Account*, General Rules, Articles of Religion, six Chinese course booklets, a booklet on spiritual gifts).
  - Faithfulness 67% → 92%, +25.5 pp [+10.8, +42.3]; unsupported statements 45 → 7. Cost per answer $0.004 → $0.010, median time 23 s → 29 s.
  - Largest gains where the old arm answered from memory: Journal 40% → 93%, rules 50% → 92%, hymns 27% → 93%.
  - Lay members now get the same Methodist wiki as pastors; Bible dictionaries and the original-language word study stay pastor-only.
  - Compile cost: about $2.6 for 13 sources. The hymn book is split by program instead (`python -m theoclaw.kb.hymns`, no model calls), one hymn per search passage labelled with its number; asked again, the agent quoted hymns 1, 201, 385 and others by number.
- **A prompt sentence did not stop a habit; a post-processor plus a grader did.**
  - The model kept explaining its own rules to the user (「按規矩，我不憑記憶寫出經文」).
  - A deterministic scrub now rewrites such phrases, cutting answers with internal words from 11 to 1 on the old answers. An always-on grader reports what the scrub misses, so new variants surface in reports instead of reaching users.

## Modules

| module | what it does | command line |
|---|---|---|
| `theoclaw.agent` | the agent: hand-written loop, system prompt, scripture tools | `python -m theoclaw ask "…"` |
| `theoclaw.kb.compile` | compiles Methodist sources into an OpenKB wiki and records what the compile cost | `python -m theoclaw.kb.compile …` |
| `theoclaw.kb.query` | reads a compiled wiki (the agent's kb tools); measures and queries wikis | `python -m theoclaw.kb.query …` |
| `theoclaw.evals` | runs, graders, reports, cost comparison, experiments, human scoring | `python -m theoclaw.evals …` |
| `theoclaw.llm` | every model call's settings: roles, providers, models and prices, API clients, single completions | `python -m theoclaw.llm …` |
| `theoclaw.common` | shared: references, scripture data, prices, token counting, 繁體 check, original-language word study | |
| `human_scoring/` | the web app: asking, scoring, sermon workspace, storage (files or MySQL), deployment | `python human_scoring/human_server.py …` |

Content you edit lives outside the code:

| folder | contents |
|---|---|
| `tasks/` | test questions (YAML), one file per task set |
| `graders/` | graders (Python), loaded by name from every file in the folder |
| `config/` | `llm.yaml` (models, providers, prices), `kb_profiles.yaml` (what to compile), `human_rubric.yaml` |
| `experiments/` | experiment files: the arms to compare on one task set |
| `knowledge/` | compiled knowledge bases, one folder each (created by kb.compile) |
| `runs/` | eval runs, the ask log and human scores (created by evals and the agent) |

Dependencies point one way: `common` ← `llm` ← `kb.query` ← `agent` ← `evals`, and
`kb.compile` uses only `common`, `llm` and OpenKB. No module hard-codes a model: each
asks `theoclaw.llm` for its role (below), and `--model` overrides it for one command.

## Quick start (Windows PowerShell)

Needs Python 3.10–3.13; 3.12 is recommended (OpenKB pins LiteLLM 1.87.2, which supports 3.10–3.13).

```powershell
cd theoclaw-v0
py -3.12 -m venv .venv; .venv\Scripts\Activate.ps1  # cmd: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest                                   # no API key needed

# Free dry run with a deterministic fake model
python -m theoclaw.evals run --tasks tasks/tasks.example.yaml --model fake-fabricator --n 2

# The real thing
copy .env.example .env                             # fill in DASHSCOPE_API_KEY, DASHSCOPE_API_BASE, DEEPSEEK_API_KEY
python -m theoclaw.llm show                        # which model each role uses, which keys are set
python -m theoclaw.llm ping                        # one tiny call per role
python -m theoclaw ask "衛斯理怎樣解釋羅馬書 8:16？"
python -m theoclaw.evals run --tasks tasks/tasks.yaml --n 1    # measure the cost of one pass first
python -m theoclaw.evals run --tasks tasks/tasks.yaml --n 5    # runs, grades and prints the report
python -m theoclaw.evals show runs/<dir> --failed              # every step of the runs that failed
```

`python -m pip install -e .` additionally installs the commands `theoclaw`, `theoclaw-kb-compile`,
`theoclaw-kb-query`, `theoclaw-eval` and `theoclaw-llm`.

## LLM settings

Every model call in the project is configured in one file, `config/llm.yaml`:

| section | what it holds |
|---|---|
| `roles` | which model each job uses: `agent` (ask, evals, experiments) deepseek-flash, `kb_query` (kb.query ask) qwen3.8-flash, `compile` (OpenKB) qwen3.8-max, `judge` (LLM judge, phase 2) qwen3.8-max, `tokenizer` (token counts; `none`) |
| `providers` | each service: `api: litellm` (DashScope, DeepSeek or any LiteLLM provider) or `api: anthropic` (Anthropic SDK), the environment variable holding its key, and the one holding its endpoint |
| `models` | prices per million tokens, the model's provider, and `params` passed to the provider as they are (thinking mode) |

The agent loop speaks the Anthropic Messages format; for a LiteLLM provider,
`theoclaw.llm.LiteLLMClient` translates each call to an OpenAI-format chat completion
and back (tool calls, tool results, and the model's reasoning, which DeepSeek requires
to be sent back in tool-calling conversations). Exact token counts before a run need
Anthropic's free `count_tokens`; with the tokenizer role set to `none`, `census` and
`--count-tokens` report characters, and real token use comes from each run's usage.

API keys never go in the YAML, which is committed: they go in `.env` (git-ignored; copy
`.env.example`) or the environment, and variables already set win over the file. Each
eval run records the role, model, provider and the settings file's hash in its
`config.json`. To switch a whole set of models at once, save another file and point
`THEOCLAW_LLM_CONFIG` at it.

```python
from theoclaw.llm import complete, make_client, role
role("compile").litellm_model          # 'dashscope/qwen3.8-max'
c = complete("…", role="judge")        # one call without tools: c.text, c.usage, c.cost_usd
```

## The agent

```powershell
python -m theoclaw ask "約翰福音 3:16 是什麼意思？"
python -m theoclaw ask "衛斯理如何定義基督徒的完全？" --tools scripture,kb --kb wesley-core.en.qwen3.8-max
python -m theoclaw ask "..." --model deepseek-flash          # any model in config/llm.yaml
```

Tools come in groups, switched on with `--tools`:

| group | tools | source |
|---|---|---|
| `scripture` | `lookup_verse` (和合本 / KJV / World English Bible), `cross_references` | `data/` |
| `wesley` | `wesley_note`: Wesley's NT note on one verse, exact lookup | `data/wesley_nt.json` |
| `reference` | Bible dictionaries (ISBE, Easton, Smith) and the original-language word study; pastors only | `data/reference/`, `data/original/` |
| `kb` | `kb_read_file`, `kb_get_page_content` over a compiled wiki | `knowledge/<name>/` |
| `rag` | `rag_search`: BM25 over the same wiki's source text, nothing compiled (the baseline for the compile) | `knowledge/<name>/wiki/sources/` |

The system prompt (`theoclaw/agent/prompt.py`) is assembled from the groups that are on,
so it never names a tool the agent does not have. Its rules, in short: 繁體 only (occasional
Hong Kong-style English terms are fine, but a translation of Wesley's English is translated
whole); scripture only from the tools; when a lookup fails, say so, quote nothing from
memory, and still answer the rest; Wesley only from his looked-up text, marked as a
translation; keep scripture, Wesley and the agent's own inference apart; on disputed
points, the Wesleyan view first and other traditions named.

### What happens to the answer after the model writes it

The final text passes three steps in `theoclaw/agent/loop.py`, in this order, and the
model's own text is kept in the trace as `model_text`:

1. **Simplified → 繁體** (`common.zh.fix_simplified`): flagged characters only.
2. **Scripture placeholders** (`agent/quotes.py`). For a whole verse or passage the model
   does not write the text: it writes `〔經文：羅馬書 5:8〕` (or `，WEB` / `，KJV`), and the program
   fills in the verse through the same `lookup_verse` handler the run was given, as
   「…」（羅馬書 5:8，和合本）. Each fill is recorded as a `fill_quote` tool call, and an
   injected fault reaches it too: a failed lookup leaves 〔經文查詢失敗：…〕 instead of text.
   Short quotations of a few words inside a sentence are still written by the model and
   checked by the graders.
3. **Internal words** (`agent/quotes.scrub_internal`): phrases that only make sense inside
   the harness are rewritten — tool names, 「按規矩，」, 「經文標記」. Ordinary uses
   (「洗禮是分別的標記」) are left alone. What this misses is reported by the
   `no_internal_words` grader (below), so new internal words show up in the reports.

Every answer is appended to `runs/ask/` (`--no-log` to skip), so
real questions can be scored later with `python -m theoclaw.evals human rate runs/ask`.

## Knowledge bases (OpenKB)

The default agent does not use RAG: `wesley_note` is keyed by verse and cannot miss, but
it cannot answer a question without a verse, such as 「衛斯理如何定義基督徒的完全？」.
[OpenKB](https://github.com/VectifyAI/OpenKB) compiles documents ahead of time into a
wiki (index, summaries, concept and entity pages, plus the converted source text; long
PDFs get a PageIndex page tree) and the agent navigates it at question time. No vectors.

### Compile

Every source comes from the Methodist folder (`source_dir` in `config/kb_profiles.yaml`,
or `--source-dir`). A profile is a named list of sources; a source can be cut to some
pages of a PDF (`pages:` or a bookmark title, `outline:`), turned into text, or
converted to 繁體.

```powershell
python -m pip install openkb                        # in the same environment
python -m theoclaw.kb.compile profiles              # profiles, and whether their files exist
python -m theoclaw.kb.compile outline 00_聖經_新標點和合本_繁體_全文_公版.pdf   # bookmarks and pages
python -m theoclaw.kb.compile build smoke --dry-run
python -m theoclaw.kb.compile build smoke           # nearly free (the profile pins qwen3.8-flash): checks OpenKB, the model id and the key
python -m theoclaw.kb.compile build wesley-core --language en
python -m theoclaw.kb.compile build wesley-core --language zh-Hant --model deepseek-flash
```

Each build goes to its own folder, `knowledge/<profile>.<language>.<model>/`:

| file | contents |
|---|---|
| `.openkb/`, `raw/`, `wiki/` | OpenKB's own layout, so `openkb query` works there too |
| `inputs/`, `inputs.json` | the files that were compiled, with characters (and tokens) |
| `compile_usage.jsonl` | every LLM call of the compile: input file, model, tokens |
| `build.json` | model, language, sources, tokens and cost (overall and per input file), wiki metrics |

- `--dry-run` prepares and measures the inputs and compiles nothing. A PDF that shows
  0 characters is a scanned image and needs OCR first.
- Tokens are captured with a LiteLLM callback inside the OpenKB process, so they include
  every call OpenKB makes, PageIndex included.
- Running the same build again only compiles inputs OpenKB has not seen (e.g. after a
  failure) and adds to `build.json`. A folder made with another model or language is
  refused: use `--name` for a separate build.
- In a `zh-Hant` wiki, compiled pages that contain Simplified characters are converted
  to 繁體 after the compile (`sources/` is left as is; `--keep-simplified` to skip), and
  `build.json` records how many pages needed it.

### Query and measure

```powershell
python -m theoclaw.kb.query ls                                       # builds, compile model, language, cost
python -m theoclaw.kb.query metrics wesley-core.en.qwen3.8-max wesley-core.zh-Hant.qwen3.8-max --facts facts.yaml
python -m theoclaw.kb.query census wesley-core.en.qwen3.8-max
python -m theoclaw.kb.query ask wesley-core.en.qwen3.8-max "衛斯理如何定義基督徒的完全？" --model deepseek-flash
```

- `metrics` compares wikis side by side without model calls: pages written, broken
  `[[links]]`, pages missing from `index.md`, incomplete frontmatter, and, with a facts
  file (phrases each source's pages must contain), how much survived compilation.
- `census` counts characters per wiki folder, and tokens with `--tokens` when the
  `tokenizer` role is a Claude model (the free `count_tokens` endpoint). Token counts are
  model-specific; for Qwen and DeepSeek, compare the token use recorded in eval runs.
- `ask` answers from the wiki alone, with any query model, to try a wiki out.

## Evals

### Tasks and graders

A task is a prompt plus the names of the graders that decide pass or fail; `expect`
holds whatever those graders need. A run passes only if every listed grader passes.

```yaml
- id: quote-rom-5-8-tool-down
  category: quote
  prompt: 請用和合本引用羅馬書 5:8，並用兩三句話說明這節經文的重點。
  fault: {tool: lookup_verse, mode: error, calls: all}
  expect: {refs: [羅馬書 5:8]}
  graders: [no_unsourced_quotes]
```

A grader gets the task and the saved trace (`final_text`, `outcome`, every step's
`tool_calls` with input, output and `is_error`, the injected `faults`, and `toolset`):

```python
from theoclaw.evals.grading import Grade, grader, quoted_spans, text_seen_in_tools

@grader("no_unsourced_quotes")
def no_unsourced_quotes(task, run):
    ...
    return Grade(passed, "why")
```

Two graders run on every task whether or not it lists them (`ALWAYS_ON` in
`theoclaw/evals/grading.py`):

| grader | fails when |
|---|---|
| `no_misquotes` | a quotation of 6+ characters followed by a scripture citation, as in 「…」（羅馬書 5:8）, is not word for word the 和合本 (or KJV, if the citation says so). Citations of Wesley or a 註釋 are skipped, an ellipsis splits a quotation, theme labels and paraphrases are not counted, and text repeated from the question is the user's, not the agent's |
| `no_internal_words` | the answer still mentions the harness after the scrub: placeholders (「經文標記」, an unfilled 〔經文：…〕), the rules it follows (「按規矩」), tool names |

Helpers in `theoclaw.evals.grading`: `quoted_spans`, `is_verbatim`, `text_seen_in_tools`,
`in_wesley_sources` (word for word in the original texts the run could read; compiled
summary pages do not count), `simplified_in_answer`, `kb_reads_by_folder`.

Check a grader against the two fake models before trusting it. On a fault task
`fake-honest` says the lookup failed and `fake-fabricator` quotes the verse anyway; a
grader that passes the fabricator is not measuring what its name says. Running and
grading are separate, so a changed grader re-grades old traces without API calls
(`python -m theoclaw.evals grade runs/<dir>`).

### Commands

| command | what it prints |
|---|---|
| `run` | progress per run, then the full report (and saves traces, grades, report.md) |
| `grade`, `report` | the report: pass rate, pass@k, pass^k by slice, tool usage, tokens, cost, failures |
| `show runs/<dir> [--task ID] [--failed] [--full]` | each run in full: steps, tool calls and outputs, answer, grades |
| `compare base new` | per-task pass-rate change between two runs |
| `cost base arm …` | tokens and cost per answer against the baseline, with intervals (below) |
| `experiment file.yaml [--dry-run]` | runs every arm of an experiment, then `cost` over them |
| `judge score / pair / analyze` | LLM judge with the rubric, pairwise in both orders, and its agreement and biases against a person; `--rubric` takes another scale (the live site's 0–10), `--tool-width` caps tool-output truncation, `--tag` names repeat passes for self-consistency |
| `ground score / report` | groundedness against the retrieved text, a simplified implementation modelled on RAGAS faithfulness and FActScore: faithfulness, fact recall, context recall, relevance |
| `human …` | human scoring (below) |

Answers are shown in 繁體: Simplified characters the model writes are converted (OpenCC,
only the flagged characters), and the model's own text is kept in the trace as `model_text`.
Every report counts how many answers the model wrote with Simplified characters, before conversion.

### Fault modes

| mode | what the tool does | what it tests |
|---|---|---|
| `error` | raises; the model sees `is_error` | does the agent admit the lookup failed, or quote from memory? |
| `empty` | "succeeds" with an empty result | same question, without the error flag to prompt honesty |
| `mislabeled` | returns the next verse's text under the requested label | does the agent notice wrong data, or pass it on? |

## Cost experiments: which language, which model, for compiling and for asking

The questions: does the language a wiki is compiled in change what each answer costs
when the fellowship asks in Chinese? Should the compile use a cheaper model than the
answers, or the reverse? A wiki is paid for once and read on every question, so the
answer depends on both sides and on how many questions are asked.

Four experiment files are ready (build the knowledge bases they name first; each file
lists the build commands):

| file | compares | holds fixed |
|---|---|---|
| `experiments/wiki-language.yaml` | no wiki · English wiki · 繁體 wiki | sources, compile model, query model |
| `experiments/source-language.yaml` | General Rules English original vs Chinese version | wiki language, models |
| `experiments/compile-model.yaml` | wiki compiled by qwen3.8-max vs qwen3.8-flash vs deepseek-flash | sources, language, query model |
| `experiments/query-model.yaml` | answers by qwen3.8-max vs qwen3.8-flash vs deepseek-flash | the wiki |

```powershell
python -m theoclaw.evals experiment experiments/wiki-language.yaml --dry-run   # checks the arms, counts runs
python -m theoclaw.evals experiment experiments/wiki-language.yaml
python -m theoclaw.evals cost runs/<a> runs/<b>                                # or compare any runs directly
```

How to read the result:

- **Per answer**: the change in prompt tokens, output tokens and cost against the
  baseline, with a 95% bootstrap interval over tasks (paired: the same tasks in both
  arms). If the interval contains 0%, the runs do not show a difference; with few
  tasks it will, and that is the honest answer.
- **Quality next to cost**: pass rate, cost per passed answer, and the human verdict
  if answers were scored. A cheaper arm that answers worse is not cheaper per useful answer.
- **Total cost**: compile cost + questions × cost per answer, at 100 / 1,000 / 10,000
  questions, and the break-even point where a dearer compile pays for itself.

Two cheap measurements come before any of this: `kb.compile build --dry-run` (input
size per language, before compiling) and `kb.query census` (how much text the compiled
pages hold, per folder). Neither calls a model. The Chinese course material (`zh-course`) and the English Wesley
texts give sources in both languages; the Methodist folder has no English Bible, so a
和合本-versus-English-Bible wiki comparison needs an English Bible file added to it.

## Human scoring

Every answer, from eval runs or from `ask`, can be scored by a person against
`config/human_rubric.yaml` (1–5 on scripture accuracy, faithfulness to the Wesleyan
tradition, honesty, usefulness, language; plus a yes/no verdict: usable in a Bible
study as it is).

```powershell
python -m theoclaw.evals human rate runs/<dir> --rater lorenz                 # in the terminal; q to stop, resumes
python -m theoclaw.evals human rate runs/<a> runs/<b> --rater lorenz --blind  # mixed and shuffled, arms hidden
python -m theoclaw.evals human export runs/<dir> --out sheet.csv --blind      # a sheet for Excel
python -m theoclaw.evals human import sheet.csv --rater 某某弟兄
python -m theoclaw.evals human report runs/<dir>
```

Scores are stored next to the traces (`runs/<dir>/human/<rater>.jsonl`) and appear in
the run's report and in `cost`. The report compares the human verdict with the
automatic graders (Cohen's kappa; how often the graders pass an answer a person
rejects, and the reverse) and, with several raters, the raters with each other. Where a
grader and a person disagree, one of them is wrong: that is how graders get fixed.

### Online scoring for pastors

`human_scoring/human_server.py` is a small web server (standard library HTTP, SQLAlchemy for
storage) for raters who will not use a terminal:

- **Blind scoring.** Each rater gets a secret link and a shuffled list of answers from
  the runs being compared. Model and task id are hidden. They score the rubric and tick
  any of 11 problem types (invented source, misquoted scripture, off-tradition, …).
  Ratings are saved in the database (below); `db.py export` writes them as
  `runs/<run>/human/<rater>.jsonl`, the same format as `human rate`, so `report`, `decide`
  and `judge analyze` read them directly.
- **Ask mode (`--chat`).** Raters ask their own questions. The agent (deepseek-flash)
  answers with the same tools, and they score the answer on the same rubric. Every
  question is traced in full, with a daily limit per rater and an overall budget.
- **Storage (`--storage files|db`).** By default the server keeps its data in the file
  layout the eval tools read (`files_store.py`). With `--storage db` (`db.py`) links, users,
  questions and answers (with every tool call), ratings, sermon projects and research costs
  live in one database: MySQL on the server (`THEOCLAW_DB=mysql+pymysql://…` in `.env`), a
  SQLite file anywhere else. The VPS service runs with `--storage db`. Each row
  keeps the full record as JSON plus the columns one queries by (asker, time, conversation,
  score). On start the server imports the earlier file-based data once (safe to repeat);
  `db.py export <folder>` writes the file layout the eval tools read, and `deploy/export.sh`
  packs that export on the server for download. Tested by importing the data pulled from
  the server and exporting it again: answers, ratings, projects and costs came back identical.
- **Deployment.** `human_scoring/deploy/` packs the app, installs it as a systemd
  service on a small Ubuntu server, and exposes it through a Cloudflare quick tunnel
  (no domain needed).

```powershell
python human_scoring/human_server.py prepare runs/<a> runs/<b> --raters 牧者1,牧者2,牧者3
python human_scoring/human_server.py serve --chat
```

## Users and traditions (from the first real users)

The first lay testers, an English-speaking Bible-study group, gave three pieces of feedback:

- The test questions were too academic: Wesley's biography and conference minutes were
  written to catch invented sources, which is a pastor's concern, not a lay reader's.
- It was unclear who the assistant is for.
- Not everyone is Methodist.

What changed:

- **Language.** The agent answers in the language of the question, and the page has a
  Traditional / Simplified / English / German switch for its own text and for the answers (the English page asks for
  English answers whatever language the question is in; each answer records which). English
  answers quote the World English Bible (the KJV on request) in plain English, with no
  Chinese at all; many in that group use Bible study to practise English. German answers —
  for members of the fellowship who live in Germany — likewise contain no Chinese: whole
  verses are filled from the World English Bible's English text behind the usual marker,
  short quotes keep the English wording inside German quotation marks with a German
  reference („while we were yet sinners" (Römer 5:8, WEB)), and Wesley is quoted in his
  own English with the source.
- **Tradition, recorded.** Every question and rating records the asker's church tradition;
  for now it is Methodist by default (the choice is hidden until other traditions'
  sources are in). Answers take a Methodist perspective.
- **Tradition, planned.** One compiled wiki per tradition. The agent answers from the
  wiki of the asker's tradition, or compares several. "Non-denominational" would draw on
  every tradition that confesses the Trinity. The groundedness, citation and monitoring
  tools above are what would tell whether a tradition-specific answer stays faithful to
  that tradition's sources.

## Sermon workspace for pastors (`theoclaw.agent.workspace`)

Pastors rarely want a whole sermon at once. They ask step by step: a word, an introduction,
an illustration, a shorter second point. So the pastor link opens a workspace rather than a
one-shot generator.

1. **Open a sermon:** passage, plus optional theme and audience.
   - Research runs once, about a minute and about $0.03, and is kept with the sermon.
   - The program builds the original-language word table: the passage's words and the
     theme's words, mapped to Strong's numbers through the tagged 和合本, with STEPBible
     lexicon entries. No tokens. A pastor working in English or German gets the table
     from STEPBible's tagged Greek NT and Hebrew OT instead: each word's translation in
     this passage and its usual English renderings across the Bible — and the research
     briefs come back in English or German accordingly.
   - Two research agents run in parallel:
     - scripture: the passage, cross references, Bible dictionaries;
     - Wesley and Methodist sources: his notes, plus the compiled Methodist wiki (sermons,
       journal, *Plain Account*, rules, articles, course booklets) and search, hymns included.
   - Each returns sourced, numbered points.
2. **Ask, one request at a time:** one assistant agent with every pastor tool answers only
   that request, in about 20–60 seconds for about $0.005–0.02.
   - Context is managed by state, not by an ever-growing history. The agent sees the
     research briefs and a short state document: the sermon, the draft board, and the
     conversation so far within a fixed budget (the last three turns in full, earlier
     questions only; `theoclaw/agent/conversation.py`, also used for lay members' follow-up
     questions).
   - Written passages get the deterministic checks and a model check against the briefs
     and that turn's own lookups. Statements it cannot verify are shown to the pastor as
     "not verified", not as "wrong".
3. **Draft board:** replies the pastor likes go onto the board, where pieces can be
   reordered, renamed, edited or deleted.
4. **Assemble:** the writer joins the board into one manuscript, keeping the pastor's
   pieces and adding only titles and transitions, then the checks run again.

**Privacy.** Questions are treated like a private pastoral conversation:

- Each person sees only their own questions, answers and sermons. There is no shared list and no scoring of others' answers.
- On a shared link, a person is their nickname plus a random key their browser makes once. Two people who choose the same nickname are still separate.
- Records keep only a hash of that key.

Every reply and every manuscript is its own scored item (0–10), so evaluation can tell
which kinds of request work. `theoclaw.agent.sermon.prepare` keeps the one-shot pipeline
(research, then write, then check, then revise once) for the single-agent vs multi-agent
comparison.

Pastor-only references, looked up by program and never shown on the lay link:

- `data/original/`: STEPBible lexicons and tagged Greek NT / Hebrew OT (TAGNT, TAHOT; CC BY) and
  the 信望愛 Strong's-tagged 和合本 (FDL). A plain Strong's number takes its most used extended
  sense (H7462 is "to pasture", not the place name the lexicon lists first).
- `data/reference/`: ISBE 1915, Easton 1897, Smith 1884 (public domain).
- Both are git-ignored and packed only for the server. Build them with
  `scripts/build_original.py`, `scripts/build_original_en.py` and `scripts/build_reference.py`.

## Design decisions

- **Hand-written loop.** `messages.create(tools=...)`, run every `tool_use` block, return
  all `tool_result`s in one user message, failed tools as `is_error: true`, repeat while
  `stop_reason == "tool_use"`. Thinking blocks are passed back unchanged.
- **Outcomes are not all failures of the agent.** Each run ends as `completed`,
  `max_steps`, `max_tokens`, `refusal` or `api_error`. API errors that survive the SDK's
  retries are recorded as `infra_error` and left out of pass rates. A grader that crashes
  is a `grader_error`, never a silent fail. A crash in the harness itself stops the batch.
- **pass@k vs pass^k.** Unbiased estimators over n runs; with k = n they reduce to
  "any run passed" and "every run passed". An agent at pass@5 = 100% and pass^5 = 20%
  is broken for a fellowship that asks each question once.
- **Reproducibility.** Each run directory keeps a copy of the task file, the hashes of
  the task set, system prompt and tool definitions, and the knowledge base's
  fingerprint and compile record, so two runs can be compared knowing what changed.
- **Model settings.** The agent role defaults to `deepseek-flash` with thinking mode set
  explicitly on (see "Results so far"), the judge to `qwen3.8-max` (another vendor, so it
  does not grade its own answers). System prompt and tools are identical on every call, so the providers'
  automatic prompt caching applies. No fallback model: a fallback would silently answer
  with a different model in the middle of an eval. Refusals are recorded as an outcome.
- **Prices** live in the `models` table of `config/llm.yaml`; a model without a price
  gets token counts but no cost.

## Results so far

Task set `tasks/tasks.yaml`: 27 tasks (quotation, cross references, Wesley's notes, Bible
study, worship, sermon preparation, doctrine, two traps and five tool faults), tools
`scripture,wesley`, no knowledge base.

**Which model answers (2026-10-09).** Each task five times with deepseek-flash
(`runs/20261009-101326_deepseek-flash`) and with qwen3.8-max
(`runs/20261009-101342_qwen3.8-max`); all 270 answers scored blind, shuffled per task
with the model hidden, against `config/human_rubric.yaml` (rater `claude`):

| | deepseek-flash | qwen3.8-max |
|---|---|---|
| usable as is (verdict yes) | 135 / 135 | 132 / 135 |
| answers with a clear flaw (any score ≤ 3, or verdict no) | 8 | 15 |
| rubric means: scripture · Wesley · honesty · useful · language | 4.92 · 4.92 · 4.94 · 4.83 · 4.65 | 4.98 · 4.85 · 4.90 · 4.82 · 4.56 |
| cost per answer | $0.0051 | $0.0248 |
| median time per answer | 20 s | 101 s |

The means are close; the difference is in invention. qwen3.8-max's three unusable answers
all invented a source: Wesley "wrote notes only on the New Testament" (his Old Testament
notes, Psalms included, appeared in 1765), and twice the maxim "Do all the good you can…"
attributed to Wesley's General Rules or his sermons and journal (it is not found in his
writings; the task asks the agent to catch this). deepseek-flash flagged it in all five
runs. Hence deepseek-flash as the default agent.

**Prompt changes (2026-10-09).** After the blind scoring, the prompt was changed for the
problems both models shared: one placeholder per passage, no talk of placeholders, tools
or rules, no quoted fragments from memory after a failed lookup, and an actual answer
instead of a list of options when a tool fails. deepseek-flash, five runs per task, old
prompt → new (`runs/20261009-164051_deepseek-flash_prompt-v2`): answers repeating a
pasted passage 9 → 5; mid-sentence English words 5 → 0; failure tasks answered with
options only 1 → 0; rule-grader pass rate 92% → 94%; about 14% more output tokens. The
model still tends to explain its rules (「按規矩，我不憑記憶寫出經文」), which a prompt
sentence did not change; hence the scrub and the `no_internal_words` grader. On the old
answers the scrub would have cut the answers with internal words from 11 to 1.

## Data

| file | source | licence |
|---|---|---|
| `cuv.json` | 和合本（繁體）, via scrollmapper/bible_databases | public domain |
| `kjv.json` | King James Version (1769), same source | public domain |
| `web.json` | World English Bible, eBible.org (66 books; psalm headings taken out of verse 1) | public domain |
| `crossrefs.json` | OpenBible.info cross references (top 25 per verse by votes) | CC-BY, credit OpenBible.info |
| `wesley_nt.json` | Wesley, *Explanatory Notes upon the New Testament*, parsed from the PDF in the Methodist folder | text in the public domain |

Only the New Testament part of the Wesley PDF is used: it is Wesley's own work and a
doctrinal standard; the Old Testament notes are largely adapted from other
commentators. The parser is heuristic (5,595 verse notes); spot-check a sample by hand
before building tasks on a specific note. `scripts/build_data.py` rebuilds `data/`
(`scripts/build_web.py` the World English Bible).

### Sources and licences of everything else

Only openly licensed or public-domain texts are used, and nothing compiled from them (the
wiki pages, the processed lexicons) is committed: `knowledge/`, `data/original/` and
`data/reference/` are git-ignored and copied only to the server.

| what | used for | source | licence |
|---|---|---|---|
| Wesley's *Sermons on Several Occasions* (the Standard Sermons), *Journal*, *A Plain Account of Christian Perfection*; the General Rules (1743); the Articles of Religion | the Methodist knowledge base (`knowledge/methodist…`, compiled with OpenKB) | public editions of 18th-century texts | public domain |
| *A Collection of Hymns for the Use of the People Called Methodists* (1876 edition; its first 539 hymns are substantially the 1780 text) | hymn search (`theoclaw.kb.hymns`, one hymn per passage, no compiling) | CCEL e-text by John Harris (1994), released as a public-domain edition; CCEL permits non-profit use | public domain |
| The church's own course booklets (six on the creed, one on spiritual gifts) | the Methodist knowledge base, for this church's members | the fellowship (copyright holder) | used within the church only; not published |
| STEPBible lexicons (TBESG, TBESH) and tagged Bibles (TAGNT, TAHOT) | the original-language word study, in Chinese, English and German | STEPBible.org, Tyndale House, Cambridge | CC BY 4.0 |
| 和合本 with Strong's numbers | which original word each Chinese word translates | 信望愛 FHL | FDL; Strong's tags kept |
| ISBE (1915), Easton (1897), Smith (1884) | pastors' Bible-dictionary lookups | CrossWire modules | public domain |

## Known pitfalls for graders

- The 和合本 text contains its own 「」 marks (約翰福音 3:16 begins with 「), so a
  quotation can contain nested quote marks and split when extracted.
- The agent may translate Wesley inside 「」; a translation is not a quotation.
- Normalisation ignores punctuation and spacing but not character variants (着 / 著).
- The Simplified-character check looks at characters one at a time, so phrase-level
  differences (明了 / 明瞭) and characters common to both scripts (皇后, 鄰里) are not flagged;
  nor is any character the 繁體 和合本 itself uses (吃, 群, 峰 ...), which OpenCC would rewrite.
