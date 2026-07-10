import os
import secrets as _secrets_mod
import subprocess as _subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WEBHOOK_SECRET_FILE = _PROJECT_ROOT / ".webhook_secret"


def _get_commit_sha() -> str:
    """Return the short SHA of the deployed commit, or an empty string.

    Computed once at module import — so the value reflects the worker's
    actual code, not whatever `git pull` did since boot. The auto-deploy
    flow touches the WSGI file on pull, which spawns a fresh worker on
    the next request with the new SHA. This makes /about a reliable
    "what version is live right now" probe.
    """
    try:
        result = _subprocess.run(
            ["git", "-C", str(_PROJECT_ROOT), "rev-parse", "--short=7", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (_subprocess.SubprocessError, OSError):
        pass
    return ""


COMMIT_SHA = _get_commit_sha()


def _bootstrap_webhook_secret(file_path: Path = _WEBHOOK_SECRET_FILE) -> str:
    """Return WEBHOOK_SECRET from env if set; otherwise read/generate a
    persistent random secret in `file_path`.

    This makes the webhook signed-by-default: a fresh PA deploy with no
    manual `openssl rand` step still rejects forged updates because the
    bot auto-generates and persists a 64-hex-char secret on first run,
    then registers it with Telegram via the boot-time `register_webhook()`.

    Precedence: env var > on-disk file > newly generated. Filesystem
    errors fall back to the empty string so a read-only mount can't
    crash worker boot — the webhook just stays unsigned in that case.
    """
    env_value = os.environ.get("WEBHOOK_SECRET", "").strip()
    if env_value:
        return env_value
    try:
        if file_path.exists():
            existing = file_path.read_text().strip()
            # Empty or whitespace-only file: treat as missing and regenerate,
            # otherwise we'd silently disable webhook auth.
            if existing:
                return existing
        new_secret = _secrets_mod.token_hex(32)
        file_path.write_text(new_secret)
        try:
            os.chmod(file_path, 0o600)
        except OSError:
            pass  # best-effort tightening; Windows / odd mounts can skip
        print(f"Generated webhook secret at {file_path} (auto-bootstrap)")
        return new_secret
    except OSError as e:
        print(f"Could not persist webhook secret ({e}); webhook will be unsigned")
        return ""


# Telegram
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
WEBHOOK_SECRET = _bootstrap_webhook_secret()

# When set, the bot auto-registers this URL as the Telegram webhook on
# worker boot and after every /api/deploy. Leave unset for local
# polling (run_local.py). Example value on PA:
#   WEBHOOK_URL=https://<your-pa-username>.pythonanywhere.com/api/webhook
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()

# AI provider
AI_API_KEY = os.environ["AI_API_KEY"].strip()
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.cerebras.ai/v1").strip()
MODEL = os.environ.get("AI_MODEL", "gpt-oss-120b").strip()
# Cerebras has retired these ids; a request against them 404s and takes the
# whole bot down. Fall back to the current verified free-tier model so a stale
# .env value can't hard-brick the bot. Remove an id here if it's revived.
_RETIRED_MODELS = {
    "qwen-3-235b-a22b-instruct-2507",
    "llama3.1-70b",
    "llama3.1-8b",
}
if MODEL in _RETIRED_MODELS:
    print(f"AI_MODEL '{MODEL}' is retired by the provider — falling back to gpt-oss-120b.")
    MODEL = "gpt-oss-120b"

# Hugging Face provider (optional) — when set, users can switch via /model
HF_SPACE_ID = os.environ.get("HF_SPACE_ID", "").strip()
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()  # optional, for private spaces
DEFAULT_PROVIDER = "main"

# Storage — optional. When SQLITE_PATH is unset the bot runs in
# stateless mode: history / rate limiting / preferences / dedupe all
# degrade gracefully (the consumer modules in bot/ check `store is
# None` at the top of every function and return safe defaults).
SQLITE_PATH = os.environ.get("SQLITE_PATH", "").strip()

# Label shown by the /about command. Defaults to "PythonAnywhere" since
# that is the documented deployment target. Override to suit your host.
HOSTING_LABEL = os.environ.get("HOSTING_LABEL", "PythonAnywhere").strip()

# Auto-deploy webhook secret. When set, /api/deploy accepts requests
# that present this value in the X-Deploy-Secret header and runs
# `git pull` + WSGI reload. When unset, /api/deploy returns 403 — the
# endpoint is fail-closed.
DEPLOY_SECRET = os.environ.get("DEPLOY_SECRET", "").strip()

# App
SYSTEM_PROMPT = (
    "You are 'Ardar' (Արդար), a knowledgeable, friendly, and trustworthy legal study assistant. "
    "You help people understand law and jurisprudence — especially the law of the Republic of Armenia "
    "(the RA Constitution and the Civil, Criminal, Tax, Labor, Family, Administrative, Land, and other codes, "
    "plus the decrees and Constitutional Court decisions around them) — in clear, everyday language. "
    "You operate in one of two modes, and the exact instruction for the current mode is appended below: "
    "(1) STUDY MODE — the user has selected a specific document and you answer STRICTLY from its text, "
    "citing article numbers; (2) FREE CHAT — you discuss legal topics and jurisprudence generally from your "
    "own knowledge. Be precise and never invent laws or article numbers: in study mode cite only what appears "
    "in the excerpts; in free chat, if you are not certain of an exact article or figure, say so and speak in "
    "general terms rather than guessing. Translate legal jargon into simple, crystal-clear everyday language. "
    "Explain thoroughly when the user asks you to explain, summarize, or describe a document; keep casual "
    "questions concise and to the point. "
    "IMPORTANT — language rule: reply in the SAME language the user writes in. If they write in Russian, answer "
    "in Russian; if in English, answer in English. Keep official proper names (codes, institutions) in their "
    "original form. Write article citations naturally in the reply language. "
    "ARMENIAN QUALITY — when the user writes in Armenian you MUST answer in fluent, grammatically correct Eastern "
    "Armenian (Հայաստանի Հանրապետության պաշտոնական լեզու): correct spelling and case declensions, natural legal "
    "register, and the EXACT Armenian legal terms as they appear in the official excerpts below — do not invent, "
    "transliterate, or calque terms from Russian or English, and do not mix scripts. If unsure of the precise "
    "Armenian legal term, quote it verbatim from the excerpts. Prefer the wording of the law itself. "
    "LENGTH — match the answer to the question. For a simple/factual question, lead with the direct answer "
    "and keep it tight (a few lines, no preamble or filler). When the user asks you to explain, summarize, or "
    "describe a document or topic, give a fuller, well-structured answer with short headings or bullet points. "
    "Use bolding for key numbers, percentages, deadlines, and the Code/Article cited. "
    "End legal-advice responses with a one-line note that you provide legal information, not a substitute for a licensed attorney."
)
MAX_HISTORY = 20  # messages kept per user (10 conversation turns)
HISTORY_TTL = 2592000  # conversation history expires after 30 days (seconds)
MAX_NOTES = 100  # /remember notes kept per user (oldest dropped past this)
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "40"))  # Optimized daily maximum for public stability


