"""LangSmith tracing. LangChain traces automatically when LANGSMITH_TRACING=true and
LANGSMITH_API_KEY are set. @traceable wraps one agent run as the parent trace.
Without keys everything still works - tracing is simply off."""
import json
import os
import time
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree


def tracing_enabled():
    val = (os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2") or "").strip().lower()
    return val in ("true", "1", "yes") and bool(os.getenv("LANGSMITH_API_KEY"))


def current_trace_id():
    """ID of the active LangSmith run, or None when tracing is off."""
    if not tracing_enabled():
        return None
    try:
        rt = get_current_run_tree()
        return str(rt.trace_id) if rt else None
    except Exception:
        return None


def tag_run(**metadata):
    """Attach metadata (session id, pseudonymous student id) to the current trace."""
    try:
        rt = get_current_run_tree()
        if rt and tracing_enabled():
            rt.metadata.update(metadata)
    except Exception:
        pass


def log_run(record):
    """Append one privacy-safe JSON line per run to logs/traces.jsonl. Never raises.
    The question text is NOT stored (it may contain sensitive details), only its length."""
    try:
        import config
        config.LOG_PATH.parent.mkdir(exist_ok=True)
        with open(config.LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **record}) + "\n")
    except Exception:
        pass


__all__ = ["traceable", "tracing_enabled", "current_trace_id", "tag_run", "log_run"]
