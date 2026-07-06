from bot import knowledge
from bot.config import SYSTEM_PROMPT
from bot.history import get_history, save_history
from bot.providers import generate

# Prepended to the retrieved excerpts so the model grounds its answer in the
# uploaded legal text (real article numbers) instead of its own memory.
_RAG_INSTRUCTION = (
    "\n\nAnswer the user's question using the official legal excerpts below. "
    "Base your answer strictly on them and cite the exact article numbers you "
    "find in them. If the excerpts do not contain the answer, say so honestly "
    "and suggest the user consult a licensed lawyer or the relevant authority.\n\n"
    "=== OFFICIAL EXCERPTS ===\n{context}\n=== END EXCERPTS ==="
)


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

    # Retrieve relevant legal text (no-op / empty when the KB is disabled).
    results = knowledge.retrieve(user_message)
    context, sources = knowledge.build_context(results) if results else ("", [])

    system_prompt = SYSTEM_PROMPT
    if context:
        system_prompt += _RAG_INSTRUCTION.format(context=context)

    messages = [{"role": "system", "content": system_prompt}]
    messages += history

    reply = generate(user_id, messages)

    history.append({"role": "assistant", "content": reply})
    save_history(user_id, history)

    if sources:
        return reply + _citation_footer(sources)
    # Emphasize provenance after every answer: when documents exist but none
    # matched, say so plainly. When no documents are loaded at all (or the KB
    # is disabled), stay quiet so the bot reads naturally.
    if knowledge.has_documents():
        return reply + "\n\n_ℹ️ Not based on a specific uploaded document — general legal information only._"
    return reply
