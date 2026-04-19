#!/usr/bin/env python3
"""
Step 1: Extract the top 5000 Italian content words from combined corpora.

Sources:
  - SUBTLEX-IT (movie/TV subtitles) — provides lemmas + POS tags
  - ita_news_2024_10K-words.txt     — news corpus, boosts frequency score

Each lemma's final score = 0.5 * norm(subtlex_freq) + 0.5 * norm(news_freq).
This balances spoken/informal vocabulary (subtitles) with formal/written (news).

Usage (from repo root):
    python scripts/01_extract_wordlist.py

Output:
    data/wordlist.csv   columns: rank, lemma, pos, freq
"""

import csv
import re
from collections import Counter
from pathlib import Path

import yaml

SUBTLEX_FILE = Path("italian/subtlex-it.csv")
NEWS_FILE    = Path("data/ita_news_2024_10K-words.txt")
OUTPUT_FILE  = Path("data/wordlist.csv")

CONTENT_POS = {"NOM", "VER", "ADJ", "ADV"}

_cfg  = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
TOP_N = int(_cfg.get("words_total", 5000))

POS_LABEL = {
    "NOM": "n",
    "VER": "v",
    "ADJ": "adj",
    "ADV": "adv",
}

SKIP_POS = {"PRE", "DET", "PRO", "CON", "AUX", "NUM", "PON", "SENT", "INT", "ABR"}


def is_valid_lemma(lemma: str) -> bool:
    if not lemma or lemma == "<unknown>":
        return False
    if "|" in lemma:
        return False
    if len(lemma) < 2:
        return False
    if re.search(r"\d", lemma):
        return False
    if not re.match(r"^[A-Za-zÀ-öø-ÿ]", lemma):
        return False
    return True


def _load_news_freqs() -> dict[str, int]:
    """Load news corpus into {word_lowercase: frequency} dict."""
    freqs: dict[str, int] = {}
    if not NEWS_FILE.exists():
        print(f"  Note: news corpus not found at {NEWS_FILE}, skipping")
        return freqs
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
                freqs[word] = freqs.get(word, 0) + freq
    return freqs


def _normalize(values: list[float]) -> list[float]:
    """Scale values to [0, 1]."""
    mx = max(values) if values else 1
    return [v / mx for v in values]


def main() -> None:
    if not SUBTLEX_FILE.exists():
        raise SystemExit(f"Corpus not found: {SUBTLEX_FILE}")

    OUTPUT_FILE.parent.mkdir(exist_ok=True)

    # ── Load news corpus ──────────────────────────────────────────────────────
    news_freqs = _load_news_freqs()
    print(f"News corpus loaded: {len(news_freqs):,} unique words")

    # ── Load SUBTLEX-IT ───────────────────────────────────────────────────────
    seen:  set[str] = set()
    words: list[dict] = []

    with open(SUBTLEX_FILE, encoding="latin-1") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            pos   = row.get("dom_pos",       "").strip()
            lemma = row.get("dom_lemma",      "").strip()
            freq  = row.get("dom_lemma_freq", "0") or "0"

            if pos not in CONTENT_POS:
                continue
            if not is_valid_lemma(lemma):
                continue
            if lemma in seen:
                continue

            try:
                freq_int = int(freq)
            except ValueError:
                freq_int = 0

            seen.add(lemma)
            words.append({
                "lemma":      lemma,
                "pos":        POS_LABEL[pos],
                "subtlex":    freq_int,
                "news":       news_freqs.get(lemma.lower(), 0),
            })

    print(f"SUBTLEX-IT loaded: {len(words):,} unique content lemmas")

    # ── Combine scores ────────────────────────────────────────────────────────
    subtlex_norm = _normalize([w["subtlex"] for w in words])
    news_norm    = _normalize([w["news"]    for w in words])

    for w, sn, nn in zip(words, subtlex_norm, news_norm):
        w["score"] = 0.5 * sn + 0.5 * nn

    words.sort(key=lambda x: -x["score"])
    top = words[:TOP_N]

    # ── Write output ──────────────────────────────────────────────────────────
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "lemma", "pos", "freq"])
        writer.writeheader()
        for i, word in enumerate(top, 1):
            writer.writerow({
                "rank":  i,
                "lemma": word["lemma"],
                "pos":   word["pos"],
                "freq":  word["subtlex"],
            })

    pos_dist = Counter(w["pos"] for w in top)
    news_hits = sum(1 for w in top if w["news"] > 0)
    print(f"\nWrote {len(top):,} words -> {OUTPUT_FILE}")
    print(f"Words present in news corpus: {news_hits:,} / {len(top):,}")
    print("POS distribution:")
    for pos, count in sorted(pos_dist.items(), key=lambda x: -x[1]):
        print(f"  {pos:<5} {count:>5}")
    print(f"\nSample top 20:")
    for i, w in enumerate(top[:20], 1):
        print(f"  [{i:4d}] {w['lemma']:<20} {w['pos']:<5}  subtlex={w['subtlex']:,}  news={w['news']:,}")


if __name__ == "__main__":
    main()
