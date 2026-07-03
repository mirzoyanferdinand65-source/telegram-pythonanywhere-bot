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
    "Introduce yourself to a new user in 3-4 short, warm lines: who you are "
    "and how you can help them. Do not analyze or define any word here — this "
    "is just a friendly introduction."
)
# Shown if the live AI call fails (timeout, provider error, etc.) so /about
# never breaks as a version/health probe.
_ABOUT_FALLBACK = "Ay, I'm the Don around here. You got a problem, you bring it to me — no job too big, no job too small. Fuhgeddaboutit."

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
    "I'm the Don around here. You got questions, you got problems — bring 'em "
    "to me and I'll take care of it, like family. Capisce?"
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
        "🎩 Ay, welcome, welcome. Come in, sit down.\n"
        "\n"
        "You can call me the Don. You got a question, somethin' you need figured "
        "out — you bring it to me, like family, and I'll take care of it, capisce?\n"
        "\n"
        "Go on, ask me anything.\n"
        "\n"
        "Type /help if you need the lay of the land."
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
        "Here's how we do business:",
        "/start — pay your respects to the Don",
        "/help  — this here list",
        "/reset — clean slate, we start fresh",
        "/about — who's runnin' this operation",
        "/sha   — check the boss's papers (live commit)",
        "/joke  — hear a good one",
        "/quote — a little wisdom from the Don",
        "/fact  — somethin' you didn't know",
        "/compliment — get some respect",
        "/roast <name> — we settle a score, playful-like",
        "/remember <note> — I'll keep that safe, between us",
        "/recall — see what I got on the books",
        "/forget — clean the books",
        "/balance — check what you're carrying",
        "/slots <bet> — try your luck at the tables",
    ]
    if HF_SPACE_ID:
        lines.append("/model — switch who's runnin' the show")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["reset"], func=is_allowed)
def cmd_reset(message):
    clear_history(message.from_user.id)
    bot.send_message(message.chat.id, "The slate's clean, kid. We start fresh.")


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
        "— How the operation runs —",
        f"Model  : {model_line}",
        f"Storage: {storage_line}",
        f"Hosting: {HOSTING_LABEL}",
    ]
    if COMMIT_SHA:
        lines.append(f"Version: {COMMIT_SHA}")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["sha"], func=is_allowed)
def cmd_sha(message):
    sha = COMMIT_SHA or "unknown"
    bot.send_message(message.chat.id, f"Live SHA: {sha}")


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
            f"You've used up your {RATE_LIMIT} favors for today. Come back tomorrow, capisce?",
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
    "You are a witty mafia don telling a joke to your crew. Reply with exactly "
    "one short, clean, original joke and nothing else — no preamble. A little "
    "gangster-movie flavor ('kid', 'capisce') is welcome but don't overdo it. "
    "Pick any topic and surprise them with something different each time."
)
_JOKE_FALLBACK = "I got a million of 'em, but my joke guy stepped out. Ask me again in a minute, capisce?"


@bot.message_handler(commands=["joke"], func=is_allowed)
def cmd_joke(message):
    _ai_oneshot(message, _JOKE_SYSTEM, "Tell me a joke.", _JOKE_FALLBACK)


_QUOTE_SYSTEM = (
    "You are a mafia don sharing hard-won wisdom with the family. Reply with "
    "exactly one original, motivational one-line quote in gangster-movie "
    "flavor, and nothing else — no author, no quotation marks, no preamble. "
    "Make it fresh and different each time."
)
_QUOTE_FALLBACK = "Respect is earned one day at a time, kid — nobody just hands it to you."


@bot.message_handler(commands=["quote"], func=is_allowed)
def cmd_quote(message):
    _ai_oneshot(message, _QUOTE_SYSTEM, "Give me a motivational quote.", _QUOTE_FALLBACK)


_FACT_SYSTEM = (
    "You are a mafia don who knows a little about everything, letting someone "
    "in on a secret. Reply with exactly one surprising, true, little-known "
    "fact and nothing else — one or two sentences, no preamble, no "
    "'Did you know'. Pick any topic and make it different each time."
)
_FACT_FALLBACK = "Here's somethin' for ya — honey never spoils. Found 3,000-year-old honey in a tomb, still good to eat."


@bot.message_handler(commands=["fact"], func=is_allowed)
def cmd_fact(message):
    _ai_oneshot(message, _FACT_SYSTEM, "Tell me a surprising fact.", _FACT_FALLBACK)


