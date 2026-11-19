"""Weekly tally + ntfy push notification."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import json
import urllib.request

from . import config
from .db import get_meta


def week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """The last full Mon 00:00 → Mon 00:00 week (HKT) before `now`."""
    now = now.astimezone(config.TZ)
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return this_monday - timedelta(days=7), this_monday


def _sum(conn, start=None, end=None) -> float:
    q, args = "SELECT COALESCE(SUM(points),0) AS s FROM drinks WHERE voided=0", []
    if start is not None:
        q += " AND ts >= ?"; args.append(int(start.timestamp()))
    if end is not None:
        q += " AND ts < ?"; args.append(int(end.timestamp()))
    return conn.execute(q, args).fetchone()["s"]


def required_weekly_pace(total: float, today: date) -> float:
    weeks_left = max((config.GOAL_DEADLINE - today).days / 7, 1)
    return max(config.GOAL_PINTS - total, 0) / weeks_left


def fmt(x: float) -> str:
    return f"{x:,.1f}".rstrip("0").rstrip(".")


def build_report(conn, now: datetime) -> tuple[str, str]:
    start, end = week_bounds(now)
    week = _sum(conn, start, end)
    prev = _sum(conn, start - timedelta(days=7), start)
    total = _sum(conn, end=end)

    leaders = conn.execute(
        "SELECT sender_name, SUM(points) AS p FROM drinks WHERE voided=0 AND ts>=? AND ts<? "
        "GROUP BY sender_id ORDER BY p DESC LIMIT 3",
        (int(start.timestamp()), int(end.timestamp())),
    ).fetchall()
    top_beer = conn.execute(
        "SELECT name, SUM(quantity) AS n FROM drinks WHERE voided=0 AND drink_type IN ('beer','cider') "
        "AND name IS NOT NULL AND ts>=? AND ts<? GROUP BY lower(name) ORDER BY n DESC LIMIT 1",
        (int(start.timestamp()), int(end.timestamp())),
    ).fetchone()
    review = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE status IN ('held','needs_review','error')"
    ).fetchone()["n"]

    delta = week - prev
    arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
    title = f"🍺 Million Pint Challenge: {start:%d %b}–{(end - timedelta(days=1)):%d %b}"
    lines = [
        f"This week: {fmt(week)} pints ({arrow}{fmt(abs(delta))} vs last week)",
        f"All-time: {fmt(total)} / {config.GOAL_PINTS:,} ({total / config.GOAL_PINTS:.4%})",
        f"Pace needed to finish by {config.GOAL_DEADLINE.year}: {fmt(required_weekly_pace(total, end.date()))} pints/week",
    ]
    if leaders:
        lines.append("Top this week: " + ", ".join(f"{i+1}. {r['sender_name']} {fmt(r['p'])}" for i, r in enumerate(leaders)))
    if top_beer:
        lines.append(f"Beer of the week: {top_beer['name']} ({top_beer['n']})")
    if review:
        lines.append(f"⚠️ {review} message(s) need review: python -m worker.review")
    return title, "\n".join(lines)


def send_ntfy(title: str, body: str) -> None:
    if not config.NTFY_TOPIC:
        print("(NTFY_TOPIC not set, printing instead)\n" + title + "\n" + body)
        return
    # JSON publishing keeps emoji in the title safe (HTTP headers are latin-1 only).
    payload = json.dumps({"topic": config.NTFY_TOPIC, "title": title, "message": body, "tags": ["beer"]})
    req = urllib.request.Request(
        config.NTFY_SERVER,
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=15).read()


def tally_due(conn, now: datetime) -> str | None:
    """Return the week key if this week's Monday-2am tally hasn't been sent yet."""
    now = now.astimezone(config.TZ)
    start, _ = week_bounds(now)
    key = start.strftime("%Y-%m-%d")
    after_send_time = now.weekday() > config.TALLY_WEEKDAY or now.hour >= config.TALLY_HOUR
    if after_send_time and get_meta(conn, "last_tally_week") != key:
        return key
    return None
