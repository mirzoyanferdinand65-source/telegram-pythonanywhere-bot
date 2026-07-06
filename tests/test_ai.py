from unittest.mock import patch


def test_ask_ai_returns_reply():
    with (
        patch("bot.ai.generate", return_value="Hello there!"),
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history"),
    ):
        from bot.ai import ask_ai

        reply = ask_ai(123, "hi")
        assert reply == "Hello there!"


def test_ask_ai_saves_history():
    with (
        patch("bot.ai.generate", return_value="reply"),
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history") as mock_save,
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
    ):
        from bot.ai import ask_ai

        ask_ai(456, "hello")
        assert mock_gen.call_args[0][0] == 456


def test_ask_ai_injects_context_and_appends_citation():
    """When the KB returns hits, the excerpts are injected into the system
    prompt and a 'Based on' footer is appended to the reply."""
    with (
        patch("bot.ai.generate", return_value="Per Article 258, the deadline is April 20.") as mock_gen,
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history"),
        patch(
            "bot.ai.knowledge.retrieve",
            return_value=[{"doc_id": 1, "title": "RA Tax Code", "upload_date": "12.05.24", "body": "Article 258..."}],
        ),
    ):
        from bot.ai import ask_ai

        reply = ask_ai(1, "tax deadline?")
        # Footer names the source document and its upload date.
        assert "📄" in reply and "RA Tax Code" in reply and "12.05.24" in reply
        # The retrieved excerpt was injected into the system prompt.
        system_msg = mock_gen.call_args[0][1][0]
        assert system_msg["role"] == "system"
        assert "OFFICIAL EXCERPTS" in system_msg["content"]
        assert "Article 258" in system_msg["content"]


def test_ask_ai_notes_when_documents_exist_but_none_match():
    with (
        patch("bot.ai.generate", return_value="General answer."),
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history"),
        patch("bot.ai.knowledge.retrieve", return_value=[]),
        patch("bot.ai.knowledge.has_documents", return_value=True),
    ):
        from bot.ai import ask_ai

        reply = ask_ai(1, "unrelated question")
        assert "Not based on a specific uploaded document" in reply


def test_ask_ai_no_footer_when_kb_empty():
    with (
        patch("bot.ai.generate", return_value="Plain reply."),
        patch("bot.ai.get_history", return_value=[]),
        patch("bot.ai.save_history"),
        patch("bot.ai.knowledge.retrieve", return_value=[]),
        patch("bot.ai.knowledge.has_documents", return_value=False),
    ):
        from bot.ai import ask_ai

        assert ask_ai(1, "hi") == "Plain reply."
