#!/usr/bin/env python3
"""Compile approved knowledge cards into the app's JS database in index.html."""

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
APPROVED_DIR = SCRIPT_DIR / "cards" / "approved"
INDEX_PATH = SCRIPT_DIR / "index.html"


def load_approved_cards():
    """Load all approved card JSON files."""
    cards = {}
    if not APPROVED_DIR.exists():
        return cards

    for f in sorted(APPROVED_DIR.glob("*.json")):
        try:
            card = json.loads(f.read_text(encoding="utf-8"))
            card_id = card.get("id", f.stem)
            cards[card_id] = card
        except json.JSONDecodeError:
            print(f"Warning: Invalid JSON in {f.name}, skipping.")
    return cards


def js_to_json(text):
    """Convert JS object notation to valid JSON (quote unquoted keys, handle trailing commas, comments)."""
    # Remove single-line JS comments (// ...)
    text = re.sub(r'//[^\n]*', '', text)
    # Quote unquoted property keys: word characters followed by :
    text = re.sub(r'(?<=[{,\n])\s*(\w+)\s*:', r' "\1":', text)
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    return text


def extract_existing_cards(html):
    """Extract existing cards from the CARDS array in index.html."""
    # Match: const CARDS = [ ... ];
    pattern = r'const CARDS = \[(.*?)\];'
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        print("Error: Could not find 'const CARDS = [...]' in index.html")
        sys.exit(1)

    array_content = match.group(1).strip()
    if not array_content:
        return {}

    # Try parsing directly first (works if cards were written by build.py as JSON)
    try:
        cards_list = json.loads("[" + array_content + "]")
    except json.JSONDecodeError:
        # Convert JS syntax to JSON
        try:
            fixed = js_to_json(array_content)
            cards_list = json.loads("[" + fixed + "]")
        except json.JSONDecodeError as e:
            print(f"Warning: Could not parse existing cards from index.html: {e}")
            print("Existing cards will not be preserved. Continue? [y/N]")
            if input().strip().lower() != "y":
                sys.exit(1)
            return {}

    cards = {}
    for card in cards_list:
        card_id = card.get("id", "")
        if card_id:
            cards[card_id] = card
    return cards


def format_card_js(card):
    """Format a card as a JS object string."""
    return json.dumps(card, indent=2, ensure_ascii=False)


def build():
    """Compile all cards and inject into index.html."""
    if not INDEX_PATH.exists():
        print(f"Error: {INDEX_PATH} not found.")
        sys.exit(1)

    html = INDEX_PATH.read_text(encoding="utf-8")

    # Load existing cards from index.html
    existing = extract_existing_cards(html)
    existing_count = len(existing)

    # Load approved cards
    approved = load_approved_cards()
    approved_count = len(approved)

    if approved_count == 0 and existing_count == 0:
        print("No cards found (none in index.html, none in cards/approved/).")
        return

    # Merge: approved wins on conflicts
    merged = {**existing, **approved}
    duplicates = len(existing) + len(approved) - len(merged)

    # Sort by category, then title
    sorted_cards = sorted(merged.values(), key=lambda c: (c.get("category", ""), c.get("title", "")))

    # Build the JS array
    cards_js = ",\n  ".join(format_card_js(card) for card in sorted_cards)
    new_cards_block = f"const CARDS = [\n  {cards_js}\n];"

    # Replace in HTML
    pattern = r'const CARDS = \[.*?\];'
    new_html = re.sub(pattern, new_cards_block, html, count=1, flags=re.DOTALL)

    # Update card count in offline badge
    total = len(sorted_cards)
    new_html = re.sub(
        r'Works offline · \d+ cards loaded',
        f'Works offline · {total} cards loaded',
        new_html
    )

    # Write
    INDEX_PATH.write_text(new_html, encoding="utf-8")

    new_count = approved_count - duplicates
    print(f"Built {total} cards into index.html ({existing_count} existing + {new_count} new, {duplicates} duplicates merged)")


if __name__ == "__main__":
    build()
    # Also regenerate embeddings
    import subprocess
    print()
    subprocess.run([sys.executable, str(SCRIPT_DIR / "embed.py")])
