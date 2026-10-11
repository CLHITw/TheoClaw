"""Where things live. Every default path is relative to the project root, so the
commands work from any working directory."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"            # scripture lookup data (scripts/build_data.py)
CONFIG_DIR = ROOT / "config"        # LLM settings and prices, knowledge-base profiles, human rubric
TASKS_DIR = ROOT / "tasks"          # test questions
GRADERS_DIR = ROOT / "graders"      # graders (Python)
KNOWLEDGE_DIR = ROOT / "knowledge"  # compiled knowledge bases, one folder each
RUNS_DIR = ROOT / "runs"            # eval runs and the ask log
ENV_FILE = ROOT / ".env"            # API keys (git-ignored)


def llm_config_path() -> Path:
    """config/llm.yaml, or the file named by THEOCLAW_LLM_CONFIG (e.g. a cheaper set of models)."""
    p = Path(os.environ.get("THEOCLAW_LLM_CONFIG") or CONFIG_DIR / "llm.yaml")
    return p if p.is_absolute() else ROOT / p
