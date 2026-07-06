from unittest.mock import patch, MagicMock


def make_message(text="hello", user_id=123, chat_id=456, chat_type="private"):
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = user_id
    msg.chat.id = chat_id
    msg.chat.type = chat_type
    msg.reply_to_message = None
    return msg


HANDLER_PATCHES = {
    "bot.handlers.should_respond": True,
    "bot.handlers.is_rate_limited": False,
    "bot.handlers.BOT_INFO": MagicMock(id=42, username="testbot"),
}


def test_handle_message_calls_ask_ai():
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai", return_value="AI reply") as mock_ask,
        patch("bot.handlers.send_reply") as mock_send,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import handle_message

        msg = make_message(text="hello")
        handle_message(msg)
        mock_ask.assert_called_once_with(123, "hello")
        mock_send.assert_called_once_with(msg, "AI reply")


def test_handle_message_skips_when_not_responding():
    with (
        patch("bot.handlers.should_respond", return_value=False),
        patch("bot.handlers.ask_ai") as mock_ask,
    ):
        from bot.handlers import handle_message

        handle_message(make_message())
        mock_ask.assert_not_called()


def test_handle_message_rate_limited():
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=True),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import handle_message

        handle_message(make_message())
        mock_ask.assert_not_called()
        mock_bot.send_message.assert_called_once()
        assert "daily" in mock_bot.send_message.call_args[0][1]


def test_handle_message_sends_generic_error():
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai", side_effect=Exception("API key invalid")),
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import handle_message

        handle_message(make_message())
        error_msg = mock_bot.send_message.call_args[0][1]
        assert "exception occurred" in error_msg
        assert "API key" not in error_msg


def test_handle_message_none_text_skipped():
    """Stickers/photos/edits arriving with text=None must NOT call ask_ai
    (would burn rate limit and AI quota for no reason)."""
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.send_reply") as mock_send,
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import handle_message

        msg = make_message()
        msg.text = None
        handle_message(msg)
        mock_ask.assert_not_called()
        mock_send.assert_not_called()


def test_handle_message_mention_only_skipped():
    """In a group, '@testbot' alone strips to empty — don't call ask_ai."""
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai") as mock_ask,
        patch("bot.handlers.send_reply"),
        patch("bot.handlers.bot"),
    ):
        from bot.handlers import handle_message

        msg = make_message(text="@testbot")
        handle_message(msg)
        mock_ask.assert_not_called()


# ── /about ────────────────────────────────────────────────────────────────────


