"""Run the RAWAA analysis + scheduling pipeline once.

Uses the same settings as the web service (DATABASE_URL, ...). Safe to run any number of times:
alerts, schedule entries and predictions are de-duplicated in the database.

    python scripts/run_pipeline.py

On Render it can be used as the command of an (optional, paid) Cron Job.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402,F401  (opens the database and applies migrations)
import intelligence_api  # noqa: E402

result = intelligence_api.run_pipeline('cron')
print(json.dumps(result, ensure_ascii=False))
sys.exit(1 if result.get('skipped') else 0)
