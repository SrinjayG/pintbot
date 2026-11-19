"""The challenge rules, in plain code. Claude never decides points; this does.

Rules: 1 drink = 1 pint. Beer (4.5% ABV+), a glass of wine, a shot or a mixed
drink each count 1. Non-alcoholic versions count half.
"""
from __future__ import annotations
from . import config

FULL_POINT_TYPES = {"wine", "shot", "mixed_drink", "other"}
BEER_TYPES = {"beer", "cider"}


def points_for(drink: dict) -> float:
    qty = max(int(drink.get("quantity") or 1), 1)

    if drink.get("non_alcoholic"):
        return qty * config.NON_ALCOHOLIC_POINTS

    kind = drink.get("drink_type")
    if kind in BEER_TYPES:
        abv = drink.get("abv")
        # Unknown ABV: assume a normal beer (most are ≥4.5%).
        if abv is not None and abv < config.BEER_MIN_ABV:
            return qty * config.LOW_ABV_BEER_POINTS
        return qty * 1.0
    if kind in FULL_POINT_TYPES:
        return qty * 1.0
    return 0.0  # unknown type: count nothing rather than guess


def points_for_message(extraction: dict) -> float:
    if not extraction.get("is_drink_log"):
        return 0.0
    return sum(points_for(d) for d in extraction.get("drinks", []))
