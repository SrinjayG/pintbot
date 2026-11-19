"""Worker loop: ingest → extract with Claude → count → Monday tally.

Run from pintbot/:  python -m worker.main
Send this week's report right now:  python -m worker.main --tally-now
"""
from __future__ import annotations
import sys
import time
from datetime import datetime

from . import config, db
from .process import ingest_inbox, process_pending
from .tally import build_report, send_ntfy, tally_due, week_bounds

POLL_SECONDS = 5


def run_once(conn) -> None:
    n = ingest_inbox(conn)
    if n:
        print(f"ingested {n} message(s)")
    for msg_id, status in process_pending(conn):
        print(f"  {msg_id}: {status}")

    now = datetime.now(config.TZ)
    key = tally_due(conn, now)
    if key:
        title, body = build_report(conn, now)
        send_ntfy(title, body)
        db.set_meta(conn, "last_tally_week", key)
        print(f"sent weekly tally for week starting {key}")


def main() -> None:
    conn = db.connect()
    config.INBOX.mkdir(parents=True, exist_ok=True)

    if "--tally-now" in sys.argv:
        ingest_inbox(conn)
        process_pending(conn)
        title, body = build_report(conn, datetime.now(config.TZ))
        send_ntfy(title, body)
        print(title + "\n" + body)
        return

    # First ever run: don't fire a report for a week from before the bot existed.
    if db.get_meta(conn, "last_tally_week") is None:
        start, _ = week_bounds(datetime.now(config.TZ))
        db.set_meta(conn, "last_tally_week", start.strftime("%Y-%m-%d"))

    print(f"worker running (model {config.CLAUDE_MODEL}); watching {config.INBOX}")
    while True:
        try:
            run_once(conn)
        except Exception as e:
            print("loop error:", e)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
