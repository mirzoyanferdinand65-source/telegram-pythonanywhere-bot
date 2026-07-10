"""Tests for bot/active_doc.py — the per-user 'document being studied' state."""

from unittest.mock import MagicMock, patch


def _with_store(store):
    """Patch the store both modules see (active_doc imports it by reference)."""
    return patch("bot.active_doc.store", store)


def test_set_get_clear_roundtrip():
    fake = MagicMock()
    saved = {}
    fake.set.side_effect = lambda k, v: saved.__setitem__(k, v)
    fake.get.side_effect = lambda k: saved.get(k)
    fake.delete.side_effect = lambda k: saved.pop(k, None)
    with _with_store(fake):
        from bot import active_doc

        assert active_doc.get_active_doc(1) is None
        assert active_doc.set_active_doc(1, 42) is True
        assert active_doc.get_active_doc(1) == 42  # returned as int
        assert active_doc.clear_active_doc(1) is True
        assert active_doc.get_active_doc(1) is None


def test_stateless_mode_returns_safe_defaults():
    with _with_store(None):
        from bot import active_doc

        assert active_doc.get_active_doc(1) is None
        assert active_doc.set_active_doc(1, 42) is False
        assert active_doc.clear_active_doc(1) is False


def test_non_integer_stored_value_is_ignored():
    fake = MagicMock()
    fake.get.return_value = "not-a-number"
    with _with_store(fake):
        from bot import active_doc

        assert active_doc.get_active_doc(1) is None


def test_store_error_degrades_to_none():
    fake = MagicMock()
    fake.get.side_effect = RuntimeError("db down")
    with _with_store(fake):
        from bot import active_doc

        assert active_doc.get_active_doc(1) is None
