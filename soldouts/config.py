"""Settings and assumptions in one place. Every number here is a decision; see README."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PACK = Path(os.environ.get("SOLDOUTS_PACK", DATA / "pack"))

# Rep time. 12 minutes is what routing books per task (config/routing.json).
MINUTES_PER_TASK = 12
# ASSUMPTION until Priya/Dan give a real figure: loaded cost of a rep hour.
REP_HOURLY_COST_GBP = float(os.environ.get("REP_HOURLY_COST_GBP", 20))

# Below this expected value a call isn't worth the rep's time.
MIN_CALL_VALUE_GBP = 0.0

# Size bands where an auto-replenish schedule makes the restock task skippable.
# A is kept: only 48 called A-band auto sold-outs, uplift CI 2.7-27.8, too wide to drop.
AUTO_SKIP_BANDS = {"B", "C", "D"}

# Text signals older than this are ignored.
SIGNAL_MAX_AGE_DAYS = 365


def load_uplift():
    return json.loads((DATA / "uplift.json").read_text())


def load_env_file():
    """Read KEY=VALUE lines from .env into os.environ (no dependency on python-dotenv)."""
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
