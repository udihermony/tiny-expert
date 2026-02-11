#!/usr/bin/env python3
"""FastAPI backend for the Knowledge Curation Pipeline."""

import asyncio
import hashlib
import shutil
import traceback
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import database as db
from parsers import parse_file
from pipeline.chunker import chunk_sections
from pipeline.embedder import embed_chunks
from pipeline.question_gen import (
    generate_questions_for_chunk, load_prompt, save_prompt, estimate_batch_cost
)
from pipeline.answer_gen import (
    generate_answer, retrieve_relevant_chunks, format_sources_for_prompt,
    load_prompt as load_answer_prompt, save_prompt as save_answer_prompt,
    estimate_answer_cost
)
from pipeline.exporter import export_qa_pairs

SCRIPT_DIR = Path(__file__).parent
UPLOAD_DIR = SCRIPT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Tiny Expert Pipeline")


# --- Static files ---
app.mount("/static", StaticFiles(directory=str(SCRIPT_DIR / "static")), name="static")


@app.get("/")
async def index():
    return FileResponse(str(SCRIPT_DIR / "static" / "index.html"))


# =====================
# Source endpoints
# =====================

@app.get("/api/sources")
async def list_sources():
    return db.get_sources()


@app.post("/api/sources/upload")
async def upload_source(
    file: UploadFile = File(...),
    title: str = Form(""),
    author: str = Form(""),
    source_type: str = Form("unknown")
):
    """Upload a source file (PDF, TXT, MD)."""
    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".txt", ".md", ".text", ".markdown"):
        raise HTTPException(400, f"Unsupported file type: {ext}")

    # Generate source ID from filename
    source_id = "src-" + hashlib.md5(file.filename.encode()).hexdigest()[:8]

    # Check if already exists
    if db.get_source(source_id):
        raise HTTPException(409, f"Source already uploaded: {file.filename}")

    # Save file
    dest = UPLOAD_DIR / f"{source_id}{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Create source record
    if not title:
        title = Path(file.filename).stem.replace("-", " ").replace("_", " ").title()

    db.create_source(source_id, title, file.filename, author, source_type)

    return {"id": source_id, "title": title, "status": "uploaded"}


@app.post("/api/sources/{source_id}/parse")
async def parse_source(source_id: str):
    """Parse an uploaded source into chunks and compute embeddings."""
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    # Find the uploaded file
    upload_files = list(UPLOAD_DIR.glob(f"{source_id}.*"))
    if not upload_files:
        raise HTTPException(404, "Upload file not found")

    filepath = upload_files[0]
    db.update_source_status(source_id, "parsing")

    try:
        # Parse file into sections
        sections = parse_file(str(filepath))

        # Chunk sections
        chunks = chunk_sections(sections, source_id)

        # Compute embeddings
        chunks = embed_chunks(chunks)

        # Save to database
        db.save_chunks(chunks)
        db.update_source_status(source_id, "indexed", chunk_count=len(chunks))

        return {
            "source_id": source_id,
            "status": "indexed",
            "chunks": len(chunks),
            "sections": len(sections)
        }
    except Exception as e:
        db.update_source_status(source_id, "error")
        traceback.print_exc()
        raise HTTPException(500, f"Parse error: {str(e)}")


@app.get("/api/sources/{source_id}/chunks")
async def get_source_chunks(source_id: str):
    """Get all chunks for a source."""
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    chunks = db.get_chunks_for_source(source_id)
    # Don't send embeddings to frontend (too large)
    for c in chunks:
        c.pop("embedding", None)
    return chunks


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: str):
    """Delete a source and its chunks."""
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    # Delete upload file
    for f in UPLOAD_DIR.glob(f"{source_id}.*"):
        f.unlink()

    db.delete_source(source_id)
    return {"status": "deleted"}


# =====================
# Question endpoints
# =====================

@app.get("/api/questions")
async def list_questions(status: str = None):
    return db.get_questions(status)


@app.get("/api/questions/prompt")
async def get_question_prompt():
    """Get the current question generation prompt."""
    return {"prompt": load_prompt()}


@app.post("/api/questions/prompt")
async def update_question_prompt(request: Request):
    """Update the question generation prompt."""
    body = await request.json()
    save_prompt(body.get("prompt", ""))
    return {"status": "saved"}


@app.post("/api/questions/estimate")
async def estimate_cost(request: Request):
    """Estimate API cost for question generation."""
    body = await request.json()
    source_ids = body.get("source_ids", [])

    chunks = []
    for sid in source_ids:
        chunks.extend(db.get_chunks_for_source(sid))

    return estimate_batch_cost(chunks)


@app.post("/api/questions/generate")
async def generate_questions_batch(request: Request):
    """Generate questions from source chunks. Streams progress via SSE."""
    body = await request.json()
    source_ids = body.get("source_ids", [])
    api_key = body.get("api_key", "")

    if not source_ids:
        raise HTTPException(400, "No sources selected")

    # Gather chunks
    chunks = []
    for sid in source_ids:
        chunks.extend(db.get_chunks_for_source(sid))

    if not chunks:
        raise HTTPException(400, "No chunks found for selected sources")

    prompt_template = load_prompt()

    async def event_stream():
        import json, time
        total = len(chunks)
        total_questions = 0
        total_cost = 0.0
        errors = []

        for i, chunk in enumerate(chunks):
            try:
                questions, raw, usage = generate_questions_for_chunk(
                    chunk, prompt_template=prompt_template, api_key=api_key
                )
                # Save to DB
                db.save_questions(questions)
                total_questions += len(questions)
                total_cost += usage.get("cost_estimate", 0)

                yield f"data: {json.dumps({'type': 'progress', 'current': i+1, 'total': total, 'chunk_id': chunk['id'], 'questions_generated': len(questions), 'total_questions': total_questions, 'cost_so_far': round(total_cost, 4)})}\n\n"

            except Exception as e:
                errors.append({"chunk_id": chunk["id"], "error": str(e)})
                yield f"data: {json.dumps({'type': 'error', 'current': i+1, 'total': total, 'chunk_id': chunk['id'], 'error': str(e)})}\n\n"

            # Rate limiting
            if i < total - 1:
                await asyncio.sleep(1.0)

        yield f"data: {json.dumps({'type': 'done', 'total_questions': total_questions, 'total_cost': round(total_cost, 4), 'errors': len(errors)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.put("/api/questions/{question_id}")
async def update_question(question_id: str, request: Request):
    """Update a question's text, type, category, or status."""
    body = await request.json()
    db.update_question(
        question_id,
        text=body.get("text"),
        question_type=body.get("question_type"),
        category=body.get("category"),
        status=body.get("status"),
    )
    return {"status": "updated"}


@app.delete("/api/questions/{question_id}")
async def delete_question(question_id: str):
    db.delete_question(question_id)
    return {"status": "deleted"}


@app.delete("/api/questions")
async def delete_all_questions():
    db.delete_all_questions()
    return {"status": "deleted"}


# =====================
# Answer endpoints
# =====================

@app.get("/api/answers")
async def list_answers(status: str = None):
    return db.get_qa_pairs(status)


@app.get("/api/answers/prompt")
async def get_answer_prompt():
    return {"prompt": load_answer_prompt()}


@app.post("/api/answers/prompt")
async def update_answer_prompt(request: Request):
    body = await request.json()
    save_answer_prompt(body.get("prompt", ""))
    return {"status": "saved"}


@app.post("/api/answers/estimate")
async def estimate_answer_batch_cost(request: Request):
    body = await request.json()
    question_ids = body.get("question_ids", [])
    if not question_ids:
        # Count all pending questions
        pending = db.get_questions("pending_answer")
        return estimate_answer_cost(len(pending))
    return estimate_answer_cost(len(question_ids))


@app.post("/api/answers/preview/{question_id}")
async def preview_answer_chunks(question_id: str):
    """Preview which chunks would be retrieved for a question."""
    questions = db.get_questions()
    question = next((q for q in questions if q["id"] == question_id), None)
    if not question:
        raise HTTPException(404, "Question not found")

    all_chunks = db.get_all_chunks_with_embeddings()
    relevant = retrieve_relevant_chunks(
        question["text"], all_chunks, top_k=10,
        original_chunk_ids=question.get("source_chunk_ids", [])
    )

    # Strip embeddings before sending
    for c in relevant:
        c.pop("embedding", None)

    return {"question": question["text"], "chunks": relevant}


@app.post("/api/answers/generate")
async def generate_answers_batch(request: Request):
    """Generate answers for pending questions. Streams progress via SSE."""
    body = await request.json()
    api_key = body.get("api_key", "")
    question_ids = body.get("question_ids", [])

    # Get questions to answer
    if question_ids:
        all_q = db.get_questions()
        questions = [q for q in all_q if q["id"] in question_ids]
    else:
        questions = db.get_questions("pending_answer")

    if not questions:
        raise HTTPException(400, "No pending questions to answer")

    # Load all chunks with embeddings for retrieval
    all_chunks = db.get_all_chunks_with_embeddings()
    prompt_template = load_answer_prompt()

    async def event_stream():
        import json
        total = len(questions)
        total_answers = 0
        total_cost = 0.0
        errors = []

        for i, question in enumerate(questions):
            try:
                # Retrieve relevant chunks
                relevant = retrieve_relevant_chunks(
                    question["text"], all_chunks, top_k=10,
                    original_chunk_ids=question.get("source_chunk_ids", [])
                )

                # Generate answer
                qa, raw, usage = generate_answer(
                    question, relevant,
                    prompt_template=prompt_template, api_key=api_key
                )

                # Save QA pair
                db.save_qa_pair(qa)
                # Mark question as answered
                db.update_question_status(question["id"], "answered")

                total_answers += 1
                total_cost += usage.get("cost_estimate", 0)

                yield f"data: {json.dumps({'type': 'progress', 'current': i+1, 'total': total, 'question': question['text'][:80], 'chunks_used': usage['chunks_used'], 'total_answers': total_answers, 'cost_so_far': round(total_cost, 4)})}\n\n"

            except Exception as e:
                errors.append({"question_id": question["id"], "error": str(e)})
                yield f"data: {json.dumps({'type': 'error', 'current': i+1, 'total': total, 'question_id': question['id'], 'error': str(e)})}\n\n"

            # Rate limiting
            if i < total - 1:
                await asyncio.sleep(1.0)

        yield f"data: {json.dumps({'type': 'done', 'total_answers': total_answers, 'total_cost': round(total_cost, 4), 'errors': len(errors)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/answers/generate-single/{question_id}")
async def generate_single_answer(question_id: str, request: Request):
    """Generate answer for a single question (non-streaming)."""
    body = await request.json()
    api_key = body.get("api_key", "")

    questions = db.get_questions()
    question = next((q for q in questions if q["id"] == question_id), None)
    if not question:
        raise HTTPException(404, "Question not found")

    all_chunks = db.get_all_chunks_with_embeddings()
    relevant = retrieve_relevant_chunks(
        question["text"], all_chunks, top_k=10,
        original_chunk_ids=question.get("source_chunk_ids", [])
    )

    prompt_template = load_answer_prompt()
    qa, raw, usage = generate_answer(
        question, relevant, prompt_template=prompt_template, api_key=api_key
    )

    db.save_qa_pair(qa)
    db.update_question_status(question["id"], "answered")

    return {"qa": qa, "usage": usage, "raw": raw}


# =====================
# Review endpoints
# =====================

@app.get("/api/review")
async def list_review(status: str = None):
    """List QA pairs for review. Default: pending_review."""
    return db.get_qa_pairs(status or "pending_review")


@app.put("/api/review/{qa_id}")
async def update_qa(qa_id: str, request: Request):
    """Update a QA pair (edit answer, change status, etc.)."""
    body = await request.json()
    qa = db.get_qa_pair(qa_id)
    if not qa:
        raise HTTPException(404, "QA pair not found")

    db.update_qa_pair(
        qa_id,
        question=body.get("question"),
        answer=body.get("answer"),
        answer_short=body.get("answer_short"),
        category=body.get("category"),
        tags=body.get("tags"),
        urgency=body.get("urgency"),
        confidence=body.get("confidence"),
        status=body.get("status"),
    )
    return {"status": "updated"}


@app.post("/api/review/bulk-approve")
async def bulk_approve(request: Request):
    """Approve multiple QA pairs at once."""
    body = await request.json()
    qa_ids = body.get("qa_ids", [])

    if not qa_ids:
        # Approve all pending
        pending = db.get_qa_pairs("pending_review")
        qa_ids = [qa["id"] for qa in pending]

    count = 0
    for qa_id in qa_ids:
        db.update_qa_status(qa_id, "approved")
        count += 1

    return {"approved": count}


@app.delete("/api/review/{qa_id}")
async def delete_qa(qa_id: str):
    """Delete a QA pair."""
    db.delete_qa_pair(qa_id)
    return {"status": "deleted"}


@app.delete("/api/answers")
async def delete_all_answers():
    db.delete_all_qa_pairs()
    return {"status": "deleted"}


# =====================
# Export endpoints
# =====================

@app.get("/api/export")
async def get_export():
    """Generate export JSON from approved QA pairs."""
    approved = db.get_qa_pairs("approved")
    sources = db.get_sources()
    export_data = export_qa_pairs(approved, sources)
    return export_data


@app.get("/api/export/stats")
async def get_export_stats():
    """Get export statistics."""
    approved = db.get_qa_pairs("approved")
    from collections import Counter
    categories = Counter(qa.get("category", "unknown") for qa in approved)
    types = Counter(qa.get("question_type", "direct") for qa in approved)

    all_qa = db.get_qa_pairs()
    return {
        "total_approved": len(approved),
        "total_all": len(all_qa),
        "total_pending": sum(1 for qa in all_qa if qa["status"] == "pending_review"),
        "total_discarded": sum(1 for qa in all_qa if qa["status"] == "discarded"),
        "categories": dict(categories),
        "question_types": dict(types),
        "sources_used": len(set(
            su["source_id"]
            for qa in approved
            for su in (qa.get("sources_used") or [])
        )),
    }


@app.post("/api/export/download")
async def download_export():
    """Download export as a JSON file."""
    import json as json_mod
    approved = db.get_qa_pairs("approved")
    sources = db.get_sources()
    export_data = export_qa_pairs(approved, sources)

    content = json_mod.dumps(export_data, indent=2, ensure_ascii=False)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=tiny-expert-qa-export.json"}
    )


# =====================
# Stats endpoint
# =====================

@app.get("/api/stats")
async def get_stats():
    sources = db.get_sources()
    questions = db.get_questions()
    qa_pairs = db.get_qa_pairs()

    return {
        "sources": len(sources),
        "sources_indexed": sum(1 for s in sources if s["status"] == "indexed"),
        "chunks": sum(s.get("chunk_count", 0) for s in sources),
        "questions": len(questions),
        "questions_pending": sum(1 for q in questions if q["status"] == "pending_answer"),
        "questions_answered": sum(1 for q in questions if q["status"] == "answered"),
        "qa_pairs": len(qa_pairs),
        "qa_approved": sum(1 for qa in qa_pairs if qa["status"] == "approved"),
        "qa_pending": sum(1 for qa in qa_pairs if qa["status"] == "pending_review"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
