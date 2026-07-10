"""Retrieval-augmented knowledge base over admin-uploaded PDF legal texts.

The bot answers legal questions grounded in the *actual* text of uploaded
documents (RA codes, the Constitution, etc.) instead of the model's memory.
This kills hallucinated article numbers and lets every answer cite its source.

**Why SQLite FTS5 and not embeddings?** PythonAnywhere's free tier only allows
outbound HTTPS to a short whitelist and can't fit heavy ML libraries. FTS5
(full-text search) is compiled into Python's stdlib ``sqlite3`` — pure local
keyword/BM25 search, zero extra dependencies, zero extra network calls. Its
``unicode61`` tokenizer case-folds and splits Armenian, Russian, and Latin
text alike, so a question in any of the three retrieves the right articles.

Enabled only when ``SQLITE_PATH`` is set AND the sqlite build has FTS5.
Otherwise every function degrades to a safe default (``retrieve`` → ``[]``,
``ingest`` → an error dict), so the bot keeps working as a plain chat bot.
"""

import io
import re
import sqlite3
from datetime import datetime

from bot.config import (
    KB_CHUNK_OVERLAP,
    KB_CHUNK_SIZE,
    KB_MAX_CONTEXT_CHARS,
    KB_TOP_K,
    SQLITE_PATH,
)

_conn = None
_ENABLED = False


def _init() -> None:
    """Open the DB, verify FTS5, and create tables. Best-effort — any
    failure leaves the module disabled rather than crashing worker boot."""
    global _conn, _ENABLED
    if not SQLITE_PATH:
        print("Knowledge base: SQLITE_PATH unset — document search disabled.")
        return
    try:
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        # Probe FTS5 availability before relying on it.
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _kb_fts_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _kb_fts_probe")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS kb_documents (
                doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                upload_date TEXT NOT NULL,
                file_id TEXT,
                file_unique_id TEXT,
                uploader_id INTEGER,
                chunk_count INTEGER DEFAULT 0,
                created_at INTEGER
            )"""
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks "
            "USING fts5(doc_id UNINDEXED, title UNINDEXED, body)"
        )
        conn.commit()
        _conn = conn
        _ENABLED = True
        print("Knowledge base: ready (SQLite FTS5).")
    except sqlite3.OperationalError as e:
        print(f"Knowledge base: FTS5 unavailable ({e}) — document search disabled.")
    except Exception as e:  # pragma: no cover - defensive
        print(f"Knowledge base: init failed ({e}) — document search disabled.")


_init()


def available() -> bool:
    """True when the knowledge base is usable (storage + FTS5 present)."""
    return _ENABLED


def has_documents() -> bool:
    """True when at least one document has been ingested."""
    if not _ENABLED:
        return False
    try:
        row = _conn.execute("SELECT 1 FROM kb_documents LIMIT 1").fetchone()
        return row is not None
    except Exception:
        return False


# ── Text extraction & chunking ──────────────────────────────────────────────


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract selectable text from a PDF. Empty result → scanned/image PDF.

    pypdf is imported lazily so this module still imports (and the bot still
    runs) in environments where pypdf isn't installed — only ingest breaks."""
    from pypdf import PdfReader  # lazy: keeps module import dependency-free

    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            # A single unreadable page shouldn't abort the whole document.
            continue
    return "\n".join(parts)


def chunk_text(
    text: str, size: int = KB_CHUNK_SIZE, overlap: int = KB_CHUNK_OVERLAP
) -> list[str]:
    """Split text into overlapping, roughly ``size``-char chunks.

    Prefers breaking on paragraph → line → sentence boundaries near the end
    of each window so an article isn't sliced mid-sentence. Overlap keeps
    context that straddles a boundary retrievable from either chunk."""
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start, n = 0, len(text)
    half = size * 0.5
    while start < n:
        end = min(start + size, n)
        if end < n:
            window = text[start:end]
            brk = window.rfind("\n\n")
            if brk < half:
                brk = window.rfind("\n")
            if brk < half:
                brk = window.rfind(". ")
            if brk > half:
                end = start + brk + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


# ── Ingestion ────────────────────────────────────────────────────────────────


