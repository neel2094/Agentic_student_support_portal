"""Usage:  python scripts/initialize_db.py          (safe, keeps data)
          python scripts/initialize_db.py --reset  (DEV ONLY: wipes everything)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import database

database.init_db(reset="--reset" in sys.argv)
print("Database ready.", "(reset)" if "--reset" in sys.argv else "")
