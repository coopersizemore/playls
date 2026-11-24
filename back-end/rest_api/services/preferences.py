"""Tweakable behavior: built-in defaults, the allowed choices, and how a value is resolved.

Account settings live on `users` and rotation overrides on `rotation`. NULL means "not set":
a rotation falls back to its owner's account setting, which falls back to the default here.
Stored values outside the allowed choices (none should exist; the API validates) also fall
back, so a bad row can't break reviewing. Pure: no DB or network.
"""
from typing import Any, Dict, Optional, Tuple

# name -> (default, allowed choices)
ACCOUNT: Dict[str, Tuple[Any, Tuple[Any, ...]]] = {
    # Reviewing
    "super_keep_multiplier": (3, (2, 3, 5)),  # a super keep waits this many intervals
    "skip_hold_days": (1, (1, 3, 7)),  # a skipped song is held back this many days (1 = until tomorrow)
    "review_order": ("overdue", ("overdue", "oldest", "shuffle")),
    "default_interval_hours": (30 * 24, None),  # any interval the picker allows (validated by the API)
    # Restocking
    "deck_size": (30, (10, 20, 30, 50)),
    "discovery_percent": (33, (15, 33, 60)),  # For you: share of "new to you" songs
    "not_now_percent": (50, (75, 50, 25)),  # weight left after a fresh Not now (lower = stronger)
    "bring_back_recovery_days": (90, (30, 90, 180)),  # days until a removed song is at full weight
}

# Settings a rotation can override (NULL = the account setting)
ROTATION_OVERRIDES = ("super_keep_multiplier", "skip_hold_days", "review_order")

# Auto rotations only (no account-wide equivalent)
AUTO: Dict[str, Tuple[Any, Tuple[Any, ...]]] = {
    "return_cooldown_days": (28, (14, 28, 56)),
    "pick_percent": (10, (0, 10, 25)),
    "bring_back_percent": (20, (0, 20, 40)),
}

NO_LIMIT = 0  # rotation.review_limit: 0 = no daily limit for this rotation


def _valid(value: Any, choices: Optional[Tuple[Any, ...]]) -> bool:
    if value is None:
        return False
    return choices is None or value in choices


def account(user: Any, name: str) -> Any:
    default, choices = ACCOUNT[name]
    value = getattr(user, name, None)
    return value if _valid(value, choices) else default


def account_settings(user: Any) -> Dict[str, Any]:
    return {name: account(user, name) for name in ACCOUNT}


def for_rotation(rotation: Any, name: str) -> Any:
    """A review setting for this rotation: its override, else the owner's account setting."""
    if name in AUTO:
        default, choices = AUTO[name]
        value = getattr(rotation, name, None)
        return value if _valid(value, choices) else default
    if name in ROTATION_OVERRIDES:
        _, choices = ACCOUNT[name]
        value = getattr(rotation, name, None)
        if _valid(value, choices):
            return value
    return account(rotation.owner, name)


def review_limit(rotation: Any) -> Optional[int]:
    """Songs offered per day for this rotation (None = no limit): its override, else the account's."""
    override = getattr(rotation, "review_limit", None)
    if override is not None:
        return None if override == NO_LIMIT else override
    return rotation.owner.review_limit


def overrides(rotation: Any) -> Dict[str, Any]:
    """The rotation's raw overrides (None = uses the account setting / default), for its edit dialog."""
    names = (*ROTATION_OVERRIDES, "review_limit", *AUTO)
    return {name: getattr(rotation, name, None) for name in names}