def test_cmd_about_with_sqlite():
    """When SQLite is configured, /about should reference SQLite."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", MagicMock()),
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.generate", return_value="Hi! I'm your coach."),
    ):
        from bot.handlers import cmd_about

        cmd_about(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "SQLite" in sent
        assert "stateless" not in sent


def test_cmd_about_includes_commit_sha_when_set():
    """When COMMIT_SHA is populated (worker booted inside a git repo),
    /about exposes a Version line so users can validate which commit is
    live."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", MagicMock()),
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.COMMIT_SHA", "abc1234"),
        patch("bot.handlers.generate", return_value="Hi! I'm your coach."),
    ):
        from bot.handlers import cmd_about

        cmd_about(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "Deployment SHA" in sent
        assert "abc1234" in sent


def test_cmd_about_omits_version_line_when_sha_unknown():
    """If git rev-parse failed at boot, the Version line is dropped
    entirely rather than showing 'unknown' — clearer for the user."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", MagicMock()),
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.COMMIT_SHA", ""),
        patch("bot.handlers.generate", return_value="Hi! I'm your coach."),
    ):
        from bot.handlers import cmd_about

        cmd_about(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "Deployment SHA" not in sent


def test_cmd_about_without_store():
    """When no backend is configured, /about must say stateless. Regression
    guard for the NameError that occurred when `store` was missing from
    bot.handlers' imports."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", None),
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.generate", return_value="Hi! I'm your coach."),
    ):
        from bot.handlers import cmd_about

        cmd_about(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "Stateless" in sent


def test_cmd_about_intro_is_generated_live():
    """The persona intro is produced by a live generate() call (built from
    SYSTEM_PROMPT, not the user's saved history) and rendered into /about."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", MagicMock()),
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch(
            "bot.handlers.generate", return_value="I am a word-loving coach."
        ) as mock_gen,
    ):
        from bot.handlers import cmd_about, _ABOUT_PROMPT

        cmd_about(make_message())

        mock_gen.assert_called_once()
        user_id, messages = mock_gen.call_args[0]
        assert user_id == 123
        assert messages[0]["role"] == "system"
        assert messages[-1] == {"role": "user", "content": _ABOUT_PROMPT}
        sent = mock_bot.send_message.call_args[0][1]
        assert "I am a word-loving coach." in sent


def test_cmd_about_falls_back_when_generate_fails():
    """If the live AI call raises, /about still renders the static fallback
    intro and the technical block — it never breaks as a health probe."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.store", MagicMock()),
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.generate", side_effect=Exception("provider down")),
    ):
        from bot.handlers import cmd_about, _ABOUT_FALLBACK

        cmd_about(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert _ABOUT_FALLBACK in sent
        assert "SQLite" in sent


# ── /help ───────────────────────────────────────────────────────────────────--


def test_cmd_help_blurb_is_generated_live():
    """The /help blurb is produced by a live generate() call built from
    SYSTEM_PROMPT (not the user's history), and the static command list is
    still rendered below it."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch(
            "bot.handlers.generate", return_value="I help you master English words."
        ) as mock_gen,
    ):
        from bot.handlers import cmd_help, _HELP_PROMPT

        cmd_help(make_message())

        mock_gen.assert_called_once()
        user_id, messages = mock_gen.call_args[0]
        assert user_id == 123
        assert messages[0]["role"] == "system"
        assert messages[-1] == {"role": "user", "content": _HELP_PROMPT}
        sent = mock_bot.send_message.call_args[0][1]
        assert "I help you master English words." in sent
        # Command list is code-rendered, not left to the model.
        assert "/reset" in sent
        assert "/about" in sent


def test_cmd_help_falls_back_when_generate_fails():
    """If the live AI call raises, /help still shows the static fallback blurb
    and the command list."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.HF_SPACE_ID", ""),
        patch("bot.handlers.generate", side_effect=Exception("provider down")),
    ):
        from bot.handlers import cmd_help, _HELP_FALLBACK

        cmd_help(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert _HELP_FALLBACK in sent
        assert "/start" in sent


def test_cmd_help_includes_model_command_when_hf_set():
    """The /model line appears only when an HF space is configured."""
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.HF_SPACE_ID", "owner/space"),
        patch("bot.handlers.generate", return_value="blurb"),
    ):
        from bot.handlers import cmd_help

        cmd_help(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "/model" in sent


# ── /sha ─────────────────────────────────────────────────────────────────────


def test_cmd_sha_reports_live_commit_sha():
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.COMMIT_SHA", "abc1234"),
    ):
        from bot.handlers import cmd_sha

        cmd_sha(make_message())
        mock_bot.send_message.assert_called_once_with(
            456, "System Deployment SHA: `abc1234`", parse_mode="Markdown"
        )


def test_cmd_sha_reports_unknown_when_git_sha_unavailable():
    with (
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.COMMIT_SHA", ""),
    ):
        from bot.handlers import cmd_sha

        cmd_sha(make_message())
        mock_bot.send_message.assert_called_once_with(
            456, "System Deployment SHA: `unknown`", parse_mode="Markdown"
        )


# ── /model command ────────────────────────────────────────────────────────────


def _import_cmd_model_with_hf_enabled():
    """Re-import handlers module with HF_SPACE_ID set so cmd_model exists."""
    import importlib
    import bot.config
    import bot.handlers

    original = bot.config.HF_SPACE_ID
    bot.config.HF_SPACE_ID = "fake/space"
    # Also patch the import in handlers module (already imported via `from ... import HF_SPACE_ID`)
    bot.handlers.HF_SPACE_ID = "fake/space"
    importlib.reload(bot.handlers)
    cmd_model = getattr(bot.handlers, "cmd_model", None)
    # Restore
    bot.config.HF_SPACE_ID = original
    bot.handlers.HF_SPACE_ID = original
    return cmd_model


def test_cmd_model_no_args_shows_current():
    cmd_model = _import_cmd_model_with_hf_enabled()
    assert cmd_model is not None
    with (
        patch("bot.handlers.get_provider", return_value="main"),
        patch("bot.handlers.bot") as mock_bot,
    ):
        msg = make_message(text="/model")
        cmd_model(msg)
        sent = mock_bot.send_message.call_args[0][1]
        assert "processing engine" in sent
        assert "main" in sent
        assert "/model main" in sent
        assert "/model hf" in sent


