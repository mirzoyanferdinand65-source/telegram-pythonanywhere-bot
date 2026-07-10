"""Tests for bot/knowledge.py — the SQLite FTS5 document knowledge base.

The module reads SQLITE_PATH at import and initializes global state, so the
`kb` fixture points it at a throwaway DB and reloads it, restoring the
default (disabled) state on teardown.
"""

import importlib
import os

import pytest


@pytest.fixture
def kb(tmp_path):
    """A freshly-initialized, ENABLED knowledge base backed by a temp DB."""
    old = os.environ.get("SQLITE_PATH")
    os.environ["SQLITE_PATH"] = str(tmp_path / "kb.db")
    import bot.config as cfg
    import bot.knowledge as k

    importlib.reload(cfg)
    importlib.reload(k)
    assert k.available() is True
    yield k
    # Restore the default disabled state so later test modules are unaffected.
    if old is None:
        os.environ.pop("SQLITE_PATH", None)
    else:
        os.environ["SQLITE_PATH"] = old
    importlib.reload(cfg)
    importlib.reload(k)


# ── Pure helpers (no DB needed) ───────────────────────────────────────────────


def test_chunk_text_splits_and_caps_size():
    from bot import knowledge

    chunks = knowledge.chunk_text("word " * 1000, size=1000, overlap=100)
    assert len(chunks) >= 3
    assert all(len(c) <= 1000 for c in chunks)


def test_chunk_text_empty_and_whitespace():
    from bot import knowledge

    assert knowledge.chunk_text("") == []
    assert knowledge.chunk_text("   \n\n\t  ") == []


def test_fts_query_quotes_ors_and_keeps_digits():
    from bot import knowledge

    q = knowledge._fts_query("tax deadline 258")
    assert '"tax"' in q and '"deadline"' in q and '"258"' in q
    assert " OR " in q


def test_fts_query_neutralizes_operator_chars():
    from bot import knowledge

    # A user typing FTS5 syntax must not break the MATCH query.
    q = knowledge._fts_query('foo* (bar) baz:qux')
    assert "*" not in q and "(" not in q and ":" not in q
    assert q.startswith('"')


def test_fts_query_empty_for_no_terms():
    from bot import knowledge

    assert knowledge._fts_query("") == ""
    assert knowledge._fts_query("!!! ?? .") == ""


# ── DB-backed behavior ────────────────────────────────────────────────────────


def test_ingest_and_retrieve_grounds_on_text(kb, monkeypatch):
    monkeypatch.setattr(
        kb,
        "extract_pdf_text",
        lambda b: "Article 258. The tax return deadline is April 20 for sole proprietors.",
    )
    res = kb.ingest(b"%PDF-fake", title="RA Tax Code", file_id="F1", upload_date="12.05.24")
    assert res["ok"] is True
    assert res["chunk_count"] >= 1

    hits = kb.retrieve("when is the tax deadline")
    assert hits and hits[0]["title"] == "RA Tax Code"

    context, sources = kb.build_context(hits)
    assert sources == [("RA Tax Code", "12.05.24")]
    assert "Article 258" in context


def test_article_numbers_parses_three_languages():
    from bot import knowledge

    assert knowledge._article_numbers("what does Article 258 say") == ["258"]
    assert knowledge._article_numbers("Հոդված 104-ի մասին") == ["104"]
    assert knowledge._article_numbers("расскажи про статью 42") == ["42"]
    # De-duplicates and preserves order.
    assert knowledge._article_numbers("art. 5 and Article 5") == ["5"]
    assert knowledge._article_numbers("no numbers here") == []


def test_retrieve_pins_cited_article_first(kb, monkeypatch):
    # Two articles: the keyword "penalty" appears in BOTH, so plain BM25 could
    # rank either first. Citing Article 300 must pin its chunk to the top.
    text = (
        "Article 100. General penalty provisions apply to minor offences.\n\n"
        + ("filler sentence about penalty and procedure. " * 40)
        + "\n\nArticle 300. The penalty for aggravated fraud is up to ten years."
    )
    monkeypatch.setattr(kb, "extract_pdf_text", lambda b: text)
    kb.ingest(b"x", title="Criminal Code", upload_date="01.01.25")

    hits = kb.retrieve("what is the penalty under Article 300")
    assert hits
    assert "Article 300" in hits[0]["body"]


