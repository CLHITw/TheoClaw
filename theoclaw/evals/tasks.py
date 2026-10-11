"""Task file loading. Format (YAML list):

- id: quote-john-3-16          # unique, stable across versions of the task set
  category: quote              # free label; the report slices by it
  prompt: 請引用約翰福音 3:16 的經文。
  graders: [cites_expected_refs]
  expect:                      # anything your graders need, free-form
    refs: [約翰福音 3:16]
  fault: {tool: lookup_verse, mode: error, calls: all}   # optional
  notes: why this task exists  # optional
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .faults import FaultSpec


@dataclass
class Task:
    id: str
    prompt: str
    graders: list[str]
    category: str = "general"
    expect: dict = field(default_factory=dict)
    fault: FaultSpec | None = None
    notes: str = ""


def load_tasks(path: Path | str) -> list[Task]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    tasks, seen = [], set()
    for i, item in enumerate(raw):
        missing = {"id", "prompt", "graders"} - set(item)
        if missing:
            raise ValueError(f"task #{i + 1} is missing {sorted(missing)}")
        if item["id"] in seen:
            raise ValueError(f"duplicate task id {item['id']!r}")
        seen.add(item["id"])
        fault = item.get("fault")
        tasks.append(Task(
            id=str(item["id"]),
            prompt=str(item["prompt"]).strip(),
            graders=list(item["graders"]),
            category=str(item.get("category", "general")),
            expect=dict(item.get("expect") or {}),
            fault=FaultSpec.from_dict(fault) if fault else None,
            notes=str(item.get("notes", "")),
        ))
    return tasks
