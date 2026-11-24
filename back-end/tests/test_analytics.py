"""Usage analytics (opt-in capture, consent, retention), app health recording, and the admin stats."""
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

from rest_api.clock import utcnow
from rest_api.database.models import AnalyticsEventDB, HealthEventDB
from rest_api.services import analytics_service as analytics
from rest_api.services import health, telemetry

from helpers import make_rotation, restock_action, review, set_account, spotify_item, track_object

SESSION = str(uuid.uuid4())


def tel(**extra):
    return {"session_id": SESSION, "decision_ms": 2500, "session_elapsed_ms": 9000, "input": "swipe",
            "revisit": False, "position": 0, "tz_offset": 0, **extra}


def review_with(client, rid, track_id, action, telemetry_payload):
    return client.post(f"/api/rotation/{rid}/review",
                       json={"track_id": track_id, "action": action, "telemetry": telemetry_payload})


def events(db, **filters):
    db.expire_all()
    return db.query(AnalyticsEventDB).filter_by(**filters).all()


# ---------- consent ----------

def test_consent_starts_unasked_and_is_changeable(client, db):
    assert client.get("/api/auth/me").json()["analytics_consent"] is None
    assert client.put("/api/user/me/settings", json={"analytics_consent": True}).json()["analytics_consent"] is True
    assert client.get("/api/auth/me").json()["analytics_consent"] is True
    assert client.put("/api/user/me/settings", json={"analytics_consent": False}).json()["analytics_consent"] is False


def test_nothing_is_recorded_without_consent(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 60)], grace=False)["id"]
    assert review_with(client, rid, "a", "keep", tel()).status_code == 200
    set_account(db, analytics_consent=False)
    assert review_with(client, rid, "a", "undo", tel()).status_code == 200
    assert events(db) == []


def test_review_decision_is_recorded_with_song_context(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 60)], grace=False)["id"]
    set_account(db, analytics_consent=True)
    assert review_with(client, rid, "a", "remove", tel(position=4)).status_code == 200
    [e] = events(db)
    assert (e.surface, e.kind, e.action, e.input, e.position, e.decision_ms) == ("review", "decision", "remove",
                                                                                  "swipe", 4, 2500)
    assert e.rotation_kind == "manual" and e.song_age_days == 60 and e.overdue_days == 30
    assert e.local_hour is not None and e.local_weekday is not None
    review_with(client, rid, "a", "undo", tel())
    assert [x.kind for x in events(db)] == ["decision", "undo"]


def test_bad_telemetry_is_dropped_not_rejected(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 60), spotify_item("b", 60)], grace=False)["id"]
    set_account(db, analytics_consent=True)
    assert review_with(client, rid, "a", "keep", {"session_id": "not-a-uuid"}).status_code == 200
    assert review_with(client, rid, "b", "keep", "garbage").status_code == 200
    assert events(db) == []
    # Huge timings are clamped
    review(client, rid, "a", "undo")
    review_with(client, rid, "a", "keep", tel(decision_ms=10**9))
    assert events(db)[0].decision_ms == telemetry.MAX_DECISION_MS


def test_restock_decisions_are_recorded_by_source(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 10)])["id"]
    spotify.catalog["n1"] = track_object("n1")
    set_account(db, analytics_consent=True)
    client.post(f"/api/rotation/{rid}/restock/add", json={"track_id": "n1", "source": "search", "telemetry": tel()})
    client.post(f"/api/rotation/{rid}/restock/skip",
                json={"track_id": "zz", "source": "suggested", "telemetry": tel(input="button")})
    rows = sorted(events(db, surface="restock"), key=lambda e: e.id)
    assert [(e.action, e.source) for e in rows] == [("add", "search"), ("not_now", "suggested")]
    assert restock_action(client, rid, "add", "a", "bring_back").status_code == 409  # no telemetry, no row
    assert len(events(db)) == 2


