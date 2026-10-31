"""All settings in one place, read from .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Normalize LangSmith & LangChain tracing environment variables
# Note: LangSmith requires lowercase "true" for TRACING and TRACING_V2
tracing_flag = (os.getenv("LANGSMITH_TRACING") or "").strip().lower()
if tracing_flag in ("true", "1", "yes"):
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"

api_key = os.getenv("LANGSMITH_API_KEY")
if api_key:
    os.environ["LANGSMITH_API_KEY"] = api_key.strip()
    os.environ["LANGCHAIN_API_KEY"] = api_key.strip()
else:
    os.environ.pop("LANGCHAIN_API_KEY", None)

project = os.getenv("LANGSMITH_PROJECT") or "college-policy-vectorless-rag"
os.environ["LANGSMITH_PROJECT"] = project
os.environ["LANGCHAIN_PROJECT"] = project

if not os.getenv("LANGCHAIN_ENDPOINT"):
    os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

ROOT = Path(__file__).parent
DB_PATH = os.getenv("DB_PATH", str(ROOT / "student_support.db"))
POLICY_PATH = ROOT / "data" / "student_policy.txt"
STUDENTS_JSON = ROOT / "data" / "students.json"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_STEPS = int(os.getenv("MAX_STEPS", "5"))      # max tool-call rounds
MIN_SCORE = float(os.getenv("MIN_SCORE", "1.0"))  # BM25 relevance threshold
TOP_K = 3
SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(24).hex()  # signs the login cookie
LOG_PATH = ROOT / "logs" / "traces.jsonl"  # one JSON line per agent run (works without LangSmith)