_COMPLIMENT_SYSTEM = (
    "You are a mafia don who's decided to show someone respect. Reply with "
    "exactly one short, genuine, uplifting compliment addressed directly to "
    "the user ('you'), delivered warmly in gangster-movie flavor, and nothing "
    "else — no preamble, no name. Keep it sincere, and make it different "
    "each time."
)
_COMPLIMENT_FALLBACK = "You got heart, kid. That's rare these days — don't lose it."


@bot.message_handler(commands=["compliment"], func=is_allowed)
def cmd_compliment(message):
    _ai_oneshot(message, _COMPLIMENT_SYSTEM, "Give me a compliment.", _COMPLIMENT_FALLBACK)


# /roast takes an argument: /roast <name>. It's a playful comedy-roast — harsh
# and savage in tone, but guardrailed (no slurs, no hate, no attacks on real
# protected traits) since this is a students' bot. Reuses _ai_oneshot with a
# per-name user prompt.
_ROAST_SYSTEM = (
    "You are a mafia don giving a playful, theatrical roast — like ribbing "
    "someone at the family table, not actually threatening them. Given a "
    "name, reply with exactly one short, punchy, savage-but-affectionate "
    "roast of that name in gangster-movie flavor, and nothing else — one or "
    "two sentences, no preamble. Keep it PG-13: no slurs, no profanity, no "
    "hate, and never attack real protected traits (race, religion, gender, "
    "disability, etc.). Roast the vibe of the name itself. Make it different "
    "each time."
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
    fallback = f"{name}? I'd roast ya, but even my guys need a coffee break. Ask me again."
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
        bot.send_message(message.chat.id, f"Consider it done — that's locked away safe. {count} thing(s) on the books now.")
    else:
        # Storage unconfigured (stateless mode) or a write error.
        bot.send_message(
            message.chat.id,
            "Can't keep notes right now — the ledger's closed on this bot.",
        )


@bot.message_handler(commands=["recall"], func=is_allowed)
def cmd_recall(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "Can't pull up the books right now — the ledger's closed on this bot.",
        )
        return
    notes = get_notes(message.from_user.id)
    if not notes:
        bot.send_message(
            message.chat.id,
            "You ain't given me nothin' to remember yet. Use /remember <note> and I'll keep it safe.",
        )
        return
    lines = ["Here's what I got on you:"] + [f"{i}. {note}" for i, note in enumerate(notes, 1)]
    # send_reply handles Telegram's 4096-char limit if the list is long.
    send_reply(message, "\n".join(lines))


@bot.message_handler(commands=["forget"], func=is_allowed)
def cmd_forget(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "Nothin' to forget — the ledger's closed on this bot.",
        )
        return
    had = len(get_notes(message.from_user.id))
    if not had:
        bot.send_message(message.chat.id, "You got nothin' on the books to forget.")
        return
    clear_notes(message.from_user.id)
    bot.send_message(message.chat.id, f"Done — wiped clean, all {had} of 'em. Never happened, capisce?")


# --- Casino (virtual currency only — no real money involved anywhere) ---


@bot.message_handler(commands=["balance"], func=is_allowed)
def cmd_balance(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "Can't check your tab right now — the ledger's closed on this bot.",
        )
        return
    balance = get_balance(message.from_user.id)
    bot.send_message(message.chat.id, f"You're carrying ${balance}, kid.")


@bot.message_handler(commands=["slots"], func=is_allowed)
def cmd_slots(message):
    if store is None:
        bot.send_message(
            message.chat.id,
            "The casino's closed — the ledger's not set up on this bot.",
        )
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /slots <bet>\nExample: /slots 10")
        return
    try:
        bet = int(parts[1].strip())
    except ValueError:
        bot.send_message(message.chat.id, "That ain't a number, kid. Usage: /slots <bet>")
        return
    if bet <= 0:
        bot.send_message(message.chat.id, "Gotta put somethin' on the table, kid — try a positive number.")
        return
    balance = get_balance(message.from_user.id)
    if bet > balance:
        bot.send_message(message.chat.id, f"You're light, kid. You've only got ${balance} on you.")
        return
    result = spin_slots(message.from_user.id, bet)
    reel = " | ".join(result["symbols"])
    if result["win"]:
        text = (
            f"[ {reel} ]\n\n"
            f"Jackpot, kid! That's ${result['payout']} for ya. Balance: ${result['balance']}."
        )
    else:
        text = f"[ {reel} ]\n\nTough break — the house wins this one. Balance: ${result['balance']}."
    bot.send_message(message.chat.id, text)


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
        limit_msg = f"You've used up your {RATE_LIMIT} favors for today. Come back tomorrow, capisce?"
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
        bot.send_message(message.chat.id, "Somethin' went sideways on my end. Try that again, kid.")
        _log(message, "out", f"[error] {e}")

