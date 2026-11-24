"""Aggregates for the admin dashboard (GET /api/admin/stats). See docs/MONITORING_PLAN.md.

The summary functions are pure: they take rows (anything with the model's attributes) and
return JSON-ready dicts. Percentiles are computed here rather than in SQL, so they run on
SQLite in tests too; with at most 5 users the row counts are small.
Only aggregates leave this module: no raw events, tokens or user rows.
"""
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from rest_api.clock import utcnow
from rest_api.database.models.analytics_event import (
    DECISION,
    RESTOCK,
    REVIEW,
    SESSION_END,
    UNDO,
    AnalyticsEventDB,
)
from rest_api.database.models.health_event import HealthEventDB
from rest_api.database.models.rotation import AUTO, MANUAL, RotationDB
from rest_api.database.models.rotation_track import ACTIVE, RotationTrackDB
from rest_api.database.models.user import DEMO, UserDB
from rest_api.services import health, preferences, telemetry

RANGES = (7, 30, 90, 180)
REVIEW_ACTIONS = ("keep", "super_keep", "remove", "skip")
RESTOCK_ACTIONS = ("add", "not_now", "block")
INF = math.inf

SESSION_BUCKETS = (
    [0, 60, 180, 300, 600, 1200, INF],
    ["<1 min", "1–3 min", "3–5 min", "5–10 min", "10–20 min", "20 min+"],
)
DECISION_BUCKETS = (
    [0, 1000, 2000, 4000, 8000, 15000, 30000, 60000, INF],
    ["<1s", "1–2s", "2–4s", "4–8s", "8–15s", "15–30s", "30–60s", "1 min+"],
)
AGE_BUCKETS = ([0, 30, 90, 180, 365, INF], ["<1 month", "1–3 months", "3–6 months", "6–12 months", "1 year+"])
POSITION_BUCKETS = ([0, 10, 25, 50, INF], ["1–10", "11–25", "26–50", "51+"])  # positions are 0-based


# ---------- small helpers ----------

def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (p in 0..100); None for no values."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return float(vals[lo] + (vals[hi] - vals[lo]) * (k - lo))


def histogram(values: list[float], buckets: tuple[list[float], list[str]]) -> list[dict[str, Any]]:
    edges, labels = buckets
    counts = [0] * len(labels)
    for v in values:
        if v is None:
            continue
        for i in range(len(labels)):
            if edges[i] <= v < edges[i + 1]:
                counts[i] += 1
                break
    return [{"bucket": label, "n": n} for label, n in zip(labels, counts, strict=True)]


def _bucket(value: float, buckets: tuple[list[float], list[str]]) -> str | None:
    edges, labels = buckets
    for i, label in enumerate(labels):
        if edges[i] <= value < edges[i + 1]:
            return label
    return None


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _round(value: float | None, digits: int = 0) -> float | None:
    return None if value is None else round(value, digits)


def _week(dt: datetime) -> str:
    return (dt - timedelta(days=dt.weekday())).date().isoformat()  # the Monday


# ---------- review ----------

def review_sessions(events: list) -> list[dict[str, Any]]:
    """One entry per review session: its length (from the client's elapsed time), songs decided,
    how it ended ("unknown" if the end signal never arrived) and when it started."""
    by_session: dict[str, list] = defaultdict(list)
    for e in events:
        if e.surface == REVIEW and e.session_id:
            by_session[e.session_id].append(e)
    out = []
    for session_id, evs in by_session.items():
        decisions = [e for e in evs if e.kind == DECISION]
        end = next((e for e in evs if e.kind == SESSION_END), None)
        elapsed = [e.session_elapsed_ms for e in evs if e.session_elapsed_ms is not None]
        out.append({
            "session_id": session_id,
            "user_id": evs[0].user_id,
            "started_at": min(e.created_at for e in evs),
            "length_s": max(elapsed) / 1000 if elapsed else None,
            "songs": sum(1 for e in decisions if not e.revisit),
            "decisions": len(decisions),
            "ended": end.ended if end else "unknown",
        })
    return out


def session_summary(events: list) -> dict[str, Any]:
    sessions = review_sessions(events)
    with_decisions = [s for s in sessions if s["decisions"] > 0]
    lengths = [s["length_s"] for s in with_decisions if s["length_s"] is not None]
    return {
        "count": len(with_decisions),
        "opened_without_deciding": len(sessions) - len(with_decisions),
        "median_s": _round(percentile(lengths, 50)),
        "p90_s": _round(percentile(lengths, 90)),
        "songs_median": _round(percentile([s["songs"] for s in with_decisions], 50), 1),
        "ended": dict(Counter(s["ended"] for s in sessions)),
        "length_histogram": histogram(lengths, SESSION_BUCKETS),
    }


