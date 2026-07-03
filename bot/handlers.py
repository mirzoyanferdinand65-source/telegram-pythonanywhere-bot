import os
from datetime import datetime
from bot.clients import bot, BOT_INFO, store
from bot.config import (
    COMMIT_SHA,
    HF_SPACE_ID,
    HOSTING_LABEL,
    MODEL,
    RATE_LIMIT,
    SYSTEM_PROMPT,
)
from bot.ai import ask_ai
from bot.casino import get_balance, spin_slots
from bot.helpers import is_allowed, keep_typing, send_reply, should_respond
from bot.history import clear_history
from bot.notes import add_note, clear_notes, get_notes
from bot.preferences import get_provider, set_provider
from bot.providers import generate
from bot.rate_limit import is_rate_limited

# One-off instruction used by /about to have the bot introduce itself in
# its own (SYSTEM_PROMPT-defined) voice. Generated live, not from history,
# so it always reflects the current persona and never pollutes the user's
# learning conversation.
_ABOUT_PROMPT = (
    "Introduce yourself to a new user in 3-4 short, warm, and professional lines: "
    "who you are (Ardar, the RA Legal Assistant) and how you can help them look up "
    "laws, taxes, and legal codes. Do not analyze or define any word here — this "
    "is just a friendly introduction."
)
# Shown if the live AI call fails (timeout, provider error, etc.) so /about
# never breaks as a version/health probe.
_ABOUT_FALLBACK = (
    "Ողջույն, I am Ardar (Արդար), your AI legal information assistant. I am here to help "
    "you navigate the legislation, codes, and tax regulations of the Republic of Armenia."
)

# One-off instruction used by /help to have the bot describe what it does in
# its own (SYSTEM_PROMPT-defined) voice. The command list below is rendered
# from code — only this descriptive blurb is generated live.
_HELP_PROMPT = (
    "In a few short, respectful lines and in your own voice, tell a new user what you can "
    "do for them regarding RA jurisprudence and how to interact with you. Do not analyze "
    "or define any word here — this is a description of your help, not an example."
)
# Shown if the live AI call fails so /help always lists the commands.
_HELP_FALLBACK = (
    "I can help you look up articles, understand tax deadlines, or clarify legal procedures "
    "in the Republic of Armenia. Please use the commands below or ask your legal question directly."
)