def test_session_end(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 10)])["id"]
    body = {"session_id": SESSION, "surface": "review", "rotation_id": rid, "ended": "done",
            "decisions": 12, "session_elapsed_ms": 95000}
    assert client.post("/api/user/me/telemetry/session-end", json=body).status_code == 204
    assert events(db) == []  # no consent yet
    set_account(db, analytics_consent=True)
    client.post("/api/user/me/telemetry/session-end", json=body)
    [e] = events(db)
    assert (e.kind, e.ended, e.decisions, e.rotation_kind) == ("session_end", "done", 12, "manual")
    bad = {**body, "ended": "exploded"}
    assert client.post("/api/user/me/telemetry/session-end", json=bad).status_code == 422


def test_opting_out_deletes_recorded_data(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 60)], grace=False)["id"]
    set_account(db, analytics_consent=True)
    review_with(client, rid, "a", "keep", tel())
    assert len(events(db)) == 1
    client.put("/api/user/me/settings", json={"analytics_consent": False})
    assert events(db) == []


def test_stats_survive_rotation_delete_but_not_account_delete(client, spotify, db):
    rid = make_rotation(client, spotify, [spotify_item("a", 60)], grace=False)["id"]
    set_account(db, analytics_consent=True)
    review_with(client, rid, "a", "keep", tel())
    client.delete(f"/api/rotation/{rid}")
    [e] = events(db)
    assert e.rotation_id is None and e.rotation_kind == "manual"
    client.delete("/api/user/me")
    assert events(db) == []


def test_purge_keeps_six_months(db, user):
    old = utcnow() - timedelta(days=telemetry.RETENTION_DAYS + 1)
    db.add_all([
        AnalyticsEventDB(user_id=user.id, surface="review", kind="decision", action="keep", created_at=old),
        AnalyticsEventDB(user_id=user.id, surface="review", kind="decision", action="keep", created_at=utcnow()),
        HealthEventDB(method="GET", route="/api/x", status=200, duration_ms=5, spotify_ms=0, spotify_calls=0,
                      db_ms=0, db_queries=0, db_connects=0, sampled=True, created_at=old),
    ])
    db.commit()
    assert telemetry.purge(db) == 2
    assert db.query(AnalyticsEventDB).count() == 1 and db.query(HealthEventDB).count() == 0


# ---------- health ----------

def test_requests_record_health_with_route_template_and_counters(client, spotify, health_db):
    rid = make_rotation(client, spotify, [spotify_item("a", 10)])["id"]
    client.get(f"/api/rotation/{rid}")
    health_db.expire_all()
    rows = health_db.query(HealthEventDB).filter_by(method="GET").all()
    row = next(r for r in rows if r.route == "/api/rotation/{rotation_id}")
    assert row.status == 200 and row.sampled is True
    assert json.loads(row.counters)["sync.attempt"] == 1


def test_health_sampling_rules():
    assert health.should_record(200, 50, {}, rand=0.9) == (False, False)
    assert health.should_record(200, 50, {}, rand=0.1) == (True, True)
    assert health.should_record(502, 50, {}, rand=0.9) == (True, False)  # errors always
    assert health.should_record(200, 5000, {}, rand=0.9) == (True, False)  # slow always
    assert health.should_record(200, 50, {"sync.failed": 1}, rand=0.9) == (True, False)
    # Other 4xx aren't sampled (anonymous traffic can't grow the table)
    assert health.should_record(401, 50, {}, rand=0.1) == (False, False)
    assert health.should_record(404, 50, {}, rand=0.1) == (False, False)
    assert health.should_record(429, 50, {}, rand=0.9) == (True, False)
    assert health.should_record(409, 50, {"sync.attempt": 1}, rand=0.1) == (True, False)  # counters still kept
    assert health.route_template({"path": "/api/rotation/12/queue"}) == "/api/rotation/{id}/queue"


# ---------- aggregation ----------