def engagement(events: list) -> dict[str, Any]:
    """Sessions per active user per week, and the typical gap between a user's sessions."""
    sessions = [s for s in review_sessions(events) if s["decisions"] > 0]
    weekly: dict[str, dict[int, int]] = defaultdict(Counter)
    starts: dict[int, list[datetime]] = defaultdict(list)
    for s in sessions:
        weekly[_week(s["started_at"])][s["user_id"]] += 1
        starts[s["user_id"]].append(s["started_at"])
    gaps = []
    for times in starts.values():
        times.sort()
        gaps += [(b - a).total_seconds() / 86400 for a, b in zip(times, times[1:], strict=False)]
    per_user_week = [n for users in weekly.values() for n in users.values()]
    return {
        "sessions_per_user_week_median": _round(percentile(per_user_week, 50), 1),
        "days_between_sessions_median": _round(percentile(gaps, 50), 1),
    }


def decision_summary(events: list) -> dict[str, Any]:
    decisions = [e for e in events if e.surface == REVIEW and e.kind == DECISION and e.action in REVIEW_ACTIONS]
    undos = [e for e in events if e.surface == REVIEW and e.kind == UNDO]
    first_time = [e for e in decisions if not e.revisit]
    times = [e.decision_ms for e in first_time if e.decision_ms is not None]
    total = len(decisions)
    mix = Counter(e.action for e in decisions)

    by_week: dict[str, Counter] = defaultdict(Counter)
    for e in decisions:
        by_week[_week(e.created_at)][e.action] += 1

    by_age: dict[str, Counter] = defaultdict(Counter)
    for e in decisions:
        if e.song_age_days is not None:
            label = _bucket(e.song_age_days, AGE_BUCKETS)
            by_age[label]["n"] += 1
            by_age[label]["remove"] += e.action == "remove"

    by_position: dict[str, dict[str, list]] = defaultdict(lambda: {"n": 0, "remove": 0, "times": []})
    for e in first_time:
        if e.position is not None:
            slot = by_position[_bucket(e.position, POSITION_BUCKETS)]
            slot["n"] += 1
            slot["remove"] += e.action == "remove"
            if e.decision_ms is not None:
                slot["times"].append(e.decision_ms)

    heat = [[0] * 24 for _ in range(7)]
    for e in decisions:
        if e.local_weekday is not None and e.local_hour is not None:
            heat[e.local_weekday][e.local_hour] += 1

    return {
        "count": total,
        "mix": {a: _share(mix[a], total) for a in REVIEW_ACTIONS},
        "counts": {a: mix[a] for a in REVIEW_ACTIONS},
        "mix_by_week": [{"week": w, **{a: c[a] for a in REVIEW_ACTIONS}} for w, c in sorted(by_week.items())],
        "median_ms": _round(percentile(times, 50)),
        "p90_ms": _round(percentile(times, 90)),
        "time_histogram": histogram(times, DECISION_BUCKETS),
        "input": dict(Counter(e.input for e in decisions if e.input)),
        "undo_count": len(undos),
        "changed_mind_share": _share(len(undos) + sum(1 for e in decisions if e.revisit), total),
        "remove_rate_by_age": [
            {"bucket": label, "n": by_age[label]["n"],
             "remove_rate": _share(by_age[label]["remove"], by_age[label]["n"])}
            for label in AGE_BUCKETS[1] if by_age[label]["n"]
        ],
        "by_position": [
            {"bucket": label, "n": by_position[label]["n"],
             "remove_rate": _share(by_position[label]["remove"], by_position[label]["n"]),
             "median_ms": _round(percentile(by_position[label]["times"], 50))}
            for label in POSITION_BUCKETS[1] if label in by_position
        ],
        "overdue_days_median": _round(percentile([e.overdue_days for e in decisions], 50), 1),
        "weekday_hour": heat,  # [weekday 0=Mon][local hour]
    }


# ---------- restock ----------