def test_cmd_model_switch_to_hf():
    cmd_model = _import_cmd_model_with_hf_enabled()
    with (
        patch("bot.handlers.set_provider", return_value=True) as mock_set,
        patch("bot.handlers.bot") as mock_bot,
    ):
        msg = make_message(text="/model hf")
        cmd_model(msg)
        mock_set.assert_called_once_with(123, "hf")
        sent = mock_bot.send_message.call_args[0][1]
        assert "hf" in sent
        assert "Armenian" in sent


def test_cmd_model_switch_to_main():
    cmd_model = _import_cmd_model_with_hf_enabled()
    with (
        patch("bot.handlers.set_provider", return_value=True) as mock_set,
        patch("bot.handlers.bot") as mock_bot,
    ):
        msg = make_message(text="/model main")
        cmd_model(msg)
        mock_set.assert_called_once_with(123, "main")
        sent = mock_bot.send_message.call_args[0][1]
        assert "Main" in sent


def test_cmd_model_invalid_choice():
    cmd_model = _import_cmd_model_with_hf_enabled()
    with (
        patch("bot.handlers.set_provider") as mock_set,
        patch("bot.handlers.bot") as mock_bot,
    ):
        msg = make_message(text="/model bogus")
        cmd_model(msg)
        mock_set.assert_not_called()
        assert "Selection error" in mock_bot.send_message.call_args[0][1]


def test_cmd_model_redis_error_reports_failure():
    cmd_model = _import_cmd_model_with_hf_enabled()
    with (
        patch("bot.handlers.set_provider", return_value=False),
        patch("bot.handlers.bot") as mock_bot,
    ):
        msg = make_message(text="/model hf")
        cmd_model(msg)
        assert "Could not modify" in mock_bot.send_message.call_args[0][1]


def test_cmd_model_not_registered_without_hf_space_id():
    """When HF_SPACE_ID is empty, cmd_model should not exist."""
    import importlib
    import bot.config
    import bot.handlers

    bot.config.HF_SPACE_ID = ""
    bot.handlers.HF_SPACE_ID = ""
    # reload() doesn't delete existing attributes, so clear it first
    if hasattr(bot.handlers, "cmd_model"):
        delattr(bot.handlers, "cmd_model")
    importlib.reload(bot.handlers)
    assert not hasattr(bot.handlers, "cmd_model")


# ── Knowledge base: upload / list / download / admin ──────────────────────────


def make_doc_message(file_name="RA Tax Code.pdf", file_size=1000, user_id=123, chat_id=456):
    msg = MagicMock()
    msg.from_user.id = user_id
    msg.chat.id = chat_id
    msg.document.file_name = file_name
    msg.document.file_size = file_size
    msg.document.file_id = "FILEID"
    msg.document.file_unique_id = "UNIQ"
    return msg


class _NullTyping:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