def ev(**kw):
    base = dict(user_id=1, surface="review", kind="decision", session_id="s1", action="keep", source=None,
                decision_ms=1000, session_elapsed_ms=1000, input="swipe", revisit=False, position=0,
                song_age_days=None, overdue_days=None, local_hour=None, local_weekday=None, ended=None,
                decisions=None, rotation_kind="manual", created_at=utcnow())
    return SimpleNamespace(**{**base, **kw})


def test_percentile_and_histogram():
    assert analytics.percentile([], 50) is None
    assert analytics.percentile([1, 2, 3, 4], 50) == 2.5
    hist = analytics.histogram([500, 1500, 70000], analytics.DECISION_BUCKETS)
    assert hist[0] == {"bucket": "<1s", "n": 1} and hist[-1] == {"bucket": "1 min+", "n": 1}


def test_sessions_and_decisions_summary():
    rows = [
        ev(session_id="s1", action="keep", session_elapsed_ms=30_000, position=0, song_age_days=10, decision_ms=2000),
        ev(session_id="s1", action="remove", session_elapsed_ms=90_000, position=1, song_age_days=400,
           decision_ms=4000),
        ev(session_id="s1", kind="session_end", action=None, ended="done", decisions=2, session_elapsed_ms=95_000),
        ev(session_id="s2", kind="session_end", action=None, ended="left", decisions=0, session_elapsed_ms=4000),
        ev(session_id="s3", action="keep", revisit=True, session_elapsed_ms=5000),
    ]
    s = analytics.session_summary(rows)
    assert s["count"] == 2 and s["opened_without_deciding"] == 1
    assert s["ended"] == {"done": 1, "left": 1, "unknown": 1}
    d = analytics.decision_summary(rows)
    assert d["count"] == 3 and d["counts"]["remove"] == 1
    assert d["median_ms"] == 3000  # the revisit (1000 ms) isn't timed
    by_age = {b["bucket"]: b["remove_rate"] for b in d["remove_rate_by_age"]}
    assert by_age == {"<1 month": 0.0, "1 year+": 1.0}
    assert d["changed_mind_share"] == round(1 / 3, 4)


def test_health_summary_uses_the_sample_for_latency():
    def row(**kw):
        base = dict(method="GET", route="/api/x", status=200, duration_ms=100, spotify_ms=0, spotify_calls=0,
                    db_ms=10, db_queries=1, db_connects=1, sampled=True, counters=None, created_at=utcnow())
        return SimpleNamespace(**{**base, **kw})

    rows = [row(duration_ms=100), row(duration_ms=300),
            row(duration_ms=9000, sampled=False, status=502, counters=json.dumps({"sync.failed": 1}))]
    h = analytics.health_summary(rows)
    assert h["p50_ms"] == 200 and h["errors"] == 1 and h["slow"] == 1
    assert h["counters"]["sync"]["failed"] == 1


def test_stats_endpoint_is_admin_only_and_aggregates(client, spotify, db, admin):
    rid = make_rotation(client, spotify, [spotify_item("a", 60), spotify_item("b", 60)], grace=False)["id"]
    set_account(db, analytics_consent=True)
    review_with(client, rid, "a", "keep", tel())
    review_with(client, rid, "b", "remove", tel(position=1))
    r = client.get("/api/admin/stats", params={"days": 30})
    assert r.status_code == 200
    stats = r.json()
    assert stats["kpis"]["current"]["decisions"] == 2
    assert stats["decisions"]["mix"]["remove"] == 0.5
    assert stats["usage"]["consent"] == {"yes": 1, "no": 0, "not_asked": 0}
    assert stats["you_vs_everyone"]["you"]["decisions"] == 2
    assert "session_id" not in json.dumps(stats)  # aggregates only
    assert client.get("/api/admin/stats", params={"days": 5}).status_code == 422


def test_stats_hidden_from_non_admins(client):
    assert client.get("/api/admin/stats").status_code == 404