def restock_summary(events: list) -> dict[str, Any]:
    decisions = [e for e in events if e.surface == RESTOCK and e.kind == DECISION]
    undos = [e for e in events if e.surface == RESTOCK and e.kind == UNDO]
    ends = [e for e in events if e.surface == RESTOCK and e.kind == SESSION_END]
    by_source = []
    for source in sorted({e.source for e in decisions + undos if e.source}):
        mine = [e for e in decisions if e.source == source]
        counts = Counter(e.action for e in mine)
        times = [e.decision_ms for e in mine if e.decision_ms is not None and not e.revisit]
        by_source.append({
            "source": source, "answered": len(mine), **{a: counts[a] for a in RESTOCK_ACTIONS},
            "undo": sum(1 for e in undos if e.source == source),
            "add_rate": _share(counts["add"], len(mine)),
            "median_ms": _round(percentile(times, 50)),
        })
    return {
        "answered": len(decisions),
        "adds": sum(1 for e in decisions if e.action == "add"),
        "by_source": by_source,
        "sessions": len({e.session_id for e in decisions + ends if e.session_id}),
        "ended": dict(Counter(e.ended for e in ends)),
    }


# ---------- usage (accounts, rotations, settings) ----------

def usage_summary(events: list, users: list, rotations: list, sizes: dict[int, int]) -> dict[str, Any]:
    active_by_week: dict[str, set] = defaultdict(set)
    for e in events:
        active_by_week[_week(e.created_at)].add(e.user_id)
    consenting = [u for u in users if u.analytics_consent is True]
    consenting_ids = {u.id for u in consenting}
    rots = [r for r in rotations if r.owner_id in consenting_ids]

    adoption = {
        name: _share(sum(1 for u in consenting if getattr(u, name, None) is not None), len(consenting))
        for name in preferences.ACCOUNT
    }
    override_names = (*preferences.ROTATION_OVERRIDES, "review_limit", *preferences.AUTO)
    return {
        "accounts": len(users),
        "consent": {
            "yes": len(consenting),
            "no": sum(1 for u in users if u.analytics_consent is False),
            "not_asked": sum(1 for u in users if u.analytics_consent is None),
        },
        "active_users_by_week": [{"week": w, "users": len(ids)} for w, ids in sorted(active_by_week.items())],
        # Below: consenting users only
        "rotations": {
            "manual": sum(1 for r in rots if r.kind == MANUAL),
            "auto": sum(1 for r in rots if r.kind == AUTO),
            "songs_median": _round(percentile([sizes.get(r.id, 0) for r in rots], 50)),
            "interval_days": dict(Counter(f"{round(r.interval_hours / 24, 1):g}" for r in rots)),
        },
        "settings_changed_share": adoption,
        "rotation_overrides": {
            name: sum(1 for r in rots if getattr(r, name, None) is not None) for name in override_names
        },
    }


# ---------- health ----------

HEALTH_GROUPS = {
    "sync": ("sync.attempt", "sync.fresh_skip", "sync.unchanged", "sync.full_read", "sync.partial_read",
             "sync.failed", "sync.flushed_songs"),
    "claim": ("claim.waited", "claim.wait_ms", "claim.timeout"),
    "spotify": ("spotify.rate_limited", "spotify.quota_exceeded", "spotify.retry", "spotify.token_refresh"),
    "auto": ("auto.rotated_out", "auto.added", "auto.short", "auto.failed"),
    "cron": ("cron.rotations", "cron.failed"),
}


