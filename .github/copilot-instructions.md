Purpose
This file helps AI coding assistants become immediately productive in this repository.

Guiding principles
- Be conservative: change only the smallest set of files needed for a task.
- Preserve the teaching-oriented persona: handlers use a stylized voice in [bot/handlers.py](bot/handlers.py).
- Prefer surgical fixes in `bot/` modules; tests live in [tests/](tests) and must pass.

Big picture (fast scan)
- Telegram entrypoints: [api/index.py](api/index.py) and [pythonanywhere_wsgi.py](pythonanywhere_wsgi.py).
- Bot runtime: [bot/handlers.py](bot/handlers.py) routes Telegram updates to business logic.
- AI orchestration: [bot/ai.py](bot/ai.py) + [bot/providers.py](bot/providers.py) (dispatch to `main` OpenAI-compatible endpoints or optional `hf` Gradio spaces).
- Storage and state: [bot/store.py](bot/store.py) (SqliteStore) enabled when `SQLITE_PATH` is set; otherwise `store is None` → stateless mode.

Key developer workflows
- Run locally (polling): `make run` runs `run_local.py` which uses polling and `threaded=False`.
- Run tests: `pytest -q` (CI uses the same). Tests mock external APIs in [tests/conftest.py](tests/conftest.py).
- Deploy: PA-first-time via `scripts/pa_deploy.sh` or CI via `.github/workflows/deploy.yml`. See [CLAUDE.md](CLAUDE.md) for full deploy notes.

Project-specific conventions
- `threaded=False` on `telebot.TeleBot` is required (see CLAUDE.md) — do not change to threaded handlers.
- Feature toggles via env: `HF_SPACE_ID` enables `/model`; `SQLITE_PATH` enables persistent memory and rate limiting.
- One-shot vs chat: `generate()` is used for stateless one-shots (joke/quote); `ask_ai()` loads/saves history and should be used for conversation flows.
- Typing indicator: use `keep_typing()` from [bot/helpers.py](bot/helpers.py) when running slow AI calls so Telegram shows typing.
- Long replies: use `send_reply()` from [bot/helpers.py](bot/helpers.py) — it splits messages to avoid Telegram's 4096 char limit.

Integration points & external dependencies
- Telegram Bot API via `pyTelegramBotAPI` instantiated in [bot/clients.py](bot/clients.py).
- AI provider(s): OpenAI-compatible endpoints (Cerebras defaults) via env vars in [bot/config.py](bot/config.py); optional HF Gradio space controlled by `HF_SPACE_ID`.
- Hosting: PythonAnywhere WSGI in [pythonanywhere_wsgi.py](pythonanywhere_wsgi.py) and webhook endpoints in [api/index.py](api/index.py).

Testing & safety notes for AI agents
- Tests assume environment overrides in [tests/conftest.py](tests/conftest.py). Use those fixtures for mocking external clients.
- Do not modify `conftest.py` to make tests pass; instead make code changes that satisfy the failing assertion.
- Preserve existing error-handling patterns: functions degrade to safe defaults when `store is None`.

Where to add code
- New Telegram commands: add a decorated handler in [bot/handlers.py](bot/handlers.py) using `@bot.message_handler` with `func=is_allowed`.
- AI-related helpers: add to [bot/ai.py](bot/ai.py) or [bot/providers.py](bot/providers.py); update tests in `tests/test_ai.py` and `tests/test_providers.py`.
- Storage schema: extend [bot/store.py](bot/store.py) carefully — tests in [tests/test_store.py](tests/test_store.py) exercise TTL and persistence.

Examples
- To add a new command `/foo`: add a `cmd_foo` function to [bot/handlers.py](bot/handlers.py) and mirror expected behaviour in tests under [tests/test_handlers.py](tests/test_handlers.py).
- To call the main provider with retries, follow the pattern in [bot/providers.py](bot/providers.py) `_call_main()`.

If you get stuck
- Read [CLAUDE.md](CLAUDE.md) (agent-oriented guide) and [README.md](README.md) (developer/student guide).
- Run the test suite locally before proposing changes to CI.

Questions for the repo owner
- Preferred CI branch (default `main` assumed)?
- Any private HF space credentials or domain whitelists required for additional integrations?

If this file should be merged differently, tell me what to preserve from any existing `.github/copilot-instructions.md` and I'll adapt.
