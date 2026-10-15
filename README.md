# TheoClaw: a Bible-study agent and the harness that measures it

TheoClaw is a small tool-using agent that helps a Mandarin-speaking fellowship of the
Methodist Church, Hong Kong (香港循道衛理聯合教會) prepare Bible studies, and helps
preachers prepare Sunday sermons. It answers
in Traditional Chinese, quotes scripture only from a lookup tool, and draws on the
Methodist sources: John Wesley's *Explanatory Notes upon the New Testament* and, through
a compiled knowledge base, his other writings and the fellowship's course material.

The agent is the small part. Most of this repository is the evaluation harness around
it: every task runs N times, every model call and tool call is traced, tools can be
broken on purpose, answers can be scored by people, and the reports separate "succeeds
sometimes" (pass@k) from "succeeds every time" (pass^k), with tokens and cost per answer.

## What this project tries to answer

The questions behind the harness are the ones any team running a domain-specific,
nondeterministic agent has to answer. Here is where each one stands, with the evidence
in this repository and what is still missing.

| question | what exists | evidence | status |
|---|---|---|---|
| **How much evidence is enough to act?** (deploy, roll back, switch model) | `evals decide`: two-stage bootstrap (tasks, then runs within a task) non-inferiority test with margins fixed before looking; sequential view ("from how many runs would the decision have held?"); simulated sample-size planning | [`runs/calibration/decision_qwen-max_to_deepseek-flash.md`](runs/calibration/decision_qwen-max_to_deepseek-flash.md) | done, used once on a real decision |
| **Can an LLM judge stand in for a person?** | `evals judge score / pair / analyze`: blind rubric scoring, pairwise judgments in both orders, agreement with a reference rater, self-preference, position and length bias | [`runs/calibration/judge_reliability.md`](runs/calibration/judge_reliability.md) | done against one reference rater; domain experts are rating now |
| **How do domain experts turn traces into evals?** | a blind web scoring tool for pastors (rubric, 11 problem types, and a mode where they ask their own questions and score the answer); always-on graders; graders checked against two fake models | [`human_scoring/`](human_scoring/), [Human scoring](#human-scoring) | half: experts can flag problems, but a flagged trace does not yet become a regression task by itself |
| **Can production behaviour be monitored as precisely as regression evals?** | every live question and answer is traced in the same format as eval runs | `runs/pastor-chat/` on the server (not published) | not started: no detector or baseline comparison yet |
| **How far is the eval suite from real use?** (coverage) | 27 tasks in 9 categories (quotation, cross references, Wesley notes, study, worship, sermon, doctrine, traps, tool faults) | [`tasks/tasks.yaml`](tasks/tasks.yaml) | not started |

### Findings so far

- **Switching the answering model: the evidence said "not yet", and the margin of error says why.**
  - deepseek-flash vs qwen3.8-max, 27 tasks × 5 runs, 270 answers scored blind.
  - deepseek-flash was **not worse** on every human metric:
    - mean score 4.85 vs 4.82, difference +0.03 [−0.04, +0.09];
    - answers with a clear flaw 5.9% vs 11.1%.
  - It was 5× cheaper and much faster.
  - The rule-grader pass rate, however, was +3.0 pp with an interval of [−6.7, +12.6]. That is wider than the 5 pp margin.
  - So under the rule fixed in advance the answer is "wait", even though everything points the same way.
  - The sample-size simulation says how to settle it: about 108 tasks × 3 runs gives an 82% chance of showing non-inferiority on that metric. Adding runs to the same 27 tasks helps much less than adding tasks.
  - deepseek-flash became the default for practical reasons (cost and speed), and that is recorded here as a judgement call, not a statistical result.
- **The rule graders are a floor, not a quality measure.**
  - Cohen's kappa between the graders and the blind human verdict was about 0.
  - Every answer the graders failed was judged usable. Three answers they passed were judged unusable, because each invented a source.
- **The LLM judge's main bias is length, not self-preference.** Judging deepseek-flash's and qwen3.8-max's answers, against the blind reference scores:

  | | deepseek-flash as judge | qwen3.8-max as judge |
  |---|---|---|
  | agrees on "usable as is" | 82–84% | 68–71% |
  | mean score vs reference | −0.04 / +0.01 | −0.31 / −0.22 (stricter) |
  | correlation of answer length with excess score | +0.36 | +0.16 |
  | cost per judged answer | ≈ $0.002 | ≈ $0.022 |

  - The qwen judge is slightly kinder to qwen's own answers: −0.22 vs −0.31, a 0.09 gap.
  - In 51 pairs judged in both orders, the winner is the same both ways 80% of the time. The answer shown first wins 52%, so there is no position bias.
  - The longer answer wins 65%. qwen's answers win 67% when they are longer and 42% when they are shorter.
  - What first looked like self-preference is mostly length.
  - The kappa against the reference is uninformative here, because the reference judged 98–100% of answers usable. Telling good from bad needs the domain experts' ratings, which include their flagged problems.
- **Compiling a knowledge base did not beat plain RAG on one book** ([`runs/calibration/kb_vs_rag.md`](runs/calibration/kb_vs_rag.md)).
  - Wesley's *Plain Account* was asked 12 questions × 2 runs: once through an OpenKB wiki compiled by deepseek-flash, and once through BM25 search over the same text.
  - RAG recalled more reference facts (92% vs 81%; 93% vs 72% on synthesis questions), was as faithful (88% vs 87%), and cost half as much per answer. My blind 0–10 scores were 8.75 vs 8.08.
  - The cause is specific: the wiki read tool capped the 190k-character source at 100k characters, so the compiled arm never saw the second half of the book.
  - Groundedness was scored with a RAGAS / FActScore-style evaluator (`evals ground`). It checks each statement against what the agent retrieved, so raters do not have to look anything up.
- **A prompt sentence did not stop a habit; a post-processor plus a grader did.**
  - The model kept explaining its own rules to the user (「按規矩，我不憑記憶寫出經文」).
  - A deterministic scrub now rewrites such phrases. An always-on grader reports what the scrub misses, so new variants surface in reports instead of reaching users.

## Modules

| module | what it does | command line |
|---|---|---|
| `theoclaw.agent` | the agent: hand-written loop, system prompt, scripture tools | `python -m theoclaw ask "…"` |
| `theoclaw.kb.compile` | compiles Methodist sources into an OpenKB wiki and records what the compile cost | `python -m theoclaw.kb.compile …` |
| `theoclaw.kb.query` | reads a compiled wiki (the agent's kb tools); measures and queries wikis | `python -m theoclaw.kb.query …` |
| `theoclaw.evals` | runs, graders, reports, cost comparison, experiments, human scoring | `python -m theoclaw.evals …` |
| `theoclaw.llm` | every model call's settings: roles, providers, models and prices, API clients, single completions | `python -m theoclaw.llm …` |
| `theoclaw.common` | shared: references, scripture data, prices, token counting, 繁體 check | |
| `theoclaw/ui/` | placeholder, not started | |

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
| `scripture` | `lookup_verse` (和合本 / KJV), `cross_references` | `data/` |
| `wesley` | `wesley_note`: Wesley's NT note on one verse, exact lookup | `data/wesley_nt.json` |
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
   does not write the text: it writes `〔經文：羅馬書 5:8〕` (or `，KJV`), and the program
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
| `judge score / pair / analyze` | LLM judge with the rubric, pairwise in both orders, and its agreement and biases against a person |
| `ground score / report` | groundedness against the retrieved text, RAGAS / FActScore style: faithfulness, fact recall, context recall, relevance |
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

`human_scoring/human_server.py` is a small web server (standard library only) for
raters who will not use a terminal:

- **Blind scoring.** Each rater gets a secret link and a shuffled list of answers from
  the runs being compared. Model and task id are hidden. They score the rubric and tick
  any of 11 problem types (invented source, misquoted scripture, off-tradition, …).
  Ratings are saved as `runs/<run>/human/<rater>.jsonl`, the same format as `human rate`,
  so `report`, `decide` and `judge analyze` read them directly.
- **Ask mode (`--chat`).** Raters ask their own questions. The agent (deepseek-flash)
  answers with the same tools, and they score the answer on the same rubric. Every
  question is traced to `runs/pastor-chat/`, with a daily limit per rater and an overall
  budget.
- **Deployment.** `human_scoring/deploy/` packs the app, installs it as a systemd
  service on a small Ubuntu server, and exposes it through a Cloudflare quick tunnel
  (no domain needed).

```powershell
python human_scoring/human_server.py prepare runs/<a> runs/<b> --raters 牧者1,牧者2,牧者3
python human_scoring/human_server.py serve --chat
```

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
runs. Hence deepseek-flash as the default agent. One rater only, and both models are near
the ceiling: "not worse, and much cheaper and faster" is the claim, not "clearly better".

**Rule graders vs judgement.** Cohen's kappa between the rule graders and the blind
verdict was about 0 for both models: every answer the graders failed was judged usable,
and three the graders passed were judged unusable. The rule graders are a floor for
scripture accuracy, not a measure of quality.

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
| `crossrefs.json` | OpenBible.info cross references (top 25 per verse by votes) | CC-BY, credit OpenBible.info |
| `wesley_nt.json` | Wesley, *Explanatory Notes upon the New Testament*, parsed from the PDF in the Methodist folder | text in the public domain |

Only the New Testament part of the Wesley PDF is used: it is Wesley's own work and a
doctrinal standard; the Old Testament notes are largely adapted from other
commentators. The parser is heuristic (5,595 verse notes); spot-check a sample by hand
before building tasks on a specific note. `scripts/build_data.py` rebuilds `data/`.

## Known pitfalls for graders

- The 和合本 text contains its own 「」 marks (約翰福音 3:16 begins with 「), so a
  quotation can contain nested quote marks and split when extracted.
- The agent may translate Wesley inside 「」; a translation is not a quotation.
- Normalisation ignores punctuation and spacing but not character variants (着 / 著).
- The Simplified-character check looks at characters one at a time, so phrase-level
  differences (明了 / 明瞭) and characters common to both scripts (皇后, 鄰里) are not flagged;
  nor is any character the 繁體 和合本 itself uses (吃, 群, 峰 ...), which OpenCC would rewrite.