def ingest(
    pdf_bytes: bytes,
    title: str,
    file_id: str | None = None,
    file_unique_id: str | None = None,
    uploader_id: int | None = None,
    upload_date: str | None = None,
) -> dict:
    """Extract, chunk, and index a PDF. Re-uploading the same title REPLACES
    the prior version (so an admin can push a corrected file).

    Returns a result dict: ``{"ok": True, "doc_id", "title", "upload_date",
    "chunk_count"}`` or ``{"ok": False, "error": <message>}``."""
    if not _ENABLED:
        return {"ok": False, "error": "Knowledge base is not configured (no persistent storage)."}
    try:
        text = extract_pdf_text(pdf_bytes)
    except Exception as e:
        return {"ok": False, "error": f"Could not read the PDF ({e})."}
    chunks = chunk_text(text)
    if not chunks:
        return {
            "ok": False,
            "error": "No selectable text found — this PDF looks like scanned images, "
            "which I can't read (OCR isn't available on the server).",
        }
    upload_date = upload_date or datetime.now().strftime("%d.%m.%y")
    created = int(datetime.now().timestamp())
    try:
        # Replace-by-title: drop any existing document with the same name.
        old = _conn.execute(
            "SELECT doc_id FROM kb_documents WHERE title = ?", (title,)
        ).fetchall()
        for (old_id,) in old:
            _conn.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (old_id,))
            _conn.execute("DELETE FROM kb_documents WHERE doc_id = ?", (old_id,))
        cur = _conn.execute(
            "INSERT INTO kb_documents "
            "(title, upload_date, file_id, file_unique_id, uploader_id, chunk_count, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (title, upload_date, file_id, file_unique_id, uploader_id, len(chunks), created),
        )
        doc_id = cur.lastrowid
        _conn.executemany(
            "INSERT INTO kb_chunks (doc_id, title, body) VALUES (?,?,?)",
            [(doc_id, title, c) for c in chunks],
        )
        _conn.commit()
    except Exception as e:
        return {"ok": False, "error": f"Storage error while indexing ({e})."}
    return {
        "ok": True,
        "doc_id": doc_id,
        "title": title,
        "upload_date": upload_date,
        "chunk_count": len(chunks),
    }


# ── Retrieval ─────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _fts_query(text: str, max_terms: int = 24) -> str:
    """Turn free-text into a safe FTS5 MATCH expression.

    Each word is quoted (neutralizing FTS5 operators like ``*``/``:``/``OR``
    that a user might type) and the terms are OR-ed for recall. Single-char
    noise is dropped, but digits are kept so 'Article 258' still matches."""
    tokens = _TOKEN_RE.findall(text or "")
    tokens = [t for t in tokens if len(t) >= 2 or t.isdigit()][:max_terms]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


# Article references a user might type, across the three languages the codes
# use: "Article 258", "art. 12", "Հոդված 104", "hodvats 15", "Статья 42",
# "ст. 7", or a bare "№ 258". Captures the number so we can pin the exact
# article's chunk to the top of the results.
# Word stems (``\w*`` tails) absorb the case endings each language adds:
# Armenian հոդված→հոդվածի/ը/ում, Russian стать→статья/статьи/статью/статей.
_ARTICLE_RE = re.compile(
    r"(?:articles?|art\.?|հոդված\w*|hodvats?\w*|стать\w*|ст\.?|№)\s*№?\s*(\d{1,4})",
    re.IGNORECASE | re.UNICODE,
)


def _article_numbers(text: str) -> list[str]:
    """Extract article numbers a user referenced, in order, de-duplicated."""
    seen, out = set(), []
    for num in _ARTICLE_RE.findall(text or ""):
        if num not in seen:
            seen.add(num)
            out.append(num)
    return out


def _run_match(match: str, limit: int, doc_id: int | None = None) -> list:
    """Execute one FTS5 MATCH and return raw rows (rowid + fields).

    When ``doc_id`` is given, results are restricted to that single document
    (study mode) so answers can't leak in from other codes."""
    sql = (
        "SELECT kb_chunks.rowid, kb_chunks.doc_id, kb_chunks.title, kb_chunks.body, "
        "kb_documents.upload_date "
        "FROM kb_chunks JOIN kb_documents ON kb_documents.doc_id = kb_chunks.doc_id "
        "WHERE kb_chunks MATCH ?"
    )
    params: tuple = (match,)
    if doc_id is not None:
        sql += " AND kb_chunks.doc_id = ?"
        params += (doc_id,)
    sql += " ORDER BY bm25(kb_chunks) LIMIT ?"
    params += (limit,)
    return _conn.execute(sql, params).fetchall()


