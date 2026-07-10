"""Per-user 'active document' selection — the document a user is currently
studying. When set, bot/ai.py answers strictly from that one document
(study mode); when unset, the bot free-chats about jurisprudence generally.

Mirrors bot/preferences.py: state lives in the KV store under
``active_doc:{user_id}`` with no TTL. In stateless mode (no SQLITE_PATH) there
is no persistence, so every user is always in free-chat mode — a safe default.
"""

from bot.clients import store


def get_active_doc(user_id: int) -> int | None:
    """Return the doc_id the user is studying, or None for free-chat mode.

    None whenever storage is unconfigured/down, nothing is selected, or the
    stored value is somehow not an integer."""
    if store is None:
        return None
    try:
        value = store.get(f"active_doc:{user_id}")
    except Exception as e:
        print(f"Store read error (active_doc): {e}")
        return None
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def set_active_doc(user_id: int, doc_id: int) -> bool:
    """Select a document to study. Returns True on success."""
    if store is None:
        return False
    try:
        store.set(f"active_doc:{user_id}", str(doc_id))
        return True
    except Exception as e:
        print(f"Store write error (active_doc): {e}")
        return False


def clear_active_doc(user_id: int) -> bool:
    """Exit study mode (back to free chat). Returns True on success."""
    if store is None:
        return False
    try:
        store.delete(f"active_doc:{user_id}")
        return True
    except Exception as e:
        print(f"Store delete error (active_doc): {e}")
        return False
