#!/usr/bin/env python3
"""Simple CLI tool to review pending knowledge cards."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PENDING_DIR = SCRIPT_DIR / "cards" / "pending"
APPROVED_DIR = SCRIPT_DIR / "cards" / "approved"


def display_card(card, index, total):
    """Pretty-print a card in the terminal."""
    width = min(shutil.get_terminal_size().columns, 80)
    sep = "─" * width

    print(f"\n{sep}")
    print(f"  Card {index} of {total} pending")
    print(sep)
    print(f"  {card.get('icon', '?')}  {card.get('title', 'Untitled')}")
    print(f"  Category: {card.get('category', '?')}  |  Difficulty: {card.get('difficulty', '?')}")
    print(f"  ID: {card.get('id', '?')}")
    print(f"  Brief: {card.get('brief', '')}")
    print()

    tags = card.get("tags", [])
    if tags:
        print(f"  Tags: {', '.join(tags)}")
        print()

    steps = card.get("steps", [])
    if steps:
        print("  STEPS:")
        for i, step in enumerate(steps, 1):
            # Wrap long steps
            print(f"    {i}. {step}")
        print()

    warnings = card.get("warnings", [])
    if warnings:
        print("  WARNINGS:")
        for w in warnings:
            print(f"    ⚠  {w}")
        print()

    source = card.get("source", "")
    if source:
        print(f"  Source: {source}")

    print(sep)


def edit_card(card_path):
    """Open the card in the user's editor."""
    editor = os.environ.get("EDITOR", "nano")
    try:
        subprocess.run([editor, str(card_path)])
        # Reload the card
        return json.loads(card_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  Error opening editor: {e}")
        return None


def main():
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)

    pending_files = sorted(PENDING_DIR.glob("*.json"))
    if not pending_files:
        print("No pending cards to review.")
        return

    total = len(pending_files)
    print(f"\n{total} card(s) pending review.\n")

    i = 0
    while i < len(pending_files):
        card_path = pending_files[i]

        try:
            card = json.loads(card_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  Error: Invalid JSON in {card_path.name}, skipping.")
            i += 1
            continue

        display_card(card, i + 1, total)

        while True:
            choice = input("\n  [a]pprove  [e]dit  [s]kip  [d]elete  [q]uit → ").strip().lower()

            if choice == "a":
                dest = APPROVED_DIR / card_path.name
                shutil.move(str(card_path), str(dest))
                print(f"  ✓ Approved → cards/approved/{card_path.name}")
                i += 1
                break

            elif choice == "e":
                updated = edit_card(card_path)
                if updated:
                    card = updated
                    display_card(card, i + 1, total)
                # Don't increment — show the card again for approve/skip/delete

            elif choice == "s":
                print("  → Skipped")
                i += 1
                break

            elif choice == "d":
                card_path.unlink()
                print(f"  ✗ Deleted {card_path.name}")
                i += 1
                break

            elif choice == "q":
                approved_count = len(list(APPROVED_DIR.glob("*.json")))
                remaining = len(list(PENDING_DIR.glob("*.json")))
                print(f"\n  Done. {approved_count} approved, {remaining} still pending.")
                return

            else:
                print("  Invalid choice. Use: a/e/s/d/q")

    approved_count = len(list(APPROVED_DIR.glob("*.json")))
    remaining = len(list(PENDING_DIR.glob("*.json")))
    print(f"\n  Review complete. {approved_count} approved, {remaining} still pending.")


if __name__ == "__main__":
    main()