def retrieve(query: str, k: int = KB_TOP_K, doc_id: int | None = None) -> list[dict]:
    """Return up to ``k`` most relevant chunks for ``query``, best first.

    When ``doc_id`` is set, retrieval is scoped to that one document (study
    mode). Two-pass for legal codes: any article number the user cited (e.g.
    "Article 258", "Հոդված 104", "Статья 42") is looked up directly and its
    chunk pinned to the front, then the rest is filled with normal keyword
    (BM25) matches. Each item: ``{"doc_id", "title", "upload_date", "body"}``.
    Empty list when disabled, when the query has no usable terms, or on error."""
    if not _ENABLED:
        return []
    match = _fts_query(query)
    if not match:
        return []
    seen_rowids: set = set()
    picked: list = []

    try:
        # Pass 1 — exact article lookups, pinned to the top. Matching the bare
        # number leans on BM25 to surface the chunk where it's most salient
        # (the article heading) rather than an incidental mention.
        for num in _article_numbers(query):
            for r in _run_match(f'"{num}"', 3, doc_id):
                if r[0] not in seen_rowids:
                    seen_rowids.add(r[0])
                    picked.append(r)

        # Pass 2 — normal keyword recall, fills the remaining budget.
        for r in _run_match(match, k, doc_id):
            if len(picked) >= k:
                break
            if r[0] not in seen_rowids:
                seen_rowids.add(r[0])
                picked.append(r)
    except Exception as e:
        print(f"Knowledge retrieve error: {e}")
        return []

    return [
        {"doc_id": r[1], "title": r[2], "body": r[3], "upload_date": r[4]}
        for r in picked[:k]
    ]


def overview_chunks(doc_id: int, n: int = 6) -> list[dict]:
    """Return the first ``n`` chunks of a document in reading order.

    Used for "what is this document about / main idea / summarize" questions:
    a legal code states its scope and general provisions up front, so the
    opening chunks are the closest thing to a summary we can retrieve without
    embeddings. Same item shape as ``retrieve``. Empty on disabled/error."""
    if not _ENABLED:
        return []
    try:
        rows = _conn.execute(
            "SELECT kb_chunks.doc_id, kb_chunks.title, kb_chunks.body, kb_documents.upload_date "
            "FROM kb_chunks JOIN kb_documents ON kb_documents.doc_id = kb_chunks.doc_id "
            "WHERE kb_chunks.doc_id = ? ORDER BY kb_chunks.rowid LIMIT ?",
            (doc_id, n),
        ).fetchall()
    except Exception as e:
        print(f"Knowledge overview error: {e}")
        return []
    return [
        {"doc_id": r[0], "title": r[1], "body": r[2], "upload_date": r[3]}
        for r in rows
    ]


def build_context(results: list[dict], max_chars: int = KB_MAX_CONTEXT_CHARS):
    """Format retrieved chunks into a prompt block + the distinct sources.

    Returns ``(context_str, sources)`` where sources is a list of
    ``(title, upload_date)`` tuples in first-seen order (for the citation
    footer). Stops adding chunks once ``max_chars`` would be exceeded."""
    block, sources, used = [], [], 0
    for r in results:
        piece = f"[Source: {r['title']}]\n{r['body']}"
        if block and used + len(piece) > max_chars:
            break
        block.append(piece)
        used += len(piece)
        src = (r["title"], r["upload_date"])
        if src not in sources:
            sources.append(src)
    return "\n\n---\n\n".join(block), sources


# ── Document management (for /documents, downloads, /deldoc) ──────────────────


def list_documents() -> list[dict]:
    """All documents, newest first. Each: doc_id, title, upload_date,
    file_id, chunk_count."""
    if not _ENABLED:
        return []
    try:
        rows = _conn.execute(
            "SELECT doc_id, title, upload_date, file_id, chunk_count "
            "FROM kb_documents ORDER BY created_at DESC, doc_id DESC"
        ).fetchall()
    except Exception as e:
        print(f"Knowledge list error: {e}")
        return []
    return [
        {"doc_id": r[0], "title": r[1], "upload_date": r[2], "file_id": r[3], "chunk_count": r[4]}
        for r in rows
    ]


def get_document(doc_id: int) -> dict | None:
    """Single document by id, or None."""
    if not _ENABLED:
        return None
    try:
        r = _conn.execute(
            "SELECT doc_id, title, upload_date, file_id, chunk_count "
            "FROM kb_documents WHERE doc_id = ?",
            (doc_id,),
        ).fetchone()
    except Exception as e:
        print(f"Knowledge get error: {e}")
        return None
    if not r:
        return None
    return {"doc_id": r[0], "title": r[1], "upload_date": r[2], "file_id": r[3], "chunk_count": r[4]}


def delete_document(doc_id: int) -> bool:
    """Remove a document and its indexed chunks. True if something was deleted."""
    if not _ENABLED:
        return False
    try:
        _conn.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (doc_id,))
        cur = _conn.execute("DELETE FROM kb_documents WHERE doc_id = ?", (doc_id,))
        _conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        print(f"Knowledge delete error: {e}")
        return False
