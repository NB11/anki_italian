#!/usr/bin/env python3
"""
Dry-run: compare the new combined wordlist against existing cards.

Shows what would be added / removed / kept if you regenerated the wordlist,
without writing anything.

Usage:
    python scripts/compare_wordlists.py
"""

import csv
import re
from pathlib import Path

import yaml

SUBTLEX_FILE = Path("italian/subtlex-it.csv")
NEWS_FILE    = Path("data/ita_news_2024_10K-words.txt")
CARDS_DIR    = Path("cards")

_cfg  = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
TOP_N = int(_cfg.get("words_total", 5000))

CONTENT_POS = {"NOM", "VER", "ADJ", "ADV"}
POS_LABEL   = {"NOM": "n", "VER": "v", "ADJ": "adj", "ADV": "adv"}


def is_valid_lemma(lemma: str) -> bool:
    if not lemma or lemma == "<unknown>" or "|" in lemma or len(lemma) < 2:
        return False
    if re.search(r"\d", lemma):
        return False
    if not re.match(r"^[A-Za-zÀ-öø-ÿ]", lemma):
        return False
    return True


def load_new_wordlist() -> list[str]:
    news_freqs: dict[str, int] = {}
    if NEWS_FILE.exists():
        with open(NEWS_FILE, encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 3:
                    continue
                word = parts[1].strip().lower()
                try:
                    freq = int(parts[2].strip())
                except ValueError:
                    continue
                if word and re.match(r"^[a-zA-ZÀ-öø-ÿ]", word):
                    news_freqs[word] = news_freqs.get(word, 0) + freq

    seen: set[str] = set()
    words: list[dict] = []
    with open(SUBTLEX_FILE, encoding="latin-1") as f:
        for row in csv.DictReader(f, delimiter=";"):
            pos   = row.get("dom_pos",       "").strip()
            lemma = row.get("dom_lemma",      "").strip()
            freq  = row.get("dom_lemma_freq", "0") or "0"
            if pos not in CONTENT_POS or not is_valid_lemma(lemma) or lemma in seen:
                continue
            try:
                subtlex = int(freq)
            except ValueError:
                subtlex = 0
            seen.add(lemma)
            news = news_freqs.get(lemma.lower(), 0)
            mx_s = 1; mx_n = 1  # will normalise after collecting all
            words.append({"lemma": lemma, "subtlex": subtlex, "news": news})

    mx_s = max(w["subtlex"] for w in words) or 1
    mx_n = max(w["news"]    for w in words) or 1
    for w in words:
        w["score"] = 0.5 * (w["subtlex"] / mx_s) + 0.5 * (w["news"] / mx_n)

    words.sort(key=lambda x: -x["score"])
    return [w["lemma"] for w in words[:TOP_N]]


def load_existing_lemmas() -> set[str]:
    lemmas: set[str] = set()
    for path in CARDS_DIR.glob("*.yml"):
        try:
            card = yaml.safe_load(path.read_text(encoding="utf-8"))
            if card and card.get("Wort"):
                lemmas.add(card["Wort"])
        except Exception:
            pass
    return lemmas


def main() -> None:
    print("Loading new combined wordlist …")
    new_list   = load_new_wordlist()
    new_set    = set(new_list)

    print("Reading existing cards …")
    existing   = load_existing_lemmas()

    to_add     = [w for w in new_list if w not in existing]
    to_remove  = existing - new_set
    to_keep    = existing & new_set

    print(f"\n{'='*50}")
    print(f"  New wordlist size   : {len(new_list):,}")
    print(f"  Existing cards      : {len(existing):,}")
    print(f"{'='*50}")
    print(f"  KEEP  (no change)   : {len(to_keep):,}")
    print(f"  ADD   (new cards)   : {len(to_add):,}")
    print(f"  REMOVE (drop cards) : {len(to_remove):,}")
    print(f"{'='*50}")

    if to_add:
        print(f"\nFirst 20 words to ADD:")
        for w in to_add[:20]:
            print(f"  + {w}")

    if to_remove:
        print(f"\nFirst 20 words to REMOVE:")
        for w in sorted(to_remove)[:20]:
            print(f"  - {w}")

    print("\nThis is a dry run — nothing was changed.")


if __name__ == "__main__":
    main()
