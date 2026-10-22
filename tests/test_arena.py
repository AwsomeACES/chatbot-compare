"""Blind arena: fair pairing, Bradley-Terry ratings and battles that survive a restart (no network)."""

import random

import pytest
from fastapi import HTTPException

import app
from adapters import Reply

BOTS = [{"id": i, "label": i.upper(), "type": "http", "url": "http://x"} for i in ("a", "b", "c")]


def vote(a, b, winner):
    return {"a": a, "b": b, "winner": winner}


def test_the_pair_with_fewest_votes_goes_next():
    votes = [vote("a", "b", "a"), vote("b", "a", "tie"), vote("a", "c", "b")]
    for seed in range(20):
        pair = app.pick_pair(BOTS, votes, random.Random(seed))
        assert {b["id"] for b in pair} == {"b", "c"}


def test_bradley_terry_ranks_by_strength_and_ignores_vote_order():
    votes = [vote("a", "b", "a")] * 6 + [vote("b", "a", "a")] * 2 + [vote("b", "c", "a")] * 5 + [vote("c", "a", "tie")]
    ratings = app.bradley_terry(votes)
    assert ratings["a"] > ratings["b"] > ratings["c"]
    assert app.bradley_terry(list(reversed(votes))) == ratings
    assert app.bradley_terry([vote("a", "b", "a")])["a"] < 2000  # unbeaten, but still finite


class Conv:
    def __init__(self, cfg):
        self.cfg = cfg

    def send(self, message):
        return Reply(text=f"{self.cfg['id']} says hi", latency_ms=5)

    def close(self):
        pass


@pytest.fixture
def arena(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "ARENA_FILE", str(tmp_path / "arena.json"))
    monkeypatch.setattr(app, "BATTLES_FILE", str(tmp_path / "arena_battles.json"))
    monkeypatch.setattr(app, "load_bots", lambda: BOTS)
    monkeypatch.setattr(app, "open_conversation", Conv)
    monkeypatch.setattr(app, "battles", {})


def test_a_battle_can_be_voted_on_after_a_restart(arena, monkeypatch):
    with pytest.raises(app.HTTPException) as e:  # these bots aren't on this machine: needs a yes first
        app.arena_message(app.BattleRequest(message="hello"))
    assert e.value.status_code == 400 and "not on this machine" in e.value.detail
    r = app.arena_message(app.BattleRequest(message="hello", consent=True))
    bid = r["battle_id"]
    monkeypatch.setattr(app, "battles", {})  # the server restarted: live sessions are gone

    restored = app.arena_battle(bid)
    assert restored["live"] is False and restored["log"][0]["a"]["text"] == r["a"]["text"]
    with pytest.raises(HTTPException) as e:
        app.arena_message(app.BattleRequest(message="more", battle_id=bid, consent=True))
    assert e.value.status_code == 409

    names = app.arena_vote(app.VoteRequest(battle_id=bid, winner="a"))
    assert r["a"]["text"].startswith(names["a"]["id"])
    board = app.leaderboard()
    assert board["votes"] == 1 and board["rows"][0]["id"] == names["a"]["id"] and board["rows"][0]["wins"] == 1
    with pytest.raises(HTTPException):  # one vote per battle
        app.arena_vote(app.VoteRequest(battle_id=bid, winner="b"))