def health_summary(rows: list) -> dict[str, Any]:
    """Latency percentiles come from the random sample only; errors and counters from every row."""
    sampled = [r for r in rows if r.sampled]
    counters: Counter = Counter()
    for r in rows:
        if r.counters:
            counters.update(json.loads(r.counters))

    routes: dict[tuple, list] = defaultdict(list)
    for r in sampled:
        routes[(r.method, r.route)].append(r)
    by_route = sorted(
        (
            {
                "route": f"{method} {route}", "sampled": len(rs),
                "est_requests": round(len(rs) / health.SAMPLE_RATE),
                "p50_ms": _round(percentile([r.duration_ms for r in rs], 50)),
                "p95_ms": _round(percentile([r.duration_ms for r in rs], 95)),
                "spotify_ms_avg": _round(sum(r.spotify_ms for r in rs) / len(rs)),
                "db_ms_avg": _round(sum(r.db_ms for r in rs) / len(rs)),
                "db_connects_avg": _round(sum(r.db_connects for r in rs) / len(rs), 1),
            }
            for (method, route), rs in routes.items()
        ),
        key=lambda x: -(x["p95_ms"] or 0),
    )

    errors_by_route = Counter(f"{r.method} {r.route}" for r in rows if r.status >= 500)
    by_day: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        day = r.created_at.date().isoformat()
        by_day[day]["errors"] += r.status >= 500
        by_day[day]["rate_limited"] += r.status == 429
        by_day[day]["slow"] += r.duration_ms >= health.SLOW_MS
    spotify_errors = {
        k.removeprefix("spotify.error_"): v for k, v in counters.items() if k.startswith("spotify.error_")
    }

    waits = counters.get("claim.waited", 0)
    return {
        "recorded": len(rows),
        "sampled": len(sampled),
        "sample_rate": health.SAMPLE_RATE,
        "p50_ms": _round(percentile([r.duration_ms for r in sampled], 50)),
        "p95_ms": _round(percentile([r.duration_ms for r in sampled], 95)),
        "errors": sum(1 for r in rows if r.status >= 500),
        "rate_limited_responses": sum(1 for r in rows if r.status == 429),
        "slow": sum(1 for r in rows if r.duration_ms >= health.SLOW_MS),
        "by_route": by_route[:15],
        "errors_by_route": [{"route": k, "n": v} for k, v in errors_by_route.most_common(10)],
        "by_day": [{"day": d, **c} for d, c in sorted(by_day.items())],
        "counters": {
            group: {k.split(".", 1)[1]: counters.get(k, 0) for k in keys} for group, keys in HEALTH_GROUPS.items()
        },
        "claim_wait_avg_ms": _round(counters.get("claim.wait_ms", 0) / waits) if waits else None,
        "spotify_errors": spotify_errors,
    }


# ---------- the whole payload ----------

def kpis(events: list) -> dict[str, Any]:
    s = session_summary(events)
    d = decision_summary(events)
    return {
        "sessions": s["count"], "session_median_s": s["median_s"], "decisions": d["count"],
        "decision_median_ms": d["median_ms"], "keep_rate": _keep_rate(d), "remove_rate": d["mix"]["remove"],
    }


def _keep_rate(d: dict) -> float | None:
    keep, super_keep = d["mix"]["keep"], d["mix"]["super_keep"]
    return None if keep is None else round(keep + (super_keep or 0), 4)


def build_stats(
    events: list, previous: list, health_rows: list, users: list, rotations: list, sizes: dict[int, int],
    admin_id: int, days: int, now: datetime,
) -> dict[str, Any]:
    mine = [e for e in events if e.user_id == admin_id]
    others = [e for e in events if e.user_id != admin_id]
    return {
        "range": {"days": days, "from": (now - timedelta(days=days)).isoformat(), "to": now.isoformat()},
        "kpis": {"current": kpis(events), "previous": kpis(previous)},
        "sessions": session_summary(events),
        "engagement": engagement(events),
        "decisions": decision_summary(events),
        "restock": restock_summary(events),
        "usage": usage_summary(events, users, rotations, sizes),
        "health": health_summary(health_rows),
        "you_vs_everyone": {"you": kpis(mine), "everyone_else": kpis(others)},
        "retention_days": telemetry.RETENTION_DAYS,
    }


def load_stats(db: Session, admin: UserDB, days: int, kind: str = "all") -> dict[str, Any]:
    """Purge anything past retention, then aggregate the range (and the one before it, for deltas)."""
    telemetry.purge(db)
    now = utcnow()
    start, prev_start = now - timedelta(days=days), now - timedelta(days=2 * days)
    query = db.query(AnalyticsEventDB).filter(AnalyticsEventDB.created_at >= prev_start)
    if kind in (MANUAL, AUTO):
        query = query.filter(AnalyticsEventDB.rotation_kind == kind)
    rows = query.all()
    events = [e for e in rows if e.created_at >= start]
    previous = [e for e in rows if e.created_at < start]
    health_rows = db.query(HealthEventDB).filter(HealthEventDB.created_at >= start).all()
    # Public demo accounts aren't real users
    users = db.query(UserDB).filter(UserDB.provider != DEMO).all()
    rotations = (
        db.query(RotationDB).join(UserDB, RotationDB.owner_id == UserDB.id).filter(UserDB.provider != DEMO).all()
    )
    sizes = dict(
        db.query(RotationTrackDB.rotation_id, func.count(RotationTrackDB.id))
        .filter(RotationTrackDB.status == ACTIVE)
        .group_by(RotationTrackDB.rotation_id)
        .all()
    )
    return build_stats(events, previous, health_rows, users, rotations, sizes, admin.id, days, now)
