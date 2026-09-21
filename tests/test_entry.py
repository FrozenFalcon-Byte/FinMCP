"""Reading a typed line: which way the money went."""
from __future__ import annotations

from types import SimpleNamespace

from finmcp.services.entry import from_history, from_model, parse_entry


class FakeRepo:
    def __init__(self, directions: list[str]):
        self.rows = [{"merchant": "Company", "direction": d} for d in directions]

    def merchant_history(self, merchant: str, limit: int = 60) -> list[dict[str, str]]:
        return self.rows


def test_history_answers_when_the_account_only_ever_goes_one_way():
    guess = from_history(FakeRepo(["credit", "credit", "credit"]), "Company")
    assert guess is not None
    assert (guess.direction, guess.source) == ("credit", "history")
    assert guess.confidence > 0.8


def test_history_keeps_quiet_when_the_account_does_both():
    """A friend you split bills with is paid and pays you back. History has no opinion worth acting on."""
    assert from_history(FakeRepo(["credit", "debit", "credit", "debit"]), "Company") is None
    assert from_history(FakeRepo([]), "Company") is None


def test_the_model_reads_a_phrasing_nobody_wrote_a_rule_for():
    extracted = SimpleNamespace(direction="credit", merchant="Acme", amount=890.0, confidence=0.9)
    provider = SimpleNamespace(extract_transactions=lambda text, hint="": [extracted])
    guess = from_model(provider, "890 from acme")
    assert guess is not None
    assert (guess.direction, guess.merchant, guess.source) == ("credit", "Acme", "model")


def test_nothing_knows_and_the_caller_keeps_its_own_reading():
    provider = SimpleNamespace(extract_transactions=lambda text, hint="": [])
    assert parse_entry(FakeRepo([]), provider, "890 whatever", "Whatever").direction is None
