"""Generate questions from source chunks using Claude API."""

import json
import os
import re
import time
import hashlib
from datetime import datetime
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
DEFAULT_DELAY = 1.0  # seconds between API calls


def load_prompt():
    """Load the question generation prompt template."""
    prompt_file = PROMPTS_DIR / "question_gen.txt"
    return prompt_file.read_text(encoding="utf-8")


def save_prompt(text):
    """Save an updated question generation prompt."""
    prompt_file = PROMPTS_DIR / "question_gen.txt"
    prompt_file.write_text(text, encoding="utf-8")


def generate_questions_for_chunk(chunk, prompt_template=None, api_key=None):
    """Generate questions for a single chunk using Claude API.

    Returns a list of question dicts with: question, type, category.
    Also returns the raw API response for debugging.
    """
    import anthropic

    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    if not prompt_template:
        prompt_template = load_prompt()

    # Fill in the template
    prompt = prompt_template.replace("{text}", chunk["text"])
    prompt = prompt.replace("{chapter}", chunk.get("chapter", ""))
    prompt = prompt.replace("{section}", chunk.get("section", ""))

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_text = response.content[0].text.strip()

    # Parse JSON response
    questions = _parse_questions_json(raw_text)

    # Add metadata
    chunk_id = chunk["id"]
    source_id = chunk["source_id"]
    result = []
    for i, q in enumerate(questions):
        q_id = "q-" + hashlib.md5(f"{chunk_id}-{i}-{q.get('question', '')}".encode()).hexdigest()[:10]
        result.append({
            "id": q_id,
            "text": q.get("question", ""),
            "question_type": q.get("type", "direct"),
            "category": q.get("category", ""),
            "source_chunk_ids": [chunk_id],
            "status": "pending_answer",
            "date_generated": datetime.now().isoformat(),
        })

    # Estimate cost: input + output tokens
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_estimate = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

    return result, raw_text, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimate": cost_estimate,
    }


def _parse_questions_json(text):
    """Parse JSON array from Claude's response, handling markdown fences."""
    # Strip markdown code fences
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text, flags=re.MULTILINE)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Could not parse questions JSON: {text[:200]}...")


def estimate_batch_cost(chunks):
    """Estimate API cost for generating questions from all chunks."""
    # Rough estimate: ~1500 input tokens per chunk, ~2000 output tokens
    total_input = len(chunks) * 1500
    total_output = len(chunks) * 2000
    cost = (total_input * 3.0 / 1_000_000) + (total_output * 15.0 / 1_000_000)
    return {
        "chunks": len(chunks),
        "estimated_input_tokens": total_input,
        "estimated_output_tokens": total_output,
        "estimated_cost_usd": round(cost, 4),
        "estimated_time_seconds": len(chunks) * 3,  # ~3s per call with rate limiting
    }
