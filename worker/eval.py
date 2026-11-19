"""Measure extraction accuracy on hand-labelled messages.

Each line of the eval file is JSON:
  {"id": "...", "sender_name": "...", "text": "...", "photo": "evals/photos/x.jpg" (optional),
   "context": [{"id","sender_name","text","drinks_summary"}] (optional), "expected_points": 1.0}

python -m worker.eval                         # uses evals/labelled.jsonl
python -m worker.eval evals/labelled.example.jsonl
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from . import config, db, rules
from .extract import extract
from .process import enrich_abv


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else config.ROOT / "evals" / "labelled.jsonl"
    cases = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    cases = [c for c in cases if c.get("expected_points") is not None]
    if not cases:
        sys.exit(f"No labelled cases in {path} (fill in expected_points).")

    config.DATA.mkdir(parents=True, exist_ok=True)
    conn = db.connect(config.DATA / "eval_cache.db")  # beer lookups cached across eval runs
    correct, abs_err, misses = 0, 0.0, []
    for c in cases:
        msg = {"id": c["id"], "sender_name": c.get("sender_name", "someone"), "text": c.get("text", ""),
               "photo": c.get("photo"), "quoted_id": c.get("quoted_id")}
        try:
            ex = extract(msg, c.get("context", []))
            enrich_abv(conn, ex.get("drinks", []))
            got = rules.points_for_message(ex)
        except Exception as e:
            ex, got = {"reasoning": f"ERROR {e}"}, None
        ok = got is not None and abs(got - c["expected_points"]) < 1e-9
        correct += ok
        abs_err += abs((got or 0) - c["expected_points"])
        if not ok:
            misses.append((c, got, ex.get("reasoning")))
        print(f'{"✓" if ok else "✗"} [{c["id"]}] expected {c["expected_points"]} got {got}')

    n = len(cases)
    print(f"\nAccuracy: {correct}/{n} = {correct / n:.0%}   (mean abs error {abs_err / n:.2f} pints/message)")
    for c, got, why in misses:
        print(f'\nMISS [{c["id"]}] "{c.get("text")}" expected {c["expected_points"]}, got {got}\n   Claude: {why}')


if __name__ == "__main__":
    main()
