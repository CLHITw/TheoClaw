"""Record the tokens of every LLM call OpenKB makes while compiling.

OpenKB calls models through LiteLLM, so a LiteLLM callback sees every call (summary,
concept and entity pages, PageIndex trees). Each call is written to
compile_usage.jsonl with the input file being compiled at the time.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ...common.pricing import add_usage, cost
from ...llm.usage import get_field as _get, normalize_litellm_usage


class UsageLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.current: str | None = None  # the input file being compiled
        self.records: list[dict] = []
        self.failures = 0
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def record(self, kwargs: dict, response, start_time=None, end_time=None) -> None:
        rid = _get(response, "id") or (kwargs or {}).get("litellm_call_id")
        with self._lock:
            if rid and rid in self._seen:  # LiteLLM may report one call to both its sync and async hooks
                return
            if rid:
                self._seen.add(rid)
            rec = {"input": self.current, "model": (kwargs or {}).get("model"),
                   **normalize_litellm_usage(_get(response, "usage"))}
            if start_time is not None and end_time is not None:
                try:
                    rec["latency_s"] = round((end_time - start_time).total_seconds(), 2)
                except (AttributeError, TypeError):
                    pass
            self.records.append(rec)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def failed(self, kwargs: dict | None = None) -> None:
        key = f"fail:{(kwargs or {}).get('litellm_call_id')}"
        with self._lock:
            if key != "fail:None" and key in self._seen:
                return
            self._seen.add(key)
            self.failures += 1

    def totals(self, default_model: str) -> dict:
        """Totals overall and per input file, with costs priced by each call's model."""
        overall: dict = {"calls": 0, "usage": {}, "cost_usd": 0.0}
        per_input: dict[str, dict] = {}
        for r in self.records:
            model = r.get("model") or default_model
            c = cost(r, model)
            for bucket in (overall, per_input.setdefault(r["input"] or "?", {"calls": 0, "usage": {}, "cost_usd": 0.0})):
                bucket["calls"] += 1
                add_usage(bucket["usage"], r)
                bucket["cost_usd"] = None if c is None or bucket["cost_usd"] is None else bucket["cost_usd"] + c
        return {**overall, "per_input": per_input, "failed_calls": self.failures}


def litellm_logger(log: UsageLog):
    """A LiteLLM CustomLogger that forwards successes and failures to ``log``."""
    from litellm.integrations.custom_logger import CustomLogger

    class _Logger(CustomLogger):
        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            log.record(kwargs, response_obj, start_time, end_time)

        async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
            log.record(kwargs, response_obj, start_time, end_time)

        def log_failure_event(self, kwargs, response_obj, start_time, end_time):
            log.failed(kwargs)

        async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
            log.failed(kwargs)

    return _Logger()
