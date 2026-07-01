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
    "Introduce yourself to a new user in 3-4 short, warm lines: who you are "
    "and how you can help them. Do not analyze or define any word here — this "
    "is just a friendly introduction."
)
# Shown if the live AI call fails (timeout, provider error, etc.) so /about
# never breaks as a version/health probe.
_ABOUT_FALLBACK = "Hi! I'm your English vocabulary coach. 📖 Send me any English word and I'll help you learn it."

# One-off instruction used by /help to have the bot describe what it does in
# its own (SYSTEM_PROMPT-defined) voice. The command list below is rendered
# from code — only this descriptive blurb is generated live.
_HELP_PROMPT = (
    "In a few short lines and in your own voice, tell a new user what you can "
    "do for them and how to use you. Do not analyze or define any word here — "
    "this is a description of your help, not an example."
)
# Shown if the live AI call fails so /help always lists the commands.
_HELP_FALLBACK = (
    "I'm your English vocabulary coach. 📖 Send me any English word and I'll "
    "give you its pronunciation, CEFR level, Russian and Armenian translations, "
    "a clear definition, synonyms, antonyms, examples, and collocations."
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
        "👋 Welcome! I'm your English vocabulary coach.\n"
        "\n"
        "Here's how to use me: just send me any English word, and I'll explain it for you — "
        "its pronunciation, CEFR level (A1–C2), translations in Russian and Armenian, "
        "a clear definition, synonyms and antonyms, example sentences, and common collocations.\n"
        "\n"
        "Try it now — send me a word like:\n"
        "    resilient\n"
        "\n"
        "Type /help any time to see what I can do."
    )
    bot.send_message(message.chat.id, text)



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
        "Commands:",
        "/start — say hello and get started",
        "/help  — show this message",
        "/reset — clear our conversation and start fresh",
        "/about — what powers me",
        "/joke  — hear a fresh joke",
        "/quote — get a motivational quote",
        "/fact  — learn a surprising fact",
        "/compliment — get a kind word",
        "/roast <name> — get a playful roast",
        "/remember <note> — save a note (adds, never replaces)",
        "/recall — show all your saved notes",
        "/forget — delete all your saved notes",
    ]
    if HF_SPACE_ID:
        lines.append("/model — switch the AI engine I run on")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["reset"], func=is_allowed)
def cmd_reset(message):
    clear_history(message.from_user.id)
    bot.send_message(message.chat.id, "Conversation cleared. Starting fresh!")


@bot.message_handler(commands=["about"], func=is_allowed)
def cmd_about(message):
    if HF_SPACE_ID:
        provider = get_provider(message.from_user.id)
        model_line = f"{MODEL} (main)" if provider == "main" else f"{HF_SPACE_ID} (hf)"
    else:
        model_line = MODEL
    storage_line = "SQLite" if store is not None else "stateless (no memory)"

    # Persona intro is generated live so it always speaks in the current
    # SYSTEM_PROMPT voice; the technical block below stays code-rendered.
    intro = _persona_blurb(
        message.chat.id, message.from_user.id, _ABOUT_PROMPT, _ABOUT_FALLBACK
    )

    lines = [
        intro,
        "",
        "— Under the hood —",
        f"Model  : {model_line}",
        f"Storage: {storage_line}",
        f"Hosting: {HOSTING_LABEL}",
    ]
    if COMMIT_SHA:
        lines.append(f"Version: {COMMIT_SHA}")
    bot.send_message(message.chat.id, "\n".join(lines))


