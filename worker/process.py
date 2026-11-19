"""Ingest listener output and turn messages into counted drinks."""
from __future__ import annotations
import hashlib
import json
import time

from . import config, rules
from .beer_lookup import is_lookupable, lookup_abv
from .extract import extract as claude_extract
from .guard import hold_reasons


def ingest_inbox(conn) -> int:
    """Move JSON files written by the listener into the messages table."""
    n = 0
    for f in sorted(config.INBOX.glob("*.json")):
        rec = json.loads(f.read_text())
        photo_hash = None
        if rec.get("photo"):
            p = config.ROOT / rec["photo"]
            if p.exists():
                photo_hash = hashlib.sha256(p.read_bytes()).hexdigest()
        conn.execute(
            "INSERT OR IGNORE INTO messages(id, sender_id, sender_name, ts, text, photo, photo_hash, quoted_id) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (rec["id"], rec["sender_id"], rec.get("sender_name") or rec["sender_id"], rec["timestamp"],
             rec.get("text") or "", rec.get("photo"), photo_hash, rec.get("quoted_id")),
        )
        conn.commit()
        f.rename(f.with_suffix(".done"))
        n += 1
    return n


def _context(conn, msg) -> list[dict]:
    rows = conn.execute(
        "SELECT id, sender_name, text FROM messages WHERE ts <= ? AND id != ? ORDER BY ts DESC LIMIT ?",
        (msg["ts"], msg["id"], config.CONTEXT_MESSAGES),
    ).fetchall()
    out = []
    for r in reversed(rows):
        drinks = conn.execute(
            "SELECT quantity, drink_type, non_alcoholic FROM drinks WHERE message_id=? AND voided=0", (r["id"],)
        ).fetchall()
        summary = ", ".join(
            f'{d["quantity"]}x {d["drink_type"]}{" (non-alc)" if d["non_alcoholic"] else ""}' for d in drinks
        )
        out.append({"id": r["id"], "sender_name": r["sender_name"], "text": r["text"], "drinks_summary": summary})
    return out


def _void_previous(conn, msg) -> None:
    """A correction replaces the sender's most recent counted log within the window."""
    since = msg["ts"] - config.CORRECTION_WINDOW_HOURS * 3600
    prev = conn.execute(
        "SELECT id FROM messages WHERE sender_id=? AND ts>=? AND ts<? AND status IN ('counted','needs_review') "
        "ORDER BY ts DESC LIMIT 1",
        (msg["sender_id"], since, msg["ts"]),
    ).fetchone()
    if prev:
        conn.execute("UPDATE drinks SET voided=1 WHERE message_id=?", (prev["id"],))
        conn.execute("UPDATE messages SET status='corrected' WHERE id=?", (prev["id"],))


def enrich_abv(conn, drinks: list[dict], lookup_fn=lookup_abv) -> None:
    """Fill in missing beer ABVs by name (cache, then web search). Never fails the message."""
    for d in drinks:
        if d.get("abv") is not None:
            d["abv_source"] = "post"
            continue
        d["abv_source"] = None
        if (not config.BEER_LOOKUP or d.get("non_alcoholic")
                or d.get("drink_type") not in rules.BEER_TYPES or not is_lookupable(d.get("name"))):
            continue
        try:
            abv, source = lookup_fn(conn, d["name"])
        except Exception as e:
            print(f"  beer lookup failed for {d['name']!r}: {e}")
            continue
        if abv is not None:
            d["abv"], d["abv_source"] = abv, source


def process_message(conn, msg, extract_fn=claude_extract, lookup_fn=lookup_abv) -> str:
    """Process one pending message. Returns its new status."""
    if msg["photo_hash"]:
        dup = conn.execute(
            "SELECT id FROM messages WHERE photo_hash=? AND id != ? AND ts <= ? AND status IN ('counted','needs_review')",
            (msg["photo_hash"], msg["id"], msg["ts"]),
        ).fetchone()
        if dup:
            conn.execute("UPDATE messages SET status='duplicate_photo', processed_at=? WHERE id=?",
                         (int(time.time()), msg["id"]))
            conn.commit()
            return "duplicate_photo"

    extraction = extract_fn(dict(msg), _context(conn, msg))

    reasons = hold_reasons(msg["text"], extraction)
    if reasons:
        extraction["hold_reasons"] = reasons

    if not extraction.get("is_drink_log") or not extraction.get("drinks"):
        status = "held" if reasons else "not_drink"
    else:
        enrich_abv(conn, extraction["drinks"], lookup_fn)  # before any writes below
        held = bool(reasons)
        if extraction.get("corrects_previous") and not held:
            _void_previous(conn, msg)  # a held correction is applied only once approved
        for d in extraction["drinks"]:
            conn.execute(
                "INSERT INTO drinks(message_id, sender_id, sender_name, ts, drink_type, name, abv, abv_source, quantity, "
                "non_alcoholic, points, voided) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (msg["id"], msg["sender_id"], msg["sender_name"], msg["ts"], d.get("drink_type"), d.get("name"),
                 d.get("abv"), d.get("abv_source"), d.get("quantity") or 1, int(bool(d.get("non_alcoholic"))),
                 rules.points_for(d), int(held)),  # held drinks are stored but don't count yet
            )
        if held:
            status = "held"
        else:
            status = "needs_review" if extraction.get("confidence") == "low" else "counted"

    conn.execute(
        "UPDATE messages SET status=?, extraction=?, processed_at=?, error=NULL WHERE id=?",
        (status, json.dumps(extraction), int(time.time()), msg["id"]),
    )
    conn.commit()
    return status


def release_held(conn, message_id: str) -> None:
    """Human approved a held message: count its drinks (and apply its correction, if any)."""
    msg = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    if not msg:
        raise ValueError(f"no message {message_id}")
    extraction = json.loads(msg["extraction"] or "{}")
    if msg["status"] == "held" and extraction.get("corrects_previous"):
        _void_previous(conn, msg)  # held corrections weren't applied yet
    conn.execute("UPDATE drinks SET voided=0 WHERE message_id=?", (message_id,))
    conn.execute("UPDATE messages SET status='counted' WHERE id=?", (message_id,))
    conn.commit()


def process_pending(conn, extract_fn=claude_extract, lookup_fn=lookup_abv) -> list[tuple[str, str]]:
    results = []
    pending = conn.execute(
        "SELECT * FROM messages WHERE status='pending' OR (status='error' AND retries < ?) ORDER BY ts",
        (config.MAX_RETRIES,),
    ).fetchall()
    for msg in pending:
        try:
            results.append((msg["id"], process_message(conn, msg, extract_fn, lookup_fn)))
        except Exception as e:  # keep going; retry later
            conn.rollback()
            conn.execute("UPDATE messages SET status='error', retries=retries+1, error=? WHERE id=?",
                         (str(e)[:500], msg["id"]))
            conn.commit()
            results.append((msg["id"], f"error: {e}"))
    return results
