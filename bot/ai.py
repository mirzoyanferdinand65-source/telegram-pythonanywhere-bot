from bot import knowledge
from bot.active_doc import get_active_doc
from bot.config import SYSTEM_PROMPT
from bot.history import get_history, save_history
from bot.providers import generate

# ── Study mode ────────────────────────────────────────────────────────────────
# The user has selected one document (via /documents → "Study this"). Answers
# are grounded strictly in that document's text.
_STUDY_INSTRUCTION = (
    '\n\nThe user is studying the document titled "{title}". Answer using ONLY '
    "the excerpts from this document below. Explain clearly and thoroughly, cite "
    "the exact article numbers you find, and quote the wording of the law itself. "
    "If the excerpts do not contain the answer, say so honestly and suggest the "
    "user ask a more specific question or consult a licensed lawyer. Reply in the "
    "user's language.\n\n"
    "=== DOCUMENT EXCERPTS ({title}) ===\n{context}\n=== END EXCERPTS ==="
)

# ── Free-chat mode ──────────────────────────────────────────────────────────
# No document selected. General jurisprudence conversation from the model's own
# knowledge — deliberately NOT grounded in a specific document, so it must not
# fabricate exact article numbers.
_FREECHAT_INSTRUCTION = (
    "\n\nThe user is chatting generally about law and jurisprudence — no specific "
    "document is selected. Give helpful, accurate general legal information in plain "
    "language. Do NOT fabricate exact article numbers or figures; when precision "
    "matters, tell the user they can open /documents and pick a specific code to get "
    "exact, cited answers."
)

# Broad "what is this about" triggers across the three languages. When a study
# question matches, we feed the document's opening (its scope / general
# provisions) instead of keyword hits.
_OVERVIEW_HINTS = (
    # English
    "main idea", "summary", "summarize", "summarise", "overview", "what is this",
    "what's this", "what is it about", "about this", "explain the document",
    "explain this document", "key points", "purpose", "in general",
    # Russian
    "главн", "суть", "о чём", "о чем", "кратко", "обзор", "содержан", "смысл", "общем",
    # Armenian
    "գլխավոր", "էություն", "ամփոփ", "ինչի մասին", "նպատակ", "բովանդակ", "համառոտ",
)


def _wants_overview(text: str) -> bool:
    t = (text or "").lower()
    return any(h in t for h in _OVERVIEW_HINTS)


def _citation_footer(sources: list) -> str:
    """Build the "Based on..." footer from a list of (title, upload_date)."""
    if not sources:
        return ""
    if len(sources) == 1:
        title, date = sources[0]
        return f"\n\n📄 _Based on: {title} (uploaded {date})_"
    lines = "\n".join(f"• {title} (uploaded {date})" for title, date in sources)
    return "\n\n📄 _Based on:_\n" + lines


def ask_ai(user_id: int, user_message: str) -> str:
    history = get_history(user_id)
    history.append({"role": "user", "content": user_message})

    system_prompt = SYSTEM_PROMPT
    footer = ""

    # Study mode iff the user has selected a document that still exists.
    active_id = get_active_doc(user_id)
    doc = knowledge.get_document(active_id) if active_id else None

    if doc:
        doc_id = doc["doc_id"]
        # Overview questions get the document's opening sections; specific
        # questions get scoped keyword retrieval, falling back to the opening
        # when nothing matches so the model still has something to work from.
        if _wants_overview(user_message):
            results = knowledge.overview_chunks(doc_id)
        else:
            results = knowledge.retrieve(user_message, doc_id=doc_id)
            if not results:
                results = knowledge.overview_chunks(doc_id, n=4)
        context, sources = knowledge.build_context(results) if results else ("", [])
        if context:
            system_prompt += _STUDY_INSTRUCTION.format(title=doc["title"], context=context)
        footer = f"\n\n📖 _Studying: {doc['title']}_  ·  _/done to exit_"
    else:
        system_prompt += _FREECHAT_INSTRUCTION

    messages = [{"role": "system", "content": system_prompt}]
    messages += history

    reply = generate(user_id, messages)

    history.append({"role": "assistant", "content": reply})
    save_history(user_id, history)

    return reply + footer
