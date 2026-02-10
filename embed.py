#!/usr/bin/env python3
"""Generate card embeddings using all-MiniLM-L6-v2 for semantic search."""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
APPROVED_DIR = SCRIPT_DIR / "cards" / "approved"
INDEX_PATH = SCRIPT_DIR / "index.html"
OUTPUT_PATH = SCRIPT_DIR / "embeddings.json"

MODEL_NAME = "all-MiniLM-L6-v2"


def load_all_cards():
    """Load cards from approved/ and from index.html."""
    import re

    cards = {}

    # From approved/
    if APPROVED_DIR.exists():
        for f in APPROVED_DIR.glob("*.json"):
            try:
                card = json.loads(f.read_text(encoding="utf-8"))
                cards[card["id"]] = card
            except (json.JSONDecodeError, KeyError):
                pass

    # From index.html
    if INDEX_PATH.exists():
        html = INDEX_PATH.read_text(encoding="utf-8")
        match = re.search(r'const CARDS = \[(.*?)\];', html, re.DOTALL)
        if match:
            try:
                card_list = json.loads("[" + match.group(1) + "]")
                for card in card_list:
                    cid = card.get("id", "")
                    if cid and cid not in cards:
                        cards[cid] = card
            except json.JSONDecodeError:
                pass

    return cards


def card_to_text(card):
    """Build embedding text: title + brief + tags."""
    parts = [card.get("title", ""), card.get("brief", "")]
    tags = card.get("tags", [])
    if tags:
        parts.append("Tags: " + ", ".join(tags))
    return ". ".join(p for p in parts if p)


def main():
    cards = load_all_cards()
    if not cards:
        print("No cards found.")
        sys.exit(1)

    print(f"Embedding {len(cards)} cards with {MODEL_NAME}...")

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME)

    texts = {}
    for cid, card in sorted(cards.items()):
        texts[cid] = card_to_text(card)

    ids = list(texts.keys())
    sentences = [texts[cid] for cid in ids]

    embeddings = model.encode(sentences, show_progress_bar=True)

    result = {
        "model": MODEL_NAME,
        "dimensions": embeddings.shape[1],
        "cards": {}
    }

    for i, cid in enumerate(ids):
        result["cards"][cid] = [round(float(v), 5) for v in embeddings[i]]

    OUTPUT_PATH.write_text(json.dumps(result), encoding="utf-8")

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"Generated embeddings for {len(ids)} cards (embeddings.json, {size_kb:.0f}KB)")


if __name__ == "__main__":
    main()
