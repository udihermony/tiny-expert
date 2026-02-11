"""SQLite database setup and queries for the pipeline."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "pipeline.db"


def get_db():
    """Get a database connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT DEFAULT '',
            type TEXT DEFAULT 'unknown',
            filename TEXT NOT NULL,
            date_added TEXT NOT NULL,
            status TEXT DEFAULT 'uploaded',
            chunk_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            chapter TEXT DEFAULT '',
            section TEXT DEFAULT '',
            text TEXT NOT NULL,
            embedding TEXT,
            token_count INTEGER DEFAULT 0,
            chunk_index INTEGER DEFAULT 0,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            question_type TEXT DEFAULT 'direct',
            source_chunk_ids TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending_answer',
            date_generated TEXT NOT NULL,
            category TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS qa_pairs (
            id TEXT PRIMARY KEY,
            question_id TEXT NOT NULL,
            question TEXT NOT NULL,
            question_type TEXT DEFAULT 'direct',
            answer TEXT NOT NULL,
            answer_short TEXT DEFAULT '',
            sources_used TEXT DEFAULT '[]',
            related_questions TEXT DEFAULT '[]',
            category TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            urgency TEXT DEFAULT 'medium',
            confidence TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'pending_review',
            date_generated TEXT NOT NULL,
            date_reviewed TEXT,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


# --- Source operations ---

def create_source(source_id, title, filename, author="", source_type="unknown"):
    conn = get_db()
    conn.execute(
        "INSERT INTO sources (id, title, author, type, filename, date_added, status) VALUES (?, ?, ?, ?, ?, ?, 'uploaded')",
        (source_id, title, author, source_type, filename, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return source_id


def update_source_status(source_id, status, chunk_count=None):
    conn = get_db()
    if chunk_count is not None:
        conn.execute("UPDATE sources SET status=?, chunk_count=? WHERE id=?", (status, chunk_count, source_id))
    else:
        conn.execute("UPDATE sources SET status=? WHERE id=?", (status, source_id))
    conn.commit()
    conn.close()


def get_sources():
    conn = get_db()
    rows = conn.execute("SELECT * FROM sources ORDER BY date_added DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_source(source_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_source(source_id):
    conn = get_db()
    conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
    conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    conn.commit()
    conn.close()


# --- Chunk operations ---

def save_chunks(chunks):
    """Save a list of chunk dicts to the database."""
    conn = get_db()
    for c in chunks:
        embedding_json = json.dumps(c.get("embedding")) if c.get("embedding") else None
        conn.execute(
            "INSERT OR REPLACE INTO chunks (id, source_id, chapter, section, text, embedding, token_count, chunk_index) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (c["id"], c["source_id"], c.get("chapter", ""), c.get("section", ""),
             c["text"], embedding_json, c.get("token_count", 0), c.get("chunk_index", 0))
        )
    conn.commit()
    conn.close()


def get_chunks_for_source(source_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM chunks WHERE source_id=? ORDER BY chunk_index", (source_id,)).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("embedding"):
            d["embedding"] = json.loads(d["embedding"])
        result.append(d)
    return result


def get_all_chunks_with_embeddings():
    """Get all chunks that have embeddings."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM chunks WHERE embedding IS NOT NULL ORDER BY source_id, chunk_index").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("embedding"):
            d["embedding"] = json.loads(d["embedding"])
        result.append(d)
    return result


# --- Question operations ---

def save_questions(questions):
    conn = get_db()
    for q in questions:
        conn.execute(
            "INSERT OR REPLACE INTO questions (id, text, question_type, source_chunk_ids, status, date_generated, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (q["id"], q["text"], q.get("question_type", "direct"),
             json.dumps(q.get("source_chunk_ids", [])), q.get("status", "pending_answer"),
             q.get("date_generated", datetime.now().isoformat()), q.get("category", ""))
        )
    conn.commit()
    conn.close()


def get_questions(status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM questions WHERE status=? ORDER BY date_generated", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM questions ORDER BY date_generated").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["source_chunk_ids"] = json.loads(d.get("source_chunk_ids", "[]"))
        result.append(d)
    return result


def update_question_status(question_id, status):
    conn = get_db()
    conn.execute("UPDATE questions SET status=? WHERE id=?", (status, question_id))
    conn.commit()
    conn.close()


def update_question(question_id, text=None, question_type=None, category=None, status=None):
    """Update question fields."""
    conn = get_db()
    updates = []
    params = []
    if text is not None:
        updates.append("text=?")
        params.append(text)
    if question_type is not None:
        updates.append("question_type=?")
        params.append(question_type)
    if category is not None:
        updates.append("category=?")
        params.append(category)
    if status is not None:
        updates.append("status=?")
        params.append(status)
    if updates:
        params.append(question_id)
        conn.execute(f"UPDATE questions SET {', '.join(updates)} WHERE id=?", params)
        conn.commit()
    conn.close()


def delete_question(question_id):
    conn = get_db()
    conn.execute("DELETE FROM questions WHERE id=?", (question_id,))
    conn.commit()
    conn.close()


def delete_all_questions():
    conn = get_db()
    conn.execute("DELETE FROM questions")
    conn.commit()
    conn.close()


def delete_all_qa_pairs():
    conn = get_db()
    conn.execute("DELETE FROM qa_pairs")
    conn.commit()
    conn.close()


def get_question_count_for_source(source_id):
    """Count questions that reference chunks from a given source."""
    conn = get_db()
    # Questions store source_chunk_ids as JSON array — search for the source prefix
    rows = conn.execute(
        "SELECT COUNT(*) as cnt FROM questions WHERE source_chunk_ids LIKE ?",
        (f'%chunk-{source_id}%',)
    ).fetchone()
    conn.close()
    return rows["cnt"] if rows else 0


# --- QA pair operations ---

def save_qa_pair(qa):
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO qa_pairs
        (id, question_id, question, question_type, answer, answer_short, sources_used,
         related_questions, category, tags, urgency, confidence, status, date_generated, date_reviewed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (qa["id"], qa["question_id"], qa["question"], qa.get("question_type", "direct"),
         qa["answer"], qa.get("answer_short", ""), json.dumps(qa.get("sources_used", [])),
         json.dumps(qa.get("related_questions", [])), qa.get("category", ""),
         json.dumps(qa.get("tags", [])), qa.get("urgency", "medium"),
         qa.get("confidence", "medium"), qa.get("status", "pending_review"),
         qa.get("date_generated", datetime.now().isoformat()), qa.get("date_reviewed"))
    )
    conn.commit()
    conn.close()


def get_qa_pairs(status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM qa_pairs WHERE status=? ORDER BY date_generated", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM qa_pairs ORDER BY date_generated").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["sources_used"] = json.loads(d.get("sources_used", "[]"))
        d["related_questions"] = json.loads(d.get("related_questions", "[]"))
        d["tags"] = json.loads(d.get("tags", "[]"))
        result.append(d)
    return result


def update_qa_status(qa_id, status):
    conn = get_db()
    conn.execute("UPDATE qa_pairs SET status=?, date_reviewed=? WHERE id=?",
                 (status, datetime.now().isoformat(), qa_id))
    conn.commit()
    conn.close()


def update_qa_pair(qa_id, **kwargs):
    """Update QA pair fields."""
    conn = get_db()
    updates = []
    params = []
    simple_fields = ["question", "question_type", "answer", "answer_short",
                     "category", "urgency", "confidence", "status"]
    json_fields = ["tags", "sources_used", "related_questions"]

    for field in simple_fields:
        if field in kwargs and kwargs[field] is not None:
            updates.append(f"{field}=?")
            params.append(kwargs[field])

    for field in json_fields:
        if field in kwargs and kwargs[field] is not None:
            updates.append(f"{field}=?")
            params.append(json.dumps(kwargs[field]))

    if "status" in kwargs:
        updates.append("date_reviewed=?")
        params.append(datetime.now().isoformat())

    if updates:
        params.append(qa_id)
        conn.execute(f"UPDATE qa_pairs SET {', '.join(updates)} WHERE id=?", params)
        conn.commit()
    conn.close()


def delete_qa_pair(qa_id):
    conn = get_db()
    conn.execute("DELETE FROM qa_pairs WHERE id=?", (qa_id,))
    conn.commit()
    conn.close()


def get_qa_pair(qa_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM qa_pairs WHERE id=?", (qa_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["sources_used"] = json.loads(d.get("sources_used", "[]"))
    d["related_questions"] = json.loads(d.get("related_questions", "[]"))
    d["tags"] = json.loads(d.get("tags", "[]"))
    return d


# Initialize on import
init_db()
