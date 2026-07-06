import threading
from contextlib import contextmanager
from bot.clients import bot
from bot.config import ADMIN_USERS, ALLOWED_USERS, MAX_MSG_LEN

# Pre-compute lookup sets so per-message is_allowed() is O(1).
# Numeric IDs are matched as strings against str(user.id).
_ALLOWED_USERNAMES = {u.lower() for u in ALLOWED_USERS if not u.isdigit()}
_ALLOWED_USER_IDS = {u for u in ALLOWED_USERS if u.isdigit()}
_ADMIN_USERNAMES = {u.lower() for u in ADMIN_USERS if not u.isdigit()}
_ADMIN_USER_IDS = {u for u in ADMIN_USERS if u.isdigit()}

# Telegram "typing" chat action expires after ~5 seconds, so re-send it every
# 4 seconds while slow providers (e.g. HF ArmGPT) are generating.
TYPING_REFRESH_SECONDS = 4


def _split_for_telegram(text: str, limit: int) -> list[str]:
    """Split text into chunks that each fit Telegram's per-message limit.

    Prefers paragraph and line breaks over hard cuts so we don't slice in
    the middle of a Markdown entity (which would make Telegram reject the
    whole chunk). Falls back to a hard cut only if a single line is too
    long to fit.
    """
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        # Look for the last newline within the first `limit` chars; prefer
        # double-newline (paragraph break), then single newline, then hard cut.
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut <= 0:
            cut = window.rfind("\n")
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def send_reply(message, text: str) -> None:
    """Send a reply, splitting and Markdown-fallback safely.

    Telegram's Markdown parser is strict — unbalanced ``*`` or ``[`` from
    the model or from search-result titles will reject the entire message.
    On parse errors we retry the same chunk as plain text. If even the
    plain-text send fails we re-raise: the webhook caller relies on this
    signal to skip the dedupe marker so Telegram can retry.
    """
    for chunk in _split_for_telegram(text, MAX_MSG_LEN):
        try:
            bot.send_message(message.chat.id, chunk, parse_mode="Markdown")
        except Exception as e:
            print(f"Markdown send failed, retrying as plain text: {e}")
            bot.send_message(message.chat.id, chunk)


@contextmanager
def keep_typing(chat_id: int):
    """Keep the Telegram "typing" indicator alive while the block runs.

    Spawns a background thread that re-sends the typing action every few
    seconds until the context exits, then joins the thread before returning
    so the serverless function can shut down cleanly.
    """
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                bot.send_chat_action(chat_id, "typing")
            except Exception as e:
                print(f"typing indicator error: {e}")
                return
            # Use wait() so we can exit early when stop is set
            if stop.wait(TYPING_REFRESH_SECONDS):
                return

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def should_respond(message) -> bool:
    """Respond to all messages in private chats and group chats."""
    return True


def is_allowed(message) -> bool:
    """Telegram-handler `func=` filter implementing the ALLOWED_USERS whitelist.

    Returns True when the whitelist is empty (default — everyone allowed)
    OR when the sender's username (case-insensitive) or numeric user_id
    is in the list. Non-matching messages cause telebot to skip every
    handler, so the bot stays silent for unauthorized users.
    """
    if not ALLOWED_USERS:
        return True
    user = getattr(message, "from_user", None)
    if user is None:
        return False
    if str(getattr(user, "id", "")) in _ALLOWED_USER_IDS:
        return True
    username = getattr(user, "username", "") or ""
    return username.lower() in _ALLOWED_USERNAMES


def is_admin(message) -> bool:
    """True only for users in ADMIN_USERS (by numeric id or username).

    Fail-closed: when ADMIN_USERS is empty, nobody is an admin, so the
    document-upload handler stays locked until an admin is configured."""
    user = getattr(message, "from_user", None)
    if user is None:
        return False
    if str(getattr(user, "id", "")) in _ADMIN_USER_IDS:
        return True
    username = getattr(user, "username", "") or ""
    return bool(_ADMIN_USERNAMES) and username.lower() in _ADMIN_USERNAMES
