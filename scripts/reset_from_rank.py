#!/usr/bin/env python3
"""
Utility: reset generation from a given rank onward.

Deletes card files for rank >= FROM_RANK, removes those lemmas from
progress.json, and pre-fills the recent-word window from the 50 cards
immediately before FROM_RANK so context is warm on resume.

Usage:
    python scripts/reset_from_rank.py 500
"""

import json
import sys
from pathlib import Path

import yaml

CARDS_DIR     = Path("cards")
PROGRESS_FILE = Path("data/progress.json")
RECENT_WINDOW = 50


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/reset_from_rank.py <from_rank>")

    from_rank = int(sys.argv[1])

    # ── Load existing progress ────────────────────────────────────────────────
    progress: dict = {}
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, encoding="utf-8", errors="ignore") as f:
                progress = json.load(f)
        except Exception:
            print("Warning: progress.json unreadable, rebuilding from card files")
            progress = {}

    done: set[str] = set(progress.get("done", []))
    if not done:
        # Rebuild done set from existing card files
        for path in CARDS_DIR.glob("*.yml"):
            try:
                card = yaml.safe_load(path.read_text(encoding="utf-8"))
                if card and card.get("Wort"):
                    done.add(card["Wort"])
            except Exception:
                pass
        print(f"Rebuilt done set from {len(done)} existing card files")

    # ── Find all card files and split at from_rank ────────────────────────────
    keep_cards: list[tuple[int, Path]] = []
    delete_cards: list[tuple[int, Path]] = []

    for path in sorted(CARDS_DIR.glob("*.yml")):
        try:
            rank = int(path.stem.split("_")[0])
        except ValueError:
            continue
        if rank >= from_rank:
            delete_cards.append((rank, path))
        else:
            keep_cards.append((rank, path))

    # ── Delete cards >= from_rank and remove from done set ───────────────────
    removed_lemmas: set[str] = set()
    for rank, path in delete_cards:
        try:
            card = yaml.safe_load(path.read_text(encoding="utf-8"))
            if card and card.get("Wort"):
                removed_lemmas.add(card["Wort"])
        except Exception:
            pass
        path.unlink()

    done -= removed_lemmas
    print(f"Deleted {len(delete_cards)} cards (rank >= {from_rank})")
    print(f"Removed {len(removed_lemmas)} lemmas from done set")

    # ── Pre-fill recent window from the 50 cards before from_rank ────────────
    recent_cards = sorted(keep_cards, key=lambda x: x[0])[-RECENT_WINDOW:]
    recent: list[list[str]] = []
    for _, path in recent_cards:
        try:
            card = yaml.safe_load(path.read_text(encoding="utf-8"))
            if card and card.get("Wort") and card.get("Definition"):
                recent.append([card["Wort"], card["Definition"]])
        except Exception:
            pass

    print(f"Pre-filled recent window with {len(recent)} words (ranks {recent_cards[0][0]}–{recent_cards[-1][0]})")

    # ── Save updated progress ─────────────────────────────────────────────────
    progress["done"]   = sorted(done)
    progress["recent"] = recent
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False)

    print(f"\nReady. Run: python scripts/run_pipeline.py --from 2")


if __name__ == "__main__":
    main()
