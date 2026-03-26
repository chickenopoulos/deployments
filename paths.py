from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR
STATE_DIR = DATA_DIR / "state"
LOG_DIR = ROOT / "logs"

for _path in (DATA_DIR, STATE_DIR, LOG_DIR):
    _path.mkdir(parents=True, exist_ok=True)
