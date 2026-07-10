from unittest.mock import patch


def test_ask_ai_returns_reply():
    with (
        patch("bot.ai.generate", return_value="Hello there!"),
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history"),
        patch("bot.ai.get_active_doc", return_value=None),
    ):
        from bot.ai import ask_ai

        reply = ask_ai(123, "hi")
        assert reply == "Hello there!"


def test_ask_ai_saves_history():
    with (
        patch("bot.ai.generate", return_value="reply"),
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history") as mock_save,
        patch("bot.ai.get_active_doc", return_value=None),
    ):
        from bot.ai import ask_ai

        ask_ai(123, "hi")
        mock_save.assert_called_once()
        saved_history = mock_save.call_args[0][1]
        assert saved_history[0] == {"role": "user", "content": "hi"}
        assert saved_history[1]["role"] == "assistant"


def test_ask_ai_passes_user_id_to_generate():
    with (
        patch("bot.ai.generate", return_value="hi") as mock_gen,
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history"),
        patch("bot.ai.get_active_doc", return_value=None),
    ):
        from bot.ai import ask_ai

        ask_ai(456, "hello")
        assert mock_gen.call_args[0][0] == 456


def test_free_chat_is_not_grounded_and_never_retrieves():
    """With no document selected the bot free-chats: no document retrieval,
    no citation footer."""
    with (
        patch("bot.ai.generate", return_value="Generally, contracts require consent.") as mock_gen,
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history"),
        patch("bot.ai.get_active_doc", return_value=None),
        patch("bot.ai.knowledge.retrieve") as mock_retrieve,
    ):
        from bot.ai import ask_ai

        reply = ask_ai(1, "how do contracts work?")
        assert reply == "Generally, contracts require consent."
        mock_retrieve.assert_not_called()  # free chat must not retrieve
        system_msg = mock_gen.call_args[0][1][0]
        assert "FREE CHAT" not in system_msg["content"] or "no specific" in system_msg["content"]
        assert "no specific" in system_msg["content"]  # free-chat instruction present


def test_study_mode_scopes_to_selected_document_and_footers():
    """In study mode retrieval is scoped to the active doc, excerpts are
    injected, and the reply is tagged with the studied document."""
    doc = {"doc_id": 7, "title": "RA Criminal Code", "upload_date": "01.01.25", "file_id": "F"}
    with (
        patch("bot.ai.generate", return_value="Article 258 covers fraud.") as mock_gen,
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history"),
        patch("bot.ai.get_active_doc", return_value=7),
        patch("bot.ai.knowledge.get_document", return_value=doc),
        patch(
            "bot.ai.knowledge.retrieve",
            return_value=[{"doc_id": 7, "title": "RA Criminal Code", "upload_date": "01.01.25", "body": "Article 258 fraud."}],
        ) as mock_retrieve,
    ):
        from bot.ai import ask_ai

        reply = ask_ai(1, "what does article 258 say?")
        # Retrieval was scoped to the selected document.
        assert mock_retrieve.call_args.kwargs.get("doc_id") == 7
        # Footer names the document being studied.
        assert "📖" in reply and "RA Criminal Code" in reply and "/done" in reply
        # Excerpt injected under the study instruction.
        system_msg = mock_gen.call_args[0][1][0]
        assert "DOCUMENT EXCERPTS" in system_msg["content"]
        assert "Article 258 fraud." in system_msg["content"]


def test_study_mode_overview_uses_document_opening():
    """A 'main idea' question pulls the document's opening chunks rather than
    keyword hits."""
    doc = {"doc_id": 3, "title": "Constitution", "upload_date": "02.02.25"}
    with (
        patch("bot.ai.generate", return_value="This document establishes..."),
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history"),
        patch("bot.ai.get_active_doc", return_value=3),
        patch("bot.ai.knowledge.get_document", return_value=doc),
        patch("bot.ai.knowledge.retrieve") as mock_retrieve,
        patch(
            "bot.ai.knowledge.overview_chunks",
            return_value=[{"doc_id": 3, "title": "Constitution", "upload_date": "02.02.25", "body": "Preamble..."}],
        ) as mock_overview,
    ):
        from bot.ai import ask_ai

        ask_ai(1, "what is the main idea of this document?")
        mock_overview.assert_called_once()
        mock_retrieve.assert_not_called()  # overview path skips keyword retrieval
