"""Build one knowledge base: knowledge/<name>/ with OpenKB's own layout (.openkb/,
raw/, wiki/) plus

    inputs/               the files that were compiled (prepared from the Methodist folder)
    compile_usage.jsonl   one line per LLM call: input file, model, tokens
    build.json            what was built, with which model and language, and what it cost

The default name is <profile>.<language>.<model>, e.g. wesley-core.en.qwen3.8-max,
so builds that differ only in compile model or wiki language sit side by side.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ...common import zh
from ...common.paths import CONFIG_DIR, KNOWLEDGE_DIR
from ...llm import litellm_id, role
from .. import MANIFEST
from .sources import PreparedInput, input_text, prepare_source

PROFILES_FILE = CONFIG_DIR / "kb_profiles.yaml"
# Wiki language as given on the command line -> the string OpenKB puts in its prompts
# ("Write all content in {language} language.").
LANGUAGES = {"en": "English", "zh-Hant": "Traditional Chinese (繁體中文)"}


def load_profiles(path: Path | str = PROFILES_FILE) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def model_slug(model: str) -> str:
    return model.split("/")[-1]


@dataclass
class BuildPlan:
    profile: str
    description: str
    sources: list[dict]
    source_dir: Path
    model: str          # LiteLLM provider/model, e.g. dashscope/qwen3.8-flash
    language: str       # en | zh-Hant
    name: str
    root: Path = field(init=False)

    def __post_init__(self):
        self.root = KNOWLEDGE_DIR / self.name


def make_plan(profile: str, *, model: str | None = None, language: str | None = None, name: str | None = None,
              source_dir: str | Path | None = None, profiles_file: Path | str = PROFILES_FILE) -> BuildPlan:
    cfg = load_profiles(profiles_file)
    profiles = cfg.get("profiles") or {}
    if profile not in profiles:
        raise SystemExit(f"unknown profile {profile!r}; defined in {profiles_file}: {', '.join(profiles)}")
    p, defaults = profiles[profile], cfg.get("defaults") or {}
    chosen = model or p.get("model")  # --model, or a profile's own model; else the compile role
    model = litellm_id(chosen) if chosen else role("compile").litellm_model
    language = language or p.get("language") or defaults.get("language", "en")
    if language not in LANGUAGES:
        raise SystemExit(f"--language must be one of {list(LANGUAGES)}")
    src = Path(source_dir or cfg.get("source_dir") or ".")
    if not src.is_dir():
        raise SystemExit(f"source folder {src} not found; set source_dir in {profiles_file} or pass --source-dir")
    return BuildPlan(profile, str(p.get("description", "")), list(p.get("sources") or []), src, model, language,
                     name or f"{profile}.{language}.{model_slug(model)}")


def prepare_inputs(plan: BuildPlan) -> list[PreparedInput]:
    inputs_dir = plan.root / "inputs"
    inputs: list[PreparedInput] = []
    for spec in plan.sources:
        inputs += prepare_source(spec, plan.source_dir, inputs_dir)
    return inputs


def describe_inputs(inputs: list[PreparedInput], counter=None) -> list[dict]:
    """Characters (and tokens, with a TokenCounter) of each input: the compile-side
    size, before any money is spent."""
    rows = []
    for inp in inputs:
        text = input_text(Path(inp.path))
        rows.append({"file": Path(inp.path).name, "kind": inp.kind, "pages": inp.pages, "chars": len(text),
                     "tokens": counter.count(text) if counter else None})
    return rows


@contextmanager
def _cwd(path: Path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _openkb():
    try:
        from openkb.cli import cli
    except ImportError as e:
        raise SystemExit("OpenKB is not installed: pip install openkb  (see README, knowledge bases)") from e
    return cli


def init_kb(plan: BuildPlan) -> None:
    """`openkb init` in the knowledge-base folder, or a check that an existing one
    was made with the same model and language (mixing them would spoil a comparison)."""
    config_path = plan.root / ".openkb" / "config.yaml"
    if config_path.is_file():
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if cfg.get("model") != plan.model or cfg.get("language") != LANGUAGES[plan.language]:
            raise SystemExit(f"{plan.root} was initialised with model={cfg.get('model')} "
                             f"language={cfg.get('language')}; use another --name for a different build")
        return
    from click.testing import CliRunner
    with _cwd(plan.root):
        # init asks for an API key on stdin; an empty line skips it (keys come from the environment)
        result = CliRunner().invoke(_openkb(), ["init", "--model", plan.model, "--language", LANGUAGES[plan.language]],
                                    input="\n")
    if result.exit_code != 0 or not config_path.is_file():
        raise SystemExit(f"openkb init failed:\n{result.output}\n{result.exception or ''}")


def check_traditional(wiki: Path, convert: bool) -> dict:
    """Simplified characters in the compiled pages (sources/ is the original text and
    is left alone). With convert, pages that have any are converted to 繁體 in place."""
    if not zh.available():
        return {"checked": False, "reason": "opencc not installed"}
    flagged: dict[str, list[str]] = {}
    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(wiki).as_posix()
        if rel.startswith("sources/"):
            continue
        bad = zh.simplified_chars(path.read_text(encoding="utf-8"))
        if bad:
            flagged[rel] = sorted(bad)
    converted = []
    if convert:
        for rel in flagged:
            p = wiki / rel
            p.write_text(zh.to_traditional(p.read_text(encoding="utf-8")), encoding="utf-8")
            converted.append(rel)
    return {"checked": True, "pages_with_simplified": len(flagged), "examples": dict(list(flagged.items())[:10]),
            "converted": converted}


def compile_kb(plan: BuildPlan, inputs: list[PreparedInput], *, to_traditional: bool = True) -> dict:
    """Run OpenKB on every input, recording the tokens of each LLM call; returns build.json."""
    import litellm

    from .usage import UsageLog, litellm_logger

    cli = _openkb()
    init_kb(plan)
    log = UsageLog(plan.root / "compile_usage.jsonl")
    logger = litellm_logger(log)
    litellm.callbacks = [*(litellm.callbacks or []), logger]
    started, t0 = time.strftime("%Y-%m-%d %H:%M:%S"), time.time()
    failed = []
    try:
        for i, inp in enumerate(inputs, 1):
            log.current = Path(inp.path).name
            print(f"\n[{i}/{len(inputs)}] openkb add {log.current}")
            try:
                cli.main(["--kb-dir", str(plan.root), "add", inp.path], standalone_mode=False)
            except Exception as e:  # one bad file should not lose the cost record of the others
                print(f"  failed: {type(e).__name__}: {e}")
                failed.append({"file": log.current, "error": f"{type(e).__name__}: {e}"})
    finally:
        litellm.callbacks = [c for c in litellm.callbacks if c is not logger]

    totals = log.totals(plan.model)
    wiki = plan.root / "wiki"
    manifest_path = plan.root / MANIFEST
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    this_run = {"started": started, "duration_s": round(time.time() - t0, 1), "calls": totals["calls"],
                "usage": totals["usage"], "cost_usd": totals["cost_usd"], "per_input": totals["per_input"],
                "failed_calls": totals["failed_calls"], "failed_inputs": failed}
    runs = [*previous.get("runs", []), this_run]  # a re-run only compiles inputs OpenKB has not seen
    usage: dict = {}
    for r in runs:
        for k, v in r["usage"].items():
            usage[k] = usage.get(k, 0) + v
    costs = [r["cost_usd"] for r in runs]
    from ..query.metrics import wiki_metrics
    from ..query.tools import fingerprint
    built = (wiki / "index.md").is_file()
    manifest = {
        "name": plan.name, "profile": plan.profile, "description": plan.description,
        "model": plan.model, "language": plan.language, "openkb_language": LANGUAGES[plan.language],
        "source_dir": str(plan.source_dir), "inputs": [i.to_dict() for i in inputs],
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "calls": sum(r["calls"] for r in runs), "usage": usage,
        "cost_usd": None if None in costs else round(sum(costs), 4),
        "traditional_check": check_traditional(wiki, to_traditional) if plan.language == "zh-Hant" else None,
        "wiki_fingerprint": fingerprint(wiki) if built else None,
        "wiki_metrics": wiki_metrics(wiki) if built else None,
        "openkb_version": _openkb_version(),
        "runs": runs,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _openkb_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("openkb")
    except Exception:
        return None
