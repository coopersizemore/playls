"""Pure rules for auto rotations (no DB or network), per docs/DESIGN.md "Auto rotations".

An auto rotation keeps its playlist at `target_size` songs. Every `interval_hours` it
rotates out `rotate_percent` of the target (plus anything over the target) and restocks
back up to the target from For you, PlayLS picks and songs that rotated out a while ago.

Who leaves: oldest first, where a song's age counts from when it was added or last kept,
and runs at a third of the speed after a super keep. Songs kept since the last rotation
are protected from the next one. Unavailable songs leave first.
"""
import random
from collections.abc import Sequence
from datetime import datetime, timedelta

from rest_api.services.listening_logic import protected_by_plays

DEFAULT_TARGET_SIZE = 50
DEFAULT_ROTATE_PERCENT = 20
DEFAULT_INTERVAL_HOURS = 7 * 24

RETURN_COOLDOWN_DAYS = 28  # a rotated-out song can't come back for 4 weeks
PICK_CHANCE = 0.1  # each new slot has a 1 in 10 chance to be a live PlayLS pick
BRING_BACK_SHARE = 0.2  # and up to about 1 in 5 can be a song that rotated out before


def rotation_anchor(rotation) -> datetime:
    """When the current rotation period started."""
    return rotation.last_rotated_at or rotation.created_at


def next_rotation_at(rotation) -> datetime:
    return rotation_anchor(rotation) + timedelta(hours=rotation.interval_hours)


def is_rotation_due(rotation, now: datetime) -> bool:
    return next_rotation_at(rotation) <= now


def per_rotation(target_size: int, rotate_percent: int) -> int:
    """Songs swapped out each rotation (at least 1)."""
    return max(1, round(target_size * rotate_percent / 100))


def rotate_out_count(target_size: int, rotate_percent: int, active_count: int) -> int:
    """How many leave at a rotation: the usual share plus any excess over the target."""
    excess = max(0, active_count - target_size)
    return min(active_count, per_rotation(target_size, rotate_percent) + excess)


def is_protected(track, rotation) -> bool:
    """Kept (or super kept) since the last rotation: safe from the next one."""
    return track.last_kept_at is not None and track.last_kept_at > rotation_anchor(rotation)


def tenure_age(track, rotation, now: datetime) -> float:
    """Effective age in hours. Keeps restart the clock; a super keep slows it 3x."""
    if track.last_kept_at is not None:
        hours = (now - track.last_kept_at).total_seconds() / 3600
        return hours / max(getattr(track, "keep_multiplier", None) or 1, 1)
    since = track.added_at or rotation.created_at
    return (now - since).total_seconds() / 3600


def rotate_out_order(tracks: Sequence, rotation, now: datetime) -> list:
    """Active tracks in leaving order: unavailable first, then oldest; protected last."""
    return sorted(
        tracks,
        key=lambda t: (is_protected(t, rotation), t.is_playable, -tenure_age(t, rotation, now), t.title.lower()),
    )


def plan_rotate_out(
    tracks: Sequence, rotation, now: datetime, listening: dict | None = None, hold_cap: int = 0,
    protect_percent: int = 0,
) -> tuple[list, list]:
    """(leaving, held) for a rotation happening now.

    Never protected (kept) songs. With listening history (`listening`: {row id:
    SongListening}): the most played `protect_percent`% never leave, and a heavily played
    song whose turn it is may stay instead, at most `hold_cap` rotations in a row (its
    `listening_holds`); the next song in line leaves in its place. If there aren't enough
    others, held songs leave after all, so turnover never stalls.
    """
    n = rotate_out_count(rotation.target_size, rotation.rotate_percent, len(tracks))
    listening = listening or {}
    shielded = protected_by_plays(listening, [t.id for t in tracks], protect_percent)
    candidates = [
        t for t in rotate_out_order(tracks, rotation, now) if not is_protected(t, rotation) and t.id not in shielded
    ]
    leaving, held = [], []
    for t in candidates:
        if len(leaving) >= n:
            break
        s = listening.get(t.id)
        if s is not None and s.heavy and (getattr(t, "listening_holds", 0) or 0) < hold_cap:
            held.append(t)
            continue
        leaving.append(t)
    while len(leaving) < n and held:
        leaving.append(held.pop(0))
    return leaving, held


def choose_rotate_out(tracks: Sequence, rotation, now: datetime, **listening_args) -> list:
    """The songs leaving at a rotation happening now (never protected ones)."""
    return plan_rotate_out(tracks, rotation, now, **listening_args)[0]


def leaving_schedule(tracks: Sequence, rotation, now: datetime, **listening_args) -> dict[int, datetime]:
    """Projected leave time per track row id (an estimate: future restocks shift it).

    The next group leaves at the next rotation; after that, one group per interval. Songs
    held back this time are first in line for the one after.
    """
    next_at = max(next_rotation_at(rotation), now)
    period = timedelta(hours=rotation.interval_hours)
    step = per_rotation(rotation.target_size, rotation.rotate_percent)
    leaving, held = plan_rotate_out(tracks, rotation, now, **listening_args)
    leaving_ids = {t.id for t in leaving}
    held_ids = {t.id for t in held}
    order = rotate_out_order(tracks, rotation, now)
    rest = held + [t for t in order if t.id not in leaving_ids and t.id not in held_ids]
    schedule = {t_id: next_at for t_id in leaving_ids}
    for i, t in enumerate(rest):
        schedule[t.id] = next_at + period * (1 + i // step)
    return schedule


def leaving_next(tracks: Sequence, rotation, now: datetime, **listening_args) -> list:
    """Songs that would leave at the next rotation, in leaving order (the review queue)."""
    return plan_rotate_out(tracks, rotation, now, **listening_args)[0]


def allocate(
    slots: int, picks_available: int, bring_back_available: int, for_you_available: int, rng: random.Random,
    pick_chance: float = PICK_CHANCE, bring_back_share: float = BRING_BACK_SHARE,
) -> dict[str, int]:
    """Split new slots between sources. Shortfalls in one source spill into the others."""
    picks = min(picks_available, sum(1 for _ in range(slots) if rng.random() < pick_chance))
    expected_back = slots * bring_back_share
    bring_back = int(expected_back) + (1 if rng.random() < expected_back - int(expected_back) else 0)
    bring_back = min(bring_back_available, bring_back, slots - picks)
    for_you = min(for_you_available, slots - picks - bring_back)
    left = slots - picks - bring_back - for_you
    # Not enough For you songs: fall back to bring back, then picks
    extra = min(left, bring_back_available - bring_back)
    bring_back += extra
    left -= extra
    extra = min(left, picks_available - picks)
    picks += extra
    return {"picks": picks, "bring_back": bring_back, "suggested": for_you}


def cooled_down(removed_at: datetime | None, now: datetime, days: int = RETURN_COOLDOWN_DAYS) -> bool:
    """A removed song may return once the cooldown (4 weeks by default) has passed
    (unknown removal time: yes)."""
    return removed_at is None or removed_at <= now - timedelta(days=days)