def test_handle_document_rejected_for_non_admin():
    with (
        patch("bot.handlers.is_admin", return_value=False),
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import handle_document

        handle_document(make_doc_message())
        mock_kb.ingest.assert_not_called()
        assert "administrator" in mock_bot.send_message.call_args[0][1].lower()


def test_handle_document_ingests_for_admin():
    with (
        patch("bot.handlers.is_admin", return_value=True),
        patch("bot.handlers.keep_typing", return_value=_NullTyping()),
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
    ):
        mock_kb.available.return_value = True
        mock_bot.get_file.return_value = MagicMock(file_path="path/f.pdf")
        mock_bot.download_file.return_value = b"%PDF-data"
        mock_kb.ingest.return_value = {
            "ok": True,
            "title": "RA Tax Code.pdf",
            "chunk_count": 12,
            "upload_date": "12.05.24",
        }
        from bot.handlers import handle_document

        handle_document(make_doc_message())
        mock_kb.ingest.assert_called_once()
        assert b"%PDF-data" == mock_kb.ingest.call_args[0][0]
        assert "Indexed" in mock_bot.send_message.call_args[0][1]


def test_handle_document_rejects_non_pdf():
    with (
        patch("bot.handlers.is_admin", return_value=True),
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
    ):
        mock_kb.available.return_value = True
        from bot.handlers import handle_document

        handle_document(make_doc_message(file_name="notes.txt"))
        mock_kb.ingest.assert_not_called()
        assert "PDF" in mock_bot.send_message.call_args[0][1]


def test_handle_document_rejects_oversize():
    with (
        patch("bot.handlers.is_admin", return_value=True),
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
    ):
        mock_kb.available.return_value = True
        from bot.handlers import handle_document

        handle_document(make_doc_message(file_size=25 * 1024 * 1024))
        mock_kb.ingest.assert_not_called()
        assert "20 MB" in mock_bot.send_message.call_args[0][1]


def test_cmd_documents_empty():
    with (
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
    ):
        mock_kb.list_documents.return_value = []
        from bot.handlers import cmd_documents

        cmd_documents(make_message())
        assert "No documents" in mock_bot.send_message.call_args[0][1]


def test_cmd_documents_lists_with_buttons():
    with (
        patch("bot.handlers.is_admin", return_value=False),
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
        patch("bot.handlers.types") as mock_types,
    ):
        mock_kb.list_documents.return_value = [
            {"doc_id": 1, "title": "RA Tax Code", "upload_date": "12.05.24", "file_id": "F1", "chunk_count": 9},
        ]
        markup = MagicMock()
        mock_types.InlineKeyboardMarkup.return_value = markup
        from bot.handlers import cmd_documents

        cmd_documents(make_message())
        sent = mock_bot.send_message.call_args[0][1]
        assert "RA Tax Code" in sent and "12.05.24" in sent
        markup.add.assert_called_once()  # one download button


def test_cb_download_document_sends_file():
    with (
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
    ):
        mock_kb.get_document.return_value = {
            "doc_id": 1, "title": "RA Tax Code", "upload_date": "12.05.24", "file_id": "F1", "chunk_count": 9,
        }
        call = MagicMock()
        call.data = "kbdl:1"
        call.message.chat.id = 456
        from bot.handlers import cb_download_document

        cb_download_document(call)
        mock_bot.send_document.assert_called_once()
        assert mock_bot.send_document.call_args[0][1] == "F1"


def test_cb_download_document_missing():
    with (
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
    ):
        mock_kb.get_document.return_value = None
        call = MagicMock()
        call.data = "kbdl:99"
        from bot.handlers import cb_download_document

        cb_download_document(call)
        mock_bot.send_document.assert_not_called()
        mock_bot.answer_callback_query.assert_called_once()


def test_cmd_myid_reports_numeric_id():
    with patch("bot.handlers.bot") as mock_bot:
        from bot.handlers import cmd_myid

        cmd_myid(make_message(user_id=777))
        assert "777" in mock_bot.send_message.call_args[0][1]


def test_cmd_deldoc_admin_deletes():
    with (
        patch("bot.handlers.is_admin", return_value=True),
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
    ):
        mock_kb.get_document.return_value = {"doc_id": 3, "title": "Old Code", "upload_date": "01.01.24", "file_id": "F", "chunk_count": 1}
        mock_kb.delete_document.return_value = True
        from bot.handlers import cmd_deldoc

        cmd_deldoc(make_message(text="/deldoc 3"))
        mock_kb.delete_document.assert_called_once_with(3)
        assert "Removed" in mock_bot.send_message.call_args[0][1]


def test_cmd_deldoc_rejected_for_non_admin():
    with (
        patch("bot.handlers.is_admin", return_value=False),
        patch("bot.handlers.knowledge") as mock_kb,
        patch("bot.handlers.bot") as mock_bot,
    ):
        from bot.handlers import cmd_deldoc

        cmd_deldoc(make_message(text="/deldoc 3"))
        mock_kb.delete_document.assert_not_called()


def test_handle_message_uses_keep_typing():
    """handle_message should wrap ask_ai in the keep_typing context."""
    with (
        patch("bot.handlers.should_respond", return_value=True),
        patch("bot.handlers.is_rate_limited", return_value=False),
        patch("bot.handlers.BOT_INFO", MagicMock(username="testbot")),
        patch("bot.handlers.ask_ai", return_value="reply"),
        patch("bot.handlers.send_reply"),
        patch("bot.handlers.keep_typing") as mock_keep,
        patch("bot.handlers.bot"),
    ):
        mock_keep.return_value.__enter__ = MagicMock(return_value=None)
        mock_keep.return_value.__exit__ = MagicMock(return_value=None)
        from bot.handlers import handle_message

        msg = make_message()
        handle_message(msg)
        mock_keep.assert_called_once_with(456)