def _persona_blurb(chat_id: int, user_id: int, prompt: str, fallback: str) -> str:
    """Generate a short persona description live, in the current SYSTEM_PROMPT
    voice. Built as a one-off message list (not via ask_ai) so it never lands
    in the user's saved history, shows a typing indicator while generating, and
    falls back to static text on any failure so the calling command never breaks."""
    try:
        with keep_typing(chat_id):
            text = generate(
                user_id,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        return (text or "").strip() or fallback
    except Exception as e:
        print(f"Error generating persona blurb: {e}")
        return fallback

# Verbose console logging for local dev and teaching. Enabled by
# BOT_VERBOSE_LOG=1 (run_local.py sets this automatically). Prints one
# line per inbound/outbound message so kids and teachers can see the
# conversation flow in their terminal while the bot is running.
VERBOSE_LOG = os.environ.get("BOT_VERBOSE_LOG", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _log(message, direction: str, text: str) -> None:
    """Print a one-line trace of a message in verbose mode.

    direction is "in" (user → bot) or "out" (bot → user). Text is
    truncated to 500 characters so long AI replies don't flood the
    terminal. Newlines are collapsed for single-line readability.
    """
    if not VERBOSE_LOG:
        return
    user = message.from_user
    user_name = (
        f"@{user.username}" if user.username else (user.first_name or f"user:{user.id}")
    )
    bot_name = f"@{BOT_INFO.username}"
    snippet = (text or "").replace("\n", " ").replace("\r", " ")
    if len(snippet) > 500:
        snippet = snippet[:500] + "..."
    if direction == "in":
        sender, receiver = user_name, bot_name
    else:
        sender, receiver = bot_name, user_name
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {sender} → {receiver}: {snippet}", flush=True)


@bot.message_handler(commands=["start"], func=is_allowed)
def cmd_start(message):
    text = (
        "⚖️ **Welcome to Ardar (Արդար) — RA Legal Assistant**\n"
        "\n"
        "My purpose is to make the jurisprudence system of the Republic of Armenia "
        "accessible, clear, and transparent for every citizen.\n"
        "\n"
        "You can ask me questions about the **RA Constitution, Tax Code, Civil Code, "
        "Criminal Code, Labor Code**, or specific legal scenarios (e.g., tax deadlines for Sole Proprietors/IE).\n"
        "\n"
        "👉 Please enter your question directly, or type /help to review available commands."
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")


@bot.message_handler(commands=["help"], func=is_allowed)
def cmd_help(message):
    # Persona blurb is generated live so it always reflects the current
    # SYSTEM_PROMPT voice; the command list below is rendered from code
    # because it's factual (the real commands), not persona text.
    blurb = _persona_blurb(
        message.chat.id, message.from_user.id, _HELP_PROMPT, _HELP_FALLBACK
    )
    lines = [
        blurb,
        "",
        "**Available Operations:**",
        "/start — Initialize the assistant and view greeting",
        "/help  — Display this system operational guide",
        "/reset — Clear active consultation history and start fresh",
        "/about — View technical specifications and system framework",
        "/sha   — Verify the system's live deployment version",
        "/remember <note> — Store a custom legal reminder or bookmark",
        "/recall — View your saved reminders and bookmarks",
        "/forget — Clear your saved reminders layout",
    ]
    if HF_SPACE_ID:
        lines.append("/model — Toggle the backend processing model")
    bot.send_message(message.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["reset"], func=is_allowed)
def cmd_reset(message):
    clear_history(message.from_user.id)
    bot.send_message(message.chat.id, "🔄 The consultation history has been reset. You can start a new inquiry.")


@bot.message_handler(commands=["about"], func=is_allowed)
def cmd_about(message):
    if HF_SPACE_ID:
        provider = get_provider(message.from_user.id)
        model_line = f"{MODEL} (main)" if provider == "main" else f"{HF_SPACE_ID} (hf)"
    else:
        model_line = MODEL
    storage_line = "SQLite Database" if store is not None else "Stateless (No Local Memory)"

    # Persona intro is generated live so it always speaks in the current
    # SYSTEM_PROMPT voice; the technical block below stays code-rendered.
    intro = _persona_blurb(
        message.chat.id, message.from_user.id, _ABOUT_PROMPT, _ABOUT_FALLBACK
    )

    lines = [
        intro,
        "",
        "📊 **— Technical Architecture —**",
        f"Processing Engine: {model_line}",
        f"Data Ledger      : {storage_line}",
        f"Hosting Node     : {HOSTING_LABEL}",
    ]
    if COMMIT_SHA:
        lines.append(f"Deployment SHA   : `{COMMIT_SHA}`")
    bot.send_message(message.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["sha"], func=is_allowed)
def cmd_sha(message):
    sha = COMMIT_SHA or "unknown"
    bot.send_message(message.chat.id, f"System Deployment SHA: `{sha}`", parse_mode="Markdown")


if HF_SPACE_ID:

    @bot.message_handler(commands=["model"], func=is_allowed)
    def cmd_model(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            current = get_provider(message.from_user.id)
            bot.send_message(
                message.chat.id,
                f"Current processing engine: **{current}**\n\n"
                "Available configurations:\n"
                "/model main — Cerebras Engine (Fast, multi-lingual contextual logic)\n"
                "/model hf — ArmGPT Engine (Specialized native text expansion)",
                parse_mode="Markdown"
            )
            return
        choice = parts[1].strip().lower()
        if choice not in ("main", "hf"):
            bot.send_message(
                message.chat.id, "Selection error. Please apply command syntax: `/model main` or `/model hf`", parse_mode="Markdown"
            )
            return
        if not set_provider(message.from_user.id, choice):
            bot.send_message(
                message.chat.id, "Database transaction error. Could not modify engine preference at this time."
            )
            return
        if choice == "hf":
            bot.send_message(
                message.chat.id,
                "Switched to processing engine: **hf (ArmGPT)**.\n\n"
                "⚠️ *System Note: This config operates via an Armenian text continuation module. "
                "Context retention is omitted, and execution speeds may scale up to 30-60s.*",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(message.chat.id, "Switched to **Main Processing Engine**.", parse_mode="Markdown")


# --- Fun one-shot AI commands (/joke, /quote, /fact, /compliment) ---
#
# These are all "one-shot" commands: a single AI generation with no memory.
# They are intentionally DECOUPLED from the bot's main SYSTEM_PROMPT persona —
# each carries its own neutral system prompt (NOT SYSTEM_PROMPT) and calls
# generate() directly with a one-off message list, so their output never
# touches the user's learning history and isn't steered toward word/dictionary
# themes. Variety across repeated calls comes from the provider's own sampling.


def _ai_oneshot(message, system_prompt: str, user_prompt: str, fallback: str) -> None:
    """Run a single stateless AI generation and send the reply.

    Shared body for /joke, /quote, /fact, /compliment. Handles the daily rate
    limit, shows the typing indicator, and falls back to a static string on any
    error or empty response so the command never breaks.
    """
    if is_rate_limited(message.from_user.id):
        bot.send_message(
            message.chat.id,
            f"You have reached your daily limit of {RATE_LIMIT} queries. Please return tomorrow for further assistance.",
        )
        return
    try:
        with keep_typing(message.chat.id):
            reply = generate(
                message.from_user.id,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        reply = (reply or "").strip() or fallback
    except Exception as e:
        print(f"Error in _ai_oneshot ({user_prompt!r}): {e}")
        reply = fallback
    bot.send_message(message.chat.id, reply)


@bot.message_handler(commands=["remember"], func=is_allowed)
def cmd_remember(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(
            message.chat.id,
            "Usage syntax: `/remember <legal note / bookmark>`\nExample: `/remember Tax submission deadline is April 20`",
            parse_mode="Markdown"
        )
        return
    note = parts[1].strip()
    # add_note APPENDS to the user's existing notes — it never replaces them.
    if add_note(message.from_user.id, note):
        count = len(get_notes(message.from_user.id))
        bot.send_message(message.chat.id, f"📝 Legal note cataloged securely. Your registry currently holds {count} entries.")
    else:
        # Storage unconfigured (stateless mode) or a write error.
        bot.send_message(
            message.chat.id,
            "Storage access denied. The data ledger is currently unconfigured or closed.",
        )


@bot.message_handler(commands=["recall"], func=is_allowed)
def cmd_recall(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "Storage access denied. The data ledger is currently unconfigured or closed.",
        )
        return
    notes = get_notes(message.from_user.id)
    if not notes:
        bot.send_message(
            message.chat.id,
            "Your legal notebook is currently empty. Use `/remember <note>` to document critical entries.",
            parse_mode="Markdown"
        )
        return
    lines = ["📋 **Your Registered Legal Notes:**"] + [f"{i}. {note}" for i, note in enumerate(notes, 1)]
    # send_reply handles Telegram's 4096-char limit if the list is long.
    send_reply(message, "\n".join(lines))


@bot.message_handler(commands=["forget"], func=is_allowed)
def cmd_forget(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "Storage modification denied. The data ledger is closed.",
        )
        return
    had = len(get_notes(message.from_user.id))
    if not had:
        bot.send_message(message.chat.id, "There are no active entries in your notebook to remove.")
        return
    clear_notes(message.from_user.id)
    bot.send_message(message.chat.id, f"🧹 Action completed. All {had} registered notebook entries have been permanently purged.")


# --- Casino (virtual currency only — no real money involved anywhere) ---




@bot.message_handler(content_types=["text"], func=is_allowed)
def handle_message(message):
    if not should_respond(message):
        return
    text = (message.text or "").replace(f"@{BOT_INFO.username}", "").strip()
    if not text:
        # Edited messages, forwards, or stickers-with-empty-caption can
        # arrive with no usable text. Don't burn rate-limit / AI calls on them.
        return
    _log(message, "in", text)
    if is_rate_limited(message.from_user.id):
        limit_msg = f"You have reached your daily processing allocation threshold ({RATE_LIMIT} queries). Please re-submit your query tomorrow."
        bot.send_message(message.chat.id, limit_msg)
        _log(message, "out", f"[rate limited] {limit_msg}")
        return
    try:
        with keep_typing(message.chat.id):
            reply = ask_ai(message.from_user.id, text)
        send_reply(message, reply)
        _log(message, "out", reply)
    except Exception as e:
        print(f"Error in handle_message: {e}")
        error_msg = "⚠️ An infrastructure or processing exception occurred on the legal server network. Please resubmit your query shortly."
        bot.send_message(message.chat.id, error_msg)
        _log(message, "out", f"[error] {e}")