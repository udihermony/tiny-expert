"""Export approved Q&A pairs to JSON for the app."""

import json
from datetime import datetime
from collections import Counter


def export_qa_pairs(qa_pairs, sources):
    """Export approved Q&A pairs to the app's JSON format.

    Args:
        qa_pairs: List of approved QA pair dicts from the database.
        sources: List of source dicts for metadata.

    Returns:
        Export dict ready for JSON serialization.
    """
    # Count by category
    categories = Counter(qa.get("category", "unknown") for qa in qa_pairs)

    # Build source lookup
    source_map = {s["id"]: s["title"] for s in sources}

    # Format QA pairs for export (strip internal metadata)
    exported = []
    for qa in qa_pairs:
        exported.append({
            "id": qa["id"],
            "question": qa["question"],
            "question_type": qa.get("question_type", "direct"),
            "answer": qa["answer"],
            "answer_short": qa.get("answer_short", ""),
            "category": qa.get("category", ""),
            "tags": qa.get("tags", []),
            "urgency": qa.get("urgency", "medium"),
            "related": qa.get("related_questions", []),
        })

    return {
        "version": "0.2",
        "generated": datetime.now().isoformat(),
        "stats": {
            "total_qa_pairs": len(exported),
            "categories": dict(categories),
            "sources_used": len(set(
                su["source_id"]
                for qa in qa_pairs
                for su in (qa.get("sources_used") or [])
            )),
        },
        "qa_pairs": exported,
    }
