"""End-to-end HTTP tests over the async stack.

These drive the real ASGI app (async routes -> AsyncSession -> aiosqlite), which
is what pins down that nothing in the request path fell back to blocking IO: a
lazy load or a sync session would raise MissingGreenlet here rather than
silently working, the way it would in a plain unit test.

They also cover the public read cache: what it serves, who it serves it to, and
what clears it.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import cache
from app.csv_import import import_csv
from app.main import app
from app.service import rebuild_men, rebuild_women

HEADER = (
    "Timestamp,Name,Gender,Phone Number,Registration Number,"
    "Year of Study (4th years not allowed),Level of Exprience"
)


# 16 men so all four groups get a drawable roster (>= 2) after the snake draft.
def _entries(n_men: int = 16, n_women: int = 8) -> str:
    rows = [HEADER]
    for i in range(n_men):
        rows.append(
            f"27/07/2026 10:0{i % 10}:00,Man {i},Male,90000000{i:02d},"
            f"2610900500{i:02d},1st Year,School"
        )
    for i in range(n_women):
        rows.append(
            f"27/07/2026 11:0{i % 10}:00,Woman {i},Female,80000000{i:02d},"
            f"2610900600{i:02d},1st Year,District"
        )
    return "\n".join(rows) + "\n"


@pytest_asyncio.fixture()
async def client(db):
    """HTTP client bound to the app; `db` gives us a freshly-created schema."""
    cache.invalidate()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    cache.invalidate()


@pytest_asyncio.fixture()
async def seeded(db):
    """A full men's + women's draw in the database."""
    await import_csv(db, _entries())
    await rebuild_men(db, seed=2026)
    await rebuild_women(db, seed=777)
    await db.commit()
    cache.invalidate()


async def _login(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/code-login", json={"code": "trials2026", "name": "Tester"}
    )
    assert r.status_code == 200, r.text


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_groups_and_bracket_are_served(client, seeded):
    groups = (await client.get("/api/groups")).json()
    labels = {(g["category"], g["group_label"]) for g in groups}
    assert ("women", None) in labels
    assert ("men", "A") in labels

    r = await client.get("/api/bracket", params={"category": "men", "group": "A"})
    assert r.status_code == 200
    body = r.json()
    assert body["tournament"]["bracket_size"] >= 2
    assert len(body["matches"]) == body["tournament"]["bracket_size"] - 1
    assert body["players"]


async def test_public_bracket_hides_pii_and_admin_bracket_shows_it(client, seeded):
    public = (await client.get("/api/bracket", params={"category": "women"})).json()
    assert all(p["phone"] is None for p in public["players"])
    assert all(p["registration_number"] is None for p in public["players"])

    await _login(client)
    admin = (await client.get("/api/bracket", params={"category": "women"})).json()
    assert any(p["phone"] for p in admin["players"])


async def test_admin_response_is_never_served_from_the_public_cache(client, seeded):
    """The cached copy is the PII-free one; an admin must not receive it."""
    # Populate the cache as an anonymous visitor first.
    anon = (await client.get("/api/bracket", params={"category": "women"})).json()
    assert all(p["phone"] is None for p in anon["players"])
    assert cache.get(("bracket", "women", None)) is not None

    await _login(client)
    admin = (await client.get("/api/bracket", params={"category": "women"})).json()
    assert any(p["phone"] for p in admin["players"]), "admin got the cached public copy"


async def test_public_bracket_is_served_from_memory_on_the_second_hit(client, seeded):
    key = ("bracket", "men", "A")
    assert cache.get(key) is None
    first = (await client.get("/api/bracket", params={"category": "men", "group": "A"})).json()
    assert cache.get(key) is not None

    # Doctor the cached object itself. If the next request returns the doctored
    # value, it demonstrably came from memory rather than from the database.
    cached = cache.get(key)
    cached.tournament.bracket_size = 9999
    second = (await client.get("/api/bracket", params={"category": "men", "group": "A"})).json()
    assert second["tournament"]["bracket_size"] == 9999
    assert first["tournament"]["bracket_size"] != 9999


async def test_admin_write_busts_the_public_cache(client, seeded):
    key = ("bracket", "men", "A")
    await client.get("/api/bracket", params={"category": "men", "group": "A"})
    assert cache.get(key) is not None

    await _login(client)
    bracket = (await client.get("/api/bracket", params={"category": "men", "group": "A"})).json()
    match = next(m for m in bracket["matches"] if not m["is_bye"] and m["player_a_id"])
    r = await client.put(
        f"/api/admin/matches/{match['id']}/schedule",
        json={"scheduled_time": "Sat 10:30 Court 2"},
    )
    assert r.status_code == 200, r.text
    assert cache.get(key) is None, "the write should have cleared the cached bracket"

    fresh = (await client.get("/api/bracket", params={"category": "men", "group": "A"})).json()
    updated = next(m for m in fresh["matches"] if m["id"] == match["id"])
    assert updated["scheduled_time"] == "Sat 10:30 Court 2"


async def test_score_entry_round_trips_and_advances(client, seeded):
    """The score snapshot returned to the browser must reflect the new games.

    Sessions no longer expire on commit, so this is the regression guard for
    the handler returning a stale in-memory collection.
    """
    await _login(client)
    bracket = (await client.get("/api/bracket", params={"category": "men", "group": "A"})).json()
    match = next(
        m
        for m in bracket["matches"]
        if not m["is_bye"] and m["player_a_id"] and m["player_b_id"]
    )
    r = await client.put(
        f"/api/admin/matches/{match['id']}/score",
        json={"games": [{"game_number": 1, "score_a": 21, "score_b": 15}]},
    )
    assert r.status_code == 200, r.text
    snap = r.json()
    assert snap["status"] == "completed"
    assert snap["winner_id"] == match["player_a_id"]
    assert snap["games"] == [{"game_number": 1, "score_a": 21, "score_b": 15}]

    # ...and the winner is in the next round.
    fresh = (await client.get("/api/bracket", params={"category": "men", "group": "A"})).json()
    nxt = next(m for m in fresh["matches"] if m["id"] == match["next_match_id"])
    slot = "player_a_id" if match["position_in_round"] % 2 == 0 else "player_b_id"
    assert nxt[slot] == match["player_a_id"]


async def test_any_scoreline_is_accepted_and_the_leader_advances(client, seeded):
    """A score that fits no standard format is still a result: 40-15 stands."""
    await _login(client)
    bracket = (await client.get("/api/bracket", params={"category": "men", "group": "A"})).json()
    match = next(
        m
        for m in bracket["matches"]
        if not m["is_bye"] and m["player_a_id"] and m["player_b_id"]
    )
    r = await client.put(
        f"/api/admin/matches/{match['id']}/score",
        json={"games": [{"game_number": 1, "score_a": 40, "score_b": 15}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["winner_id"] == match["player_a_id"]

    # A short, schedule-squeezed game counts exactly the same way.
    other = next(
        m
        for m in bracket["matches"]
        if not m["is_bye"] and m["player_a_id"] and m["player_b_id"] and m["id"] != match["id"]
    )
    r = await client.put(
        f"/api/admin/matches/{other['id']}/score",
        json={"games": [{"game_number": 1, "score_a": 2, "score_b": 5}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["winner_id"] == other["player_b_id"]


async def test_a_level_score_does_not_pick_a_winner(client, seeded):
    await _login(client)
    bracket = (await client.get("/api/bracket", params={"category": "men", "group": "A"})).json()
    match = next(
        m
        for m in bracket["matches"]
        if not m["is_bye"] and m["player_a_id"] and m["player_b_id"]
    )
    r = await client.put(
        f"/api/admin/matches/{match['id']}/score",
        json={"games": [{"game_number": 1, "score_a": 9, "score_b": 9}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["winner_id"] is None


async def test_writes_require_an_admin_session(client, seeded):
    r = await client.post("/api/admin/men/rebuild", json={"seed": 1})
    assert r.status_code == 401
    r = await client.get("/api/flagged")
    assert r.status_code == 401


async def test_search_returns_the_match_to_jump_to(client, seeded):
    """The UI navigates to a tie from these fields, so they must be present."""
    results = (await client.get("/api/search", params={"q": "Man"})).json()
    assert results
    first = results[0]
    assert first["category"] == "men"
    assert first["group_label"] in {"A", "B", "C", "D"}
    assert first["matches"], "a drawn player should have at least one match"
    m = first["matches"][0]
    assert isinstance(m["match_id"], int)
    assert m["round_name"]
    # PII stays admin-only here too.
    assert first["phone"] is None


async def test_search_shows_phone_only_to_admins(client, seeded):
    await _login(client)
    results = (await client.get("/api/search", params={"q": "Man"})).json()
    assert any(r["phone"] for r in results)


@pytest.mark.parametrize("q", ["", "a"])
async def test_search_ignores_too_short_queries(client, seeded, q):
    assert (await client.get("/api/search", params={"q": q})).json() == []


# --------------------------------------------------------------------------
# Editing an entry. The roster comes off a Google Form filled in by hundreds of
# students, so corrections mid-event are routine.
# --------------------------------------------------------------------------
async def _find(client: AsyncClient, name: str) -> dict:
    results = (await client.get("/api/search", params={"q": name})).json()
    return next(r for r in results if r["full_name"] == name)


async def test_edit_entry_updates_every_field(client, seeded):
    await _login(client)
    p = await _find(client, "Man 3")
    r = await client.patch(
        f"/api/admin/players/{p['id']}",
        json={
            "full_name": "  Manny   Threeson ",
            "phone": "+91 98765 43210",
            "registration_number": "261090059999",
            "year_of_study": "3rd Year",
            "experience_level": "Nationals",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Manny Threeson"  # whitespace collapsed
    assert body["phone"] == "9876543210"  # normalized to 10 digits
    assert body["registration_number"] == "261090059999"
    assert body["year_of_study"] == "3rd Year"
    assert body["experience_level"] == "Nationals"

    # ...and it's what the draw serves afterwards.
    again = await _find(client, "Manny Threeson")
    assert again["phone"] == "9876543210"


async def test_edit_leaves_omitted_fields_alone(client, seeded):
    await _login(client)
    p = await _find(client, "Man 4")
    r = await client.patch(
        f"/api/admin/players/{p['id']}", json={"year_of_study": "4th Year"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Man 4"
    assert r.json()["phone"] == p["phone"]


async def test_edit_renames_the_player_in_the_bracket(client, seeded):
    await _login(client)
    p = await _find(client, "Man 5")
    await client.patch(f"/api/admin/players/{p['id']}", json={"full_name": "Renamed Player"})
    bracket = (
        await client.get(
            "/api/bracket", params={"category": "men", "group": p["group_label"]}
        )
    ).json()
    assert any(x["full_name"] == "Renamed Player" for x in bracket["players"])


async def test_edit_rejects_an_empty_name_and_a_bad_phone(client, seeded):
    await _login(client)
    p = await _find(client, "Man 6")
    assert (
        await client.patch(f"/api/admin/players/{p['id']}", json={"full_name": "   "})
    ).status_code == 422
    assert (
        await client.patch(f"/api/admin/players/{p['id']}", json={"phone": "12345"})
    ).status_code == 422


async def test_edit_refuses_to_duplicate_another_entry(client, seeded):
    """Two entries can't end up with the same identity — the unique index would
    reject it anyway, so say who it clashed with instead of throwing a 500."""
    await _login(client)
    a = await _find(client, "Man 7")
    b = await _find(client, "Man 8")
    r = await client.patch(f"/api/admin/players/{a['id']}", json={"phone": b["phone"]})
    assert r.status_code == 409
    assert "Man 8" in r.json()["detail"]["message"]


async def test_edit_keeps_identity_in_step_so_reimport_still_matches(client, seeded, db):
    """Correcting a phone must move the dedup key with it, or re-importing the
    CSV would file the same person again as a new entry."""
    from sqlalchemy import select

    from app.models import Player

    await _login(client)
    p = await _find(client, "Man 9")
    await client.patch(f"/api/admin/players/{p['id']}", json={"phone": "9000099000"})
    row = (await db.execute(select(Player).where(Player.id == p["id"]))).scalar_one()
    await db.refresh(row)
    assert row.dedup_key == "ph:9000099000"


async def test_edit_requires_admin_and_a_real_player(client, seeded):
    assert (
        await client.patch("/api/admin/players/1", json={"full_name": "Nope"})
    ).status_code == 401
    await _login(client)
    assert (
        await client.patch("/api/admin/players/999999", json={"full_name": "Nope"})
    ).status_code == 404


async def test_edit_is_written_to_the_audit_log(client, seeded):
    await _login(client)
    p = await _find(client, "Man 10")
    await client.patch(f"/api/admin/players/{p['id']}", json={"full_name": "Audited Name"})
    audit = (await client.get("/api/admin/audit")).json()
    assert any(a["action"] == "edit_player" and a["entity_id"] == p["id"] for a in audit)