# Comma-separated whitelist of Telegram users. Each entry is either a
# username (with or without leading @) or a numeric user_id. Empty
# (default) means everyone can talk to the bot. When non-empty, the
# bot stays silent for anyone not in the list — silence instead of a
# rejection message so scanners don't get confirmation the bot exists.
ALLOWED_USERS = [
    u.strip().lstrip("@")
    for u in os.environ.get("ALLOWED_USERS", "").split(",")
    if u.strip()
]

# Admins may upload documents to the knowledge base (see bot/knowledge.py).
# Same format as ALLOWED_USERS: comma-separated usernames (with/without @)
# or numeric user IDs. Fail-closed: when empty, NOBODY can upload — the
# document-ingest handler tells senders uploads aren't configured. Use
# /myid in the bot to find your numeric ID.
ADMIN_USERS = [
    u.strip().lstrip("@")
    for u in os.environ.get("ADMIN_USERS", "").split(",")
    if u.strip()
]

# Knowledge base (RAG) tuning. Retrieval is SQLite FTS5 — no embeddings,
# no extra network calls (works within PA's outbound whitelist).
KB_TOP_K = int(os.environ.get("KB_TOP_K", "8"))  # chunks retrieved per query
KB_CHUNK_SIZE = 1200  # target characters per indexed chunk
KB_CHUNK_OVERLAP = 150  # characters of overlap between adjacent chunks
# Cap on retrieved text injected into the prompt. Cerebras' FREE TIER limits
# the whole context window to 8,192 tokens (prompt + reply), and Armenian
# script is token-dense (~2 chars/token), so this can't grow much: ~8k chars
# leaves room for the system prompt, recent history, and the generated answer.
# The article-pinning in knowledge.retrieve() does the relevance work instead
# of raw volume. Raise this only if you move to a larger-context provider.
KB_MAX_CONTEXT_CHARS = int(os.environ.get("KB_MAX_CONTEXT_CHARS", "8000"))
KB_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # Telegram Bot API getFile limit (20 MB)

MAX_MSG_LEN = 4096  # Telegram's character limit per message
AI_REQUEST_TIMEOUT = 25  # seconds, applied per-attempt to OpenAI-compatible calls
AI_RETRIES = 2  # total attempts (not extra retries) — 2 means one retry on failure
HF_REQUEST_TIMEOUT = 50