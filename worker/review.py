"""List messages that were held (possible injection / too many drinks), unsure or failed; settle them by hand.

python -m worker.review                      # list
python -m worker.review approve <message_id> # accept Claude's count
python -m worker.review zero <message_id>    # count nothing for it
"""
from __future__ import annotations
import json
import sys

from . import db
from .process import release_held


def main() -> None:
    conn = db.connect()
    args = sys.argv[1:]
    if len(args) == 2 and args[0] in {"approve", "zero"}:
        action, mid = args
        if action == "zero":
            conn.execute("UPDATE drinks SET voided=1 WHERE message_id=?", (mid,))
            conn.execute("UPDATE messages SET status='not_drink' WHERE id=?", (mid,))
        else:
            release_held(conn, mid)  # counts held drinks too
        conn.commit()
        print(f"{action}d {mid}")
        return

    rows = conn.execute(
        "SELECT id, sender_name, text, photo, status, error, extraction FROM messages "
        "WHERE status IN ('held','needs_review','error') ORDER BY ts"
    ).fetchall()
    if not rows:
        print("Nothing to review.")
    for r in rows:
        pts = conn.execute("SELECT COALESCE(SUM(points),0) s FROM drinks WHERE message_id=? AND voided=0",
                           (r["id"],)).fetchone()["s"]
        ex = json.loads(r["extraction"]) if r["extraction"] else {}
        why = "; ".join(ex.get("hold_reasons", [])) or ex.get("reasoning") or r["error"]
        if r["status"] == "held":
            pts = sum(d["points"] for d in conn.execute("SELECT points FROM drinks WHERE message_id=?", (r["id"],)))
        print(f'[{r["id"]}] {r["status"]} | {r["sender_name"]}: "{r["text"]}" '
              f'{"(photo: " + r["photo"] + ")" if r["photo"] else ""}\n   '
              f'{"would add" if r["status"] == "held" else "counted"} {pts} pts. {why}\n')


if __name__ == "__main__":
    main()
