import json
from bot.clients import store
from bot.config import MAX_NOTES


def get_notes(user_id: int) -> list:
    """Return the user's saved notes (oldest first), or an empty list.

    Falls back to an empty list if storage is unconfigured (stateless mode)
    or fails, matching the graceful-degradation pattern used elsewhere.
    """
    if store is None:
        return []
    try:
        data = store.get(f"notes:{user_id}")
        return json.loads(data) if data else []
    except Exception as e:
        print(f"Store read error (notes): {e}")
        return []


def add_note(user_id: int, text: str) -> bool:
    """APPEND a note to the user's existing notes — never replaces them.

    Reads the current list, adds the new note to the end, trims to the most
    recent MAX_NOTES, and saves. Returns True on success, False if storage is
    unconfigured or the write fails. No TTL: notes are meant to persist.
    """
    if store is None:
        return False
    try:
        notes = get_notes(user_id)
        notes.append(text)
        store.set(f"notes:{user_id}", json.dumps(notes[-MAX_NOTES:]))
        return True
    except Exception as e:
        print(f"Store write error (notes): {e}")
        return False


def clear_notes(user_id: int) -> None:
    """Delete all of the user's notes."""
    if store is None:
        return
    try:
        store.delete(f"notes:{user_id}")
    except Exception as e:
        print(f"Store delete error (notes): {e}")
