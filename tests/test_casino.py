from unittest.mock import patch


def test_get_balance_initializes_new_user():
    with patch("bot.casino.store") as mock_store:
        mock_store.get.return_value = None
        from bot.casino import get_balance

        assert get_balance(123) == 100
        mock_store.set.assert_called_once_with("casino_balance:123", "100")


def test_get_balance_returns_existing_value():
    with patch("bot.casino.store") as mock_store:
        mock_store.get.return_value = "42"
        from bot.casino import get_balance

        assert get_balance(123) == 42
        mock_store.set.assert_not_called()


def test_get_balance_without_store():
    with patch("bot.casino.store", None):
        from bot.casino import get_balance

        assert get_balance(123) == 100


def test_get_balance_falls_back_on_store_error():
    with patch("bot.casino.store") as mock_store:
        mock_store.get.side_effect = Exception("db down")
        from bot.casino import get_balance

        assert get_balance(123) == 100


def test_spin_slots_three_match_pays_10x():
    with (
        patch("bot.casino.store") as mock_store,
        patch("bot.casino.random.choice", return_value="🎩"),
    ):
        mock_store.get.return_value = "100"
        from bot.casino import spin_slots

        result = spin_slots(123, 10)
        assert result["symbols"] == ["🎩", "🎩", "🎩"]
        assert result["win"] is True
        assert result["payout"] == 100
        assert result["balance"] == 190  # 100 - 10 + 100
        mock_store.set.assert_called_with("casino_balance:123", "190")


def test_spin_slots_two_match_pays_2x():
    with patch("bot.casino.store") as mock_store:
        mock_store.get.return_value = "100"
        from bot.casino import spin_slots

        with patch("bot.casino.random.choice", side_effect=["🎩", "🎩", "💰"]):
            result = spin_slots(123, 10)
        assert result["win"] is True
        assert result["payout"] == 20
        assert result["balance"] == 110  # 100 - 10 + 20


def test_spin_slots_no_match_loses_bet():
    with patch("bot.casino.store") as mock_store:
        mock_store.get.return_value = "100"
        from bot.casino import spin_slots

        with patch("bot.casino.random.choice", side_effect=["🎩", "💰", "🔫"]):
            result = spin_slots(123, 10)
        assert result["win"] is False
        assert result["payout"] == 0
        assert result["balance"] == 90


def test_spin_slots_floors_balance_at_minimum():
    """A losing bet that would drop the balance below CASINO_MIN_BALANCE (5)
    is floored at 5 instead, so a losing streak can't lock a user out."""
    with patch("bot.casino.store") as mock_store:
        mock_store.get.return_value = "8"
        from bot.casino import spin_slots

        with patch("bot.casino.random.choice", side_effect=["🎩", "💰", "🔫"]):
            result = spin_slots(123, 8)
        assert result["balance"] == 5
        mock_store.set.assert_called_with("casino_balance:123", "5")
