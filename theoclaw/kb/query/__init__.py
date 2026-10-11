"""Reading a compiled OpenKB wiki: the agent's kb tools, plus a standalone command line.

    python -m theoclaw.kb.query ls
    python -m theoclaw.kb.query census wesley-core.en.qwen3.8-max
    python -m theoclaw.kb.query ask wesley-core.en.qwen3.8-max "衛斯理如何定義基督徒的完全？" --model deepseek-flash
"""

from . import tools
from .kb import KnowledgeBase, list_knowledge_bases

__all__ = ["tools", "KnowledgeBase", "list_knowledge_bases"]