if HF_SPACE_ID:

    @bot.message_handler(commands=["model"], func=is_allowed)
    def cmd_model(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            current = get_provider(message.from_user.id)
            bot.send_message(
                message.chat.id,
                f"Current provider: {current}\n\n"
                "Options:\n"
                "/model main — Cerebras (fast, multilingual, with memory)\n"
                "/model hf — ArmGPT (Armenian only, slow, no memory)",
            )
            return
        choice = parts[1].strip().lower()
        if choice not in ("main", "hf"):
            bot.send_message(
                message.chat.id, "Invalid choice. Use: /model main or /model hf"
            )
            return
        if not set_provider(message.from_user.id, choice):
            bot.send_message(
                message.chat.id, "Could not save preference. Try again later."
            )
            return
        if choice == "hf":
            bot.send_message(
                message.chat.id,
                "Switched to hf (ArmGPT).\n\n"
                "Note: this is a tiny base completion model trained only on Armenian text. "
                "It will continue whatever you write rather than answer questions, "
                "and it does not understand English. Replies take ~30-60s and there is no memory.",
            )
        else:
            bot.send_message(message.chat.id, "Switched to Main Provider.")


# --- Fun one-shot AI commands (/joke, /quote, /fact, /compliment) ---
#
# These are all "one-shot" commands: a single AI generation with no memory.
# They are intentionally DECOUPLED from the bot's vocabulary-coach persona —
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
            f"You've reached the daily limit of {RATE_LIMIT} messages. Try again tomorrow.",
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


_JOKE_SYSTEM = (
    "You are a witty, family-friendly stand-up comedian. Reply with exactly "
    "one short, clean, original joke and nothing else — no preamble, no emoji "
    "unless it's part of the punchline. Pick any topic you like and surprise "
    "the user with something different each time."
)
_JOKE_FALLBACK = "I'd tell you a joke about the internet, but it might not load. 😄"


@bot.message_handler(commands=["joke"], func=is_allowed)
def cmd_joke(message):
    _ai_oneshot(message, _JOKE_SYSTEM, "Tell me a joke.", _JOKE_FALLBACK)


_QUOTE_SYSTEM = (
    "You are a concise motivational writer. Reply with exactly one original, "
    "uplifting one-line quote and nothing else — no author, no quotation "
    "marks, no preamble. Make it fresh and different each time."
)
_QUOTE_FALLBACK = "Small steps every day still carry you further than standing still. ✨"


@bot.message_handler(commands=["quote"], func=is_allowed)
def cmd_quote(message):
    _ai_oneshot(message, _QUOTE_SYSTEM, "Give me a motivational quote.", _QUOTE_FALLBACK)


_FACT_SYSTEM = (
    "You are a knowledgeable trivia host. Reply with exactly one surprising, "
    "true, little-known fact and nothing else — one or two sentences, no "
    "preamble, no 'Did you know'. Pick any topic and make it different each time."
)
_FACT_FALLBACK = "Honey never spoils — archaeologists have found 3,000-year-old honey still edible. 🍯"


@bot.message_handler(commands=["fact"], func=is_allowed)
def cmd_fact(message):
    _ai_oneshot(message, _FACT_SYSTEM, "Tell me a surprising fact.", _FACT_FALLBACK)


_COMPLIMENT_SYSTEM = (
    "You are warm and encouraging. Reply with exactly one short, genuine, "
    "uplifting compliment addressed directly to the user ('you') and nothing "
    "else — no preamble, no name. Keep it kind and sincere, and make it "
    "different each time."
)
_COMPLIMENT_FALLBACK = "You show up and keep trying, and that quiet persistence is something special. 🌟"


@bot.message_handler(commands=["compliment"], func=is_allowed)
def cmd_compliment(message):
    _ai_oneshot(message, _COMPLIMENT_SYSTEM, "Give me a compliment.", _COMPLIMENT_FALLBACK)


# /roast takes an argument: /roast <name>. It's a playful comedy-roast — harsh
# and savage in tone, but guardrailed (no slurs, no hate, no attacks on real
# protected traits) since this is a students' bot. Reuses _ai_oneshot with a
# per-name user prompt.
_ROAST_SYSTEM = (
    "You are a savage but playful comedy-roast writer. Given a name, reply with "
    "exactly one short, punchy, brutal roast of that name and nothing else — "
    "one or two sentences, no preamble. Be witty and harsh like a stand-up "
    "roast, but keep it PG-13: no slurs, no profanity, no hate, and never "
    "attack real protected traits (race, religion, gender, disability, etc.). "
    "Roast the vibe of the name itself. Make it different each time."
)


@bot.message_handler(commands=["roast"], func=is_allowed)
def cmd_roast(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(
            message.chat.id, "Usage: /roast <name>\nExample: /roast Kevin"
        )
        return
    name = parts[1].strip()
    fallback = f"{name}? I'd roast you, but my circuits fell asleep halfway through. 😴"
    _ai_oneshot(message, _ROAST_SYSTEM, f"Roast this name: {name}", fallback)


@bot.message_handler(commands=["remember"], func=is_allowed)
def cmd_remember(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(
            message.chat.id,
            "Usage: /remember <note>\nExample: /remember buy milk tomorrow",
        )
        return
    note = parts[1].strip()
    # add_note APPENDS to the user's existing notes — it never replaces them.
    if add_note(message.from_user.id, note):
        count = len(get_notes(message.from_user.id))
        bot.send_message(message.chat.id, f"Got it — saved. You now have {count} note(s).")
    else:
        # Storage unconfigured (stateless mode) or a write error.
        bot.send_message(
            message.chat.id,
            "I can't save notes right now — memory isn't set up on this bot.",
        )


@bot.message_handler(commands=["recall"], func=is_allowed)
def cmd_recall(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "I can't recall notes right now — memory isn't set up on this bot.",
        )
        return
    notes = get_notes(message.from_user.id)
    if not notes:
        bot.send_message(
            message.chat.id,
            "You don't have any saved notes yet. Add one with /remember <note>.",
        )
        return
    lines = ["Your notes:"] + [f"{i}. {note}" for i, note in enumerate(notes, 1)]
    # send_reply handles Telegram's 4096-char limit if the list is long.
    send_reply(message, "\n".join(lines))


@bot.message_handler(commands=["forget"], func=is_allowed)
def cmd_forget(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "There's nothing to forget — memory isn't set up on this bot.",
        )
        return
    had = len(get_notes(message.from_user.id))
    if not had:
        bot.send_message(message.chat.id, "You have no saved notes to forget.")
        return
    clear_notes(message.from_user.id)
    bot.send_message(message.chat.id, f"Done — deleted all {had} of your notes.")


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
        limit_msg = f"You've reached the daily limit of {RATE_LIMIT} messages. Try again tomorrow."
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
        bot.send_message(message.chat.id, "Something went wrong. Please try again.")
        _log(message, "out", f"[error] {e}")