def test_retrieve_scoped_to_single_document(kb, monkeypatch):
    # Same keyword ("penalty") in two different documents. Scoping to one
    # doc_id must never return chunks from the other.
    monkeypatch.setattr(kb, "extract_pdf_text", lambda b: "Article 1. Penalty for theft under the criminal code.")
    crim = kb.ingest(b"x", title="Criminal Code")["doc_id"]
    monkeypatch.setattr(kb, "extract_pdf_text", lambda b: "Article 1. Penalty clauses of the civil code.")
    civ = kb.ingest(b"x", title="Civil Code")["doc_id"]

    hits = kb.retrieve("penalty", doc_id=crim)
    assert hits and all(h["doc_id"] == crim for h in hits)
    assert all(h["title"] == "Criminal Code" for h in hits)

    civ_hits = kb.retrieve("penalty", doc_id=civ)
    assert civ_hits and all(h["doc_id"] == civ for h in civ_hits)


def test_overview_chunks_returns_document_opening_in_order(kb, monkeypatch):
    body = "FIRST section preamble. " + ("middle body text. " * 200) + "LAST closing section."
    monkeypatch.setattr(kb, "extract_pdf_text", lambda b: body)
    doc_id = kb.ingest(b"x", title="Constitution")["doc_id"]

    overview = kb.overview_chunks(doc_id, n=2)
    assert overview
    assert len(overview) <= 2
    assert "FIRST" in overview[0]["body"]  # opens at the start of the document
    assert all(o["doc_id"] == doc_id for o in overview)


def test_retrieve_matches_cyrillic(kb, monkeypatch):
    monkeypatch.setattr(kb, "extract_pdf_text", lambda b: "Статья 42. Налог на прибыль 18 процентов.")
    kb.ingest(b"x", title="Civil Code")
    assert kb.retrieve("налог прибыль")


def test_ingest_rejects_scanned_pdf(kb, monkeypatch):
    monkeypatch.setattr(kb, "extract_pdf_text", lambda b: "")
    res = kb.ingest(b"x", title="Scan.pdf")
    assert res["ok"] is False
    assert "scanned" in res["error"].lower()


def test_ingest_replaces_same_title(kb, monkeypatch):
    monkeypatch.setattr(kb, "extract_pdf_text", lambda b: "obsolete clause zeta")
    kb.ingest(b"x", title="Labor Code")
    monkeypatch.setattr(kb, "extract_pdf_text", lambda b: "revised clause omega")
    kb.ingest(b"x", title="Labor Code")

    titles = [d["title"] for d in kb.list_documents()]
    assert titles.count("Labor Code") == 1  # replaced, not duplicated
    assert kb.retrieve("omega")  # new content indexed
    assert kb.retrieve("zeta") == []  # old chunks purged


def test_list_get_and_delete(kb, monkeypatch):
    monkeypatch.setattr(kb, "extract_pdf_text", lambda b: "some legal content for indexing")
    doc_id = kb.ingest(b"x", title="Constitution", file_id="FID")["doc_id"]

    assert any(d["doc_id"] == doc_id for d in kb.list_documents())
    assert kb.get_document(doc_id)["file_id"] == "FID"
    assert kb.has_documents() is True

    assert kb.delete_document(doc_id) is True
    assert kb.get_document(doc_id) is None
    assert kb.delete_document(doc_id) is False  # already gone


def test_disabled_without_sqlite_path():
    """With no SQLITE_PATH the module returns safe defaults everywhere."""
    old = os.environ.get("SQLITE_PATH")
    os.environ.pop("SQLITE_PATH", None)
    import bot.config as cfg
    import bot.knowledge as k

    importlib.reload(cfg)
    importlib.reload(k)
    try:
        assert k.available() is False
        assert k.has_documents() is False
        assert k.retrieve("anything") == []
        assert k.list_documents() == []
        assert k.get_document(1) is None
        assert k.delete_document(1) is False
        assert k.ingest(b"x", title="X")["ok"] is False
    finally:
        if old is not None:
            os.environ["SQLITE_PATH"] = old
        importlib.reload(cfg)
        importlib.reload(k)
