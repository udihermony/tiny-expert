#!/usr/bin/env python3
"""Extract structured survival knowledge cards from source text using Claude API."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SOURCES_DIR = SCRIPT_DIR / "sources"
PENDING_DIR = SCRIPT_DIR / "cards" / "pending"
APPROVED_DIR = SCRIPT_DIR / "cards" / "approved"

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 8096

SYSTEM_PROMPT = """You are a survival knowledge extraction system. Your job is to read source material and extract discrete, actionable knowledge cards.

Each card should cover ONE specific skill or procedure. Do not combine multiple topics into one card.

Extract cards as a JSON array. Each card must follow this exact schema:

{
  "id": "category-short-descriptor" (lowercase, hyphens, unique),
  "title": "Clear, Specific Title",
  "icon": "(emoji matching the category)",
  "category": "(one of: water, fire, shelter, first-aid, food, navigation, rescue, tools, climate, psychology)",
  "brief": "One sentence explaining what this card teaches.",
  "tags": ["relevant", "context", "tags"],
  "difficulty": "easy|medium|hard",
  "steps": [
    "Step 1: Clear, actionable instruction.",
    "Step 2: Each step should be one concrete action.",
    "Step 3: Include specific measurements, times, distances where available."
  ],
  "warnings": [
    "Critical safety warnings. Things that could cause harm if done wrong."
  ],
  "source": "Book/Manual Title — Author (Chapter/Section if available)"
}

Rules:
- Each card must be SELF-CONTAINED. Someone reading just this card should be able to act on it.
- Steps must be concrete and actionable, not vague. "Build a shelter" is bad. "Lean sticks at 45° angles along both sides of the ridgepole, spaced 6-8 inches apart" is good.
- Include specific numbers: temperatures, times, distances, quantities.
- Warnings should cover what could go WRONG or what NOT to do. These are critical for safety.
- If the source material contains common myths or dangerous misconceptions, create a card that addresses and corrects them.
- Do not invent information not present in the source material.
- Difficulty: easy = can be done by anyone with no practice, medium = requires some skill or specific conditions, hard = requires practice or specialized knowledge.
- Tags should describe context: when/where this applies (desert, forest, cold-weather, tropical, no-tools, etc.)
- Generate between 3-15 cards per chunk depending on how much extractable content there is.
- If the source material is too general, narrative, or doesn't contain actionable survival knowledge, return an empty array [].

Respond with ONLY the JSON array, no other text."""


def count_words(text):
    return len(text.split())


def chunk_text(text, max_words=6000, overlap=500):
    """Split text into chunks, preferring section boundaries."""
    if count_words(text) <= 8000:
        return [text]

    # Try splitting on section boundaries
    section_patterns = [
        r'\n#{1,3}\s+',           # Markdown headers
        r'\n[A-Z][A-Z\s]{4,}\n',  # ALL CAPS lines
        r'\n\n\n+',               # Triple+ newlines
    ]

    sections = None
    for pattern in section_patterns:
        parts = re.split(pattern, text)
        if len(parts) > 1:
            sections = parts
            break

    if sections and len(sections) > 1:
        chunks = []
        current = ""
        for section in sections:
            if count_words(current + section) > max_words and current:
                chunks.append(current)
                # Overlap: take last ~overlap words from current chunk
                words = current.split()
                current = " ".join(words[-overlap:]) + "\n\n" + section if len(words) > overlap else section
            else:
                current += "\n\n" + section if current else section
        if current.strip():
            chunks.append(current)
        return chunks

    # Fallback: split by word count
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk_words = words[i:i + max_words]
        chunks.append(" ".join(chunk_words))
        i += max_words - overlap
    return chunks


def existing_ids():
    """Get all card IDs already in pending or approved."""
    ids = set()
    for d in [PENDING_DIR, APPROVED_DIR]:
        if d.exists():
            for f in d.glob("*.json"):
                ids.add(f.stem)
    return ids


def unique_id(card_id, used_ids):
    """Ensure ID is unique by appending a number if needed."""
    if card_id not in used_ids:
        used_ids.add(card_id)
        return card_id
    n = 2
    while f"{card_id}-{n}" in used_ids:
        n += 1
    new_id = f"{card_id}-{n}"
    used_ids.add(new_id)
    return new_id


def parse_json_response(text):
    """Parse JSON from Claude's response, stripping markdown fences if present."""
    text = text.strip()
    # Strip markdown code blocks
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
    return json.loads(text)


def extract_cards(source_path, dry_run=False):
    """Extract cards from a source file."""
    source_path = Path(source_path)
    if not source_path.exists():
        print(f"Error: File not found: {source_path}")
        sys.exit(1)

    text = source_path.read_text(encoding="utf-8")
    filename = source_path.name

    if not text.strip():
        print(f"Error: File is empty: {source_path}")
        sys.exit(1)

    chunks = chunk_text(text)
    print(f"Processing {filename} ({count_words(text)} words, {len(chunks)} chunk{'s' if len(chunks) != 1 else ''})")

    if dry_run:
        for i, chunk in enumerate(chunks):
            print(f"\n--- Chunk {i+1} ({count_words(chunk)} words) ---")
            print(chunk[:500] + ("..." if len(chunk) > 500 else ""))
        print(f"\nDry run: would send {len(chunks)} API call(s) for {filename}")
        return

    # Check API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        print("Set it with: export ANTHROPIC_API_KEY=sk-...")
        sys.exit(1)

    from anthropic import Anthropic
    client = Anthropic()

    used_ids = existing_ids()
    total_cards = 0

    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            print(f"  Chunk {i+1}/{len(chunks)}...", end=" ", flush=True)

        user_prompt = f"Extract survival knowledge cards from the following source material:\n\nSOURCE: {filename}\n---\n{chunk}\n---\n\nExtract all actionable survival knowledge as structured cards."

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            response_text = response.content[0].text
            cards = parse_json_response(response_text)

            if not isinstance(cards, list):
                print(f"Warning: API returned non-array response, skipping chunk {i+1}")
                continue

            for card in cards:
                card_id = unique_id(card.get("id", f"unknown-{total_cards}"), used_ids)
                card["id"] = card_id

                card_path = PENDING_DIR / f"{card_id}.json"
                card_path.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
                total_cards += 1

            if len(chunks) > 1:
                print(f"{len(cards)} cards")

        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse JSON from API response for chunk {i+1}: {e}")
            continue
        except Exception as e:
            print(f"Error calling API for chunk {i+1}: {e}")
            sys.exit(1)

    print(f"\nExtracted {total_cards} cards from {filename} → cards/pending/")


def main():
    parser = argparse.ArgumentParser(description="Extract survival knowledge cards from source text.")
    parser.add_argument("source", nargs="?", help="Path to source text file")
    parser.add_argument("--all", action="store_true", help="Process all files in sources/")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent without calling the API")
    args = parser.parse_args()

    if not args.source and not args.all:
        parser.print_help()
        sys.exit(1)

    if args.all:
        source_files = sorted(SOURCES_DIR.glob("*"))
        source_files = [f for f in source_files if f.is_file() and f.suffix in (".txt", ".md", ".text")]
        if not source_files:
            print(f"No source files found in {SOURCES_DIR}/")
            sys.exit(1)
        print(f"Found {len(source_files)} source file(s)\n")
        for sf in source_files:
            extract_cards(sf, dry_run=args.dry_run)
            print()
    else:
        extract_cards(args.source, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
