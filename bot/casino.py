import random
from bot.clients import store
from bot.config import CASINO_MIN_BALANCE, CASINO_STARTING_BALANCE

SLOT_SYMBOLS = ["🎩", "💰", "🔫", "🍷", "🎲"]


def get_balance(user_id: int) -> int:
    """Return the user's casino balance in dollars.

    A first-time user is initialized to CASINO_STARTING_BALANCE and that
    value is persisted immediately, so /slots and /balance agree on the
    same starting point. Falls back to the starting balance (without
    persisting) if storage is unconfigured or fails.
    """
    if store is None:
        return CASINO_STARTING_BALANCE
    try:
        data = store.get(f"casino_balance:{user_id}")
        if data is not None:
            return int(data)
        store.set(f"casino_balance:{user_id}", str(CASINO_STARTING_BALANCE))
        return CASINO_STARTING_BALANCE
    except Exception as e:
        print(f"Store read error (casino): {e}")
        return CASINO_STARTING_BALANCE


def _set_balance(user_id: int, balance: int) -> int:
    """Persist `balance`, floored at CASINO_MIN_BALANCE. Returns the
    floored value actually stored."""
    balance = max(balance, CASINO_MIN_BALANCE)
    if store is None:
        return balance
    try:
        store.set(f"casino_balance:{user_id}", str(balance))
    except Exception as e:
        print(f"Store write error (casino): {e}")
    return balance


def spin_slots(user_id: int, bet: int) -> dict:
    """Spin the slots, settle `bet` against the user's balance, and return
    the result as {symbols, win, payout, balance}.

    Payout: three matching symbols pays 10x the bet, any two matching pays
    2x, no match loses the bet. The new balance is floored at
    CASINO_MIN_BALANCE so a losing streak never locks a user out.
    """
    balance = get_balance(user_id)
    symbols = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    if symbols[0] == symbols[1] == symbols[2]:
        payout = bet * 10
    elif symbols[0] == symbols[1] or symbols[1] == symbols[2] or symbols[0] == symbols[2]:
        payout = bet * 2
    else:
        payout = 0
    new_balance = _set_balance(user_id, balance - bet + payout)
    return {
        "symbols": symbols,
        "win": payout > 0,
        "payout": payout,
        "balance": new_balance,
    }
