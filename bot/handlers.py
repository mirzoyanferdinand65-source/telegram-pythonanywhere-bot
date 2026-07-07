import os
from datetime import datetime
from telebot import types
from bot.clients import bot, BOT_INFO, store
from bot.config import (
    COMMIT_SHA,
    HF_SPACE_ID,
    HOSTING_LABEL,
    KB_MAX_UPLOAD_BYTES,
    MODEL,
    RATE_LIMIT,
    SYSTEM_PROMPT,
)
from bot import knowledge
from bot.ai import ask_ai
from bot.helpers import is_admin, is_allowed, keep_typing, send_reply, should_respond
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
    "the laws, tax rules, and legal codes of the Republic of Armenia. Keep it to a "
    "friendly introduction — do not answer a legal question or cite an article here."
)
# Shown if the live AI call fails (timeout, provider error, etc.) so /about
# never breaks as a version/health probe.
_ABOUT_FALLBACK = (
    "Hello, I am Ardar, your AI legal information assistant. I am here to help "
    "you navigate the legislation, codes, and tax regulations of the Republic of Armenia. "
    "I reply in English or Russian."
)

# One-off instruction used by /help to have the bot describe what it does in
# its own (SYSTEM_PROMPT-defined) voice. The command list below is rendered
# from code — only this descriptive blurb is generated live.
_HELP_PROMPT = (
    "In a few short, respectful lines and in your own voice, tell a new user what you can "
    "do for them regarding RA jurisprudence and how to interact with you. Keep it to a "
    "description of your help — do not answer a legal question or cite an article here."
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
        "/documents — Browse and download the official legal documents",
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


# --- Knowledge base: document upload (admin), listing, and download ---


@bot.message_handler(commands=["myid"], func=is_allowed)
def cmd_myid(message):
    # Lets the owner discover the numeric ID to put in ADMIN_USERS.
    bot.send_message(
        message.chat.id,
        f"Your Telegram user ID: `{message.from_user.id}`",
        parse_mode="Markdown",
    )


@bot.message_handler(content_types=["document"], func=is_allowed)
def handle_document(message):
    """Ingest an admin-uploaded PDF into the knowledge base.

    Only admins (ADMIN_USERS) may upload; everyone else gets a polite refusal
    so the knowledge base can't be poisoned. The PDF is downloaded, its text
    extracted and indexed, and Telegram's file_id is stored so the file can be
    re-sent to any user via /documents without keeping it on the server."""
    if not is_admin(message):
        bot.send_message(
            message.chat.id,
            "⛔ Only the administrator can add documents to my knowledge base.",
        )
        return
    if not knowledge.available():
        bot.send_message(
            message.chat.id,
            "Knowledge base is not configured — persistent storage (SQLITE_PATH) is required.",
        )
        return
    doc = message.document
    name = (getattr(doc, "file_name", None) or "document.pdf").strip()
    if not name.lower().endswith(".pdf"):
        bot.send_message(message.chat.id, "Please send a PDF file (a .pdf document).")
        return
    if (getattr(doc, "file_size", 0) or 0) > KB_MAX_UPLOAD_BYTES:
        bot.send_message(
            message.chat.id,
            "That file is larger than 20 MB — Telegram bots can't download files that big. "
            "Please split it into smaller PDFs and send them one by one.",
        )
        return
    try:
        with keep_typing(message.chat.id):
            file_info = bot.get_file(doc.file_id)
            data = bot.download_file(file_info.file_path)
            result = knowledge.ingest(
                data,
                title=name,
                file_id=doc.file_id,
                file_unique_id=getattr(doc, "file_unique_id", None),
                uploader_id=message.from_user.id,
            )
    except Exception as e:
        print(f"Document ingest error: {e}")
        bot.send_message(message.chat.id, "⚠️ Failed to download or process that document.")
        return
    if result.get("ok"):
        bot.send_message(
            message.chat.id,
            f"✅ Indexed *{result['title']}* — {result['chunk_count']} searchable sections "
            f"(uploaded {result['upload_date']}).\n\nMy answers will now cite it when relevant, "
            "and users can download it via /documents.",
            parse_mode="Markdown",
        )
        _log(message, "out", f"[ingested] {result['title']} ({result['chunk_count']} chunks)")
    else:
        bot.send_message(message.chat.id, f"⚠️ {result.get('error', 'Could not index the document.')}")


@bot.message_handler(commands=["documents"], func=is_allowed)
def cmd_documents(message):
    """List available documents with inline download buttons for any user."""
    docs = knowledge.list_documents()
    if not docs:
        bot.send_message(
            message.chat.id,
            "📚 No documents have been uploaded yet. The administrator can add legal "
            "codes and the Constitution, and they'll show up here for download.",
        )
        return
    markup = types.InlineKeyboardMarkup()
    lines = ["📚 *Available legal documents:*", ""]
    for d in docs:
        suffix = f" — id {d['doc_id']}" if is_admin(message) else ""
        lines.append(f"• {d['title']} (uploaded {d['upload_date']}){suffix}")
        if d.get("file_id"):
            markup.add(
                types.InlineKeyboardButton(
                    f"⬇ {d['title']}", callback_data=f"kbdl:{d['doc_id']}"
                )
            )
    bot.send_message(
        message.chat.id, "\n".join(lines), reply_markup=markup, parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda c: (getattr(c, "data", "") or "").startswith("kbdl:"))
def cb_download_document(call):
    """Re-send a stored document to the user who tapped its download button."""
    try:
        doc_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    d = knowledge.get_document(doc_id)
    if not d or not d.get("file_id"):
        bot.answer_callback_query(call.id, "That document is no longer available.")
        return
    try:
        bot.send_document(
            call.message.chat.id,
            d["file_id"],
            caption=f"{d['title']} (uploaded {d['upload_date']})",
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Document download error: {e}")
        bot.answer_callback_query(call.id, "Could not send that file.")


@bot.message_handler(commands=["deldoc"], func=is_allowed)
def cmd_deldoc(message):
    """Admin-only: remove a document (and its index) by id (see /documents)."""
    if not is_admin(message):
        bot.send_message(message.chat.id, "⛔ Only the administrator can remove documents.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        bot.send_message(
            message.chat.id,
            "Usage: `/deldoc <document id>` — run /documents to see each id.",
            parse_mode="Markdown",
        )
        return
    doc_id = int(parts[1].strip())
    d = knowledge.get_document(doc_id)
    if knowledge.delete_document(doc_id):
        bot.send_message(message.chat.id, f"🗑️ Removed *{d['title']}* from the knowledge base.", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, f"No document with id {doc_id} was found.")


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
        # TEMPORARY DEBUG: surface the real exception in the reply so we can
        # diagnose without PA console access. Revert after diagnosis.
        error_msg = f"⚠️ DEBUG — {type(e).__name__}: {e}"
        bot.send_message(message.chat.id, error_msg)
        _log(message, "out", f"[error] {e}")