"""Generate answers using cross-source retrieval and Claude API."""

import json
import os
import re
import hashlib
import numpy as np
from datetime import datetime
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt():
    """Load the answer generation prompt template."""
    return (PROMPTS_DIR / "answer_gen.txt").read_text(encoding="utf-8")


def save_prompt(text):
    """Save an updated answer generation prompt."""
    (PROMPTS_DIR / "answer_gen.txt").write_text(text, encoding="utf-8")


def cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    a = np.array(a)
    b = np.array(b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(np.dot(a, b) / norm)


def retrieve_relevant_chunks(question_text, all_chunks, top_k=10, original_chunk_ids=None):
    """Retrieve the most relevant chunks for a question using embedding similarity.

    Args:
        question_text: The question to find chunks for.
        all_chunks: List of chunk dicts with 'embedding' field.
        top_k: Number of top chunks to return.
        original_chunk_ids: Chunk IDs that generated this question (always included).

    Returns:
        List of chunk dicts sorted by relevance.
    """
    from pipeline.embedder import embed_texts

    # Embed the question
    q_embedding = embed_texts([question_text])[0]

    # Score all chunks
    scored = []
    for chunk in all_chunks:
        emb = chunk.get("embedding")
        if not emb:
            continue
        sim = cosine_similarity(q_embedding, emb)
        # Boost original chunks
        is_original = original_chunk_ids and chunk["id"] in original_chunk_ids
        scored.append((sim, is_original, chunk))

    # Sort: originals first (boosted), then by similarity
    scored.sort(key=lambda x: (x[1], x[0]), reverse=True)

    # Take top_k, ensuring originals are always included
    results = []
    seen = set()
    # Add originals first
    for sim, is_orig, chunk in scored:
        if is_orig and chunk["id"] not in seen:
            results.append(chunk)
            seen.add(chunk["id"])
    # Fill remaining with top similar
    for sim, is_orig, chunk in scored:
        if len(results) >= top_k:
            break
        if chunk["id"] not in seen:
            results.append(chunk)
            seen.add(chunk["id"])

    return results


def format_sources_for_prompt(chunks):
    """Format retrieved chunks as source text for the answer prompt."""
    parts = []
    for i, c in enumerate(chunks, 1):
        header = f"[Source {i}]"
        if c.get("chapter"):
            header += f" {c['chapter']}"
        if c.get("section"):
            header += f" > {c['section']}"
        parts.append(f"{header}\n{c['text']}")
    return "\n\n---\n\n".join(parts)


def generate_answer(question, chunks, prompt_template=None, api_key=None):
    """Generate an answer for a question using retrieved chunks.

    Returns: (qa_dict, raw_response, usage_info)
    """
    import anthropic

    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    if not prompt_template:
        prompt_template = load_prompt()

    sources_text = format_sources_for_prompt(chunks)
    prompt = prompt_template.replace("{question}", question["text"])
    prompt = prompt.replace("{sources}", sources_text)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_text = response.content[0].text.strip()
    parsed = _parse_answer_json(raw_text)

    # Build QA pair
    qa_id = "qa-" + hashlib.md5(f"{question['id']}-{datetime.now().isoformat()}".encode()).hexdigest()[:10]

    # Build sources_used from chunks
    sources_used = {}
    for c in chunks:
        sid = c["source_id"]
        if sid not in sources_used:
            sources_used[sid] = {"source_id": sid, "chunk_ids": []}
        sources_used[sid]["chunk_ids"].append(c["id"])

    qa = {
        "id": qa_id,
        "question_id": question["id"],
        "question": question["text"],
        "question_type": question.get("question_type", "direct"),
        "answer": parsed.get("answer", raw_text),
        "answer_short": parsed.get("answer_short", ""),
        "sources_used": list(sources_used.values()),
        "related_questions": [],
        "category": parsed.get("category", question.get("category", "")),
        "tags": parsed.get("tags", []),
        "urgency": parsed.get("urgency", "medium"),
        "confidence": parsed.get("confidence", "medium"),
        "status": "pending_review",
        "date_generated": datetime.now().isoformat(),
    }

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_estimate = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

    return qa, raw_text, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimate": cost_estimate,
        "chunks_used": len(chunks),
    }


def _parse_answer_json(text):
    """Parse JSON object from Claude's answer response."""
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text, flags=re.MULTILINE)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        # Return partial — answer is the raw text
        return {"answer": text}


def estimate_answer_cost(num_questions):
    """Estimate API cost for answer generation."""
    # ~3000 input tokens (question + retrieved chunks), ~1000 output tokens
    total_input = num_questions * 3000
    total_output = num_questions * 1000
    cost = (total_input * 3.0 / 1_000_000) + (total_output * 15.0 / 1_000_000)
    return {
        "questions": num_questions,
        "estimated_input_tokens": total_input,
        "estimated_output_tokens": total_output,
        "estimated_cost_usd": round(cost, 4),
        "estimated_time_seconds": num_questions * 4,
    }
