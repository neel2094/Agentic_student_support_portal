import os
import sys
import tempfile
from pathlib import Path

os.environ["LANGSMITH_TRACING"] = "false"      # tests must never call LangSmith
os.environ["LANGCHAIN_TRACING_V2"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

config.LOG_PATH = Path(tempfile.mkdtemp()) / "traces.jsonl"  # keep test runs out of the real trace file
