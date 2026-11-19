"""Settings, loaded from pintbot/.env."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
INBOX = DATA / "inbox"
DB_PATH = DATA / "pintbot.db"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
# Beer ABV lookup via Claude web search ($10 per 1,000 searches + tokens; each beer searched once).
BEER_LOOKUP = os.getenv("BEER_LOOKUP", "on").lower() in {"on", "true", "1", "yes"}
LOOKUP_MODEL = os.getenv("LOOKUP_MODEL", CLAUDE_MODEL)

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")

TZ = ZoneInfo("Asia/Hong_Kong")
TALLY_WEEKDAY = 0  # Monday
TALLY_HOUR = 2     # 02:00 HKT

GOAL_PINTS = 1_000_000
GOAL_DEADLINE = date.fromisoformat(os.getenv("GOAL_DEADLINE", "2036-12-31"))

# --- Challenge rules (see worker/rules.py) ---
# Your rule says beer counts when it's 4.5% ABV or stronger. What a weaker beer
# is worth isn't defined yet, so it's a setting. Decide with the group.
BEER_MIN_ABV = 4.5
LOW_ABV_BEER_POINTS = float(os.getenv("LOW_ABV_BEER_POINTS", "0.5"))
NON_ALCOHOLIC_POINTS = 0.5

CONTEXT_MESSAGES = 8  # earlier messages shown to Claude (for "+1", "same", corrections)
CORRECTION_WINDOW_HOURS = 12
MAX_RETRIES = 3
# More drinks than this in ONE message is held for human review (anti-injection, anti-typo).
MAX_DRINKS_PER_MESSAGE = int(os.getenv("MAX_DRINKS_PER_MESSAGE", "8"))
