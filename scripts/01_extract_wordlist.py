#!/usr/bin/env python3
"""
Step 1: Extract the top 5000 Italian content words from the SUBTLEX-IT corpus.

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

INPUT_FILE  = Path("italian/subtlex-it.csv")
OUTPUT_FILE = Path("data/wordlist.csv")

CONTENT_POS = {"NOM", "VER", "ADJ", "ADV"}

_cfg  = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
TOP_N = int(_cfg.get("words_total", 5000))

POS_LABEL = {
    "NOM": "n",
    "VER": "v",
    "ADJ": "adj",
    "ADV": "adv",
}

# SUBTLEX-IT POS codes to skip explicitly (belt-and-suspenders on top of the
# CONTENT_POS whitelist, useful for debugging the filter output)
SKIP_POS = {"PRE", "DET", "PRO", "CON", "AUX", "NUM", "PON", "SENT", "INT", "ABR"}


def is_valid_lemma(lemma: str) -> bool:
    if not lemma or lemma == "<unknown>":
        return False
    # Compound lemmas produced by ambiguous tokenisation, e.g. "essere|sonare"
    if "|" in lemma:
        return False
    if len(lemma) < 2:
        return False
    # No digits inside the lemma
    if re.search(r"\d", lemma):
        return False
    # Must start with a Unicode letter (covers accented Italian chars)
    if not re.match(r"^[A-Za-zÀ-öø-ÿ]", lemma):
        return False
    return True


def main() -> None:
    if not INPUT_FILE.exists():
        raise SystemExit(f"Corpus not found: {INPUT_FILE}")

    OUTPUT_FILE.parent.mkdir(exist_ok=True)

    seen:  set[str] = set()
    words: list[dict] = []

    with open(INPUT_FILE, encoding="latin-1") as f:
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
            words.append({"lemma": lemma, "pos": POS_LABEL[pos], "freq": freq_int})

    words.sort(key=lambda x: -x["freq"])
    top = words[:TOP_N]

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "lemma", "pos", "freq"])
        writer.writeheader()
        for i, word in enumerate(top, 1):
            writer.writerow({"rank": i, **word})

    pos_dist = Counter(w["pos"] for w in top)
    print(f"Wrote {len(top):,} words -> {OUTPUT_FILE}")
    print(f"Total unique content lemmas in corpus: {len(words):,}")
    print("POS distribution in top 5000:")
    for pos, count in sorted(pos_dist.items(), key=lambda x: -x[1]):
        print(f"  {pos:<5} {count:>5}")
    print(f"\nSample top 20:")
    for i, w in enumerate(top[:20], 1):
        print(f"  [{i:4d}] {w['lemma']:<20} {w['pos']:<5}  freq={w['freq']:,}")


if __name__ == "__main__":
    main()
