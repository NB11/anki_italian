#!/usr/bin/env python3
"""
Step 2: Generate Italian Anki card YAML files using the Mistral API.

Mistral handles BOTH example sentences (Italian) AND their German translations,
so no separate translation API is needed.

Usage (from repo root):
    python scripts/02_generate_cards.py

Reads:   data/wordlist.csv
Writes:  cards/XXXX_lemma.yml     (one per word)
         data/progress.json       (resume checkpoint)

Rate:    Defaults to 30 RPM (free tier safe).
         Set MISTRAL_RPM=60 in .env if needed.
"""

import csv
import json
import os
import re
import time
from pathlib import Path

import yaml
from mistralai.client import Mistral
from dotenv import load_dotenv

load_dotenv()

WORDLIST      = Path("data/wordlist.csv")
CARDS_DIR     = Path("cards")
PROGRESS_FILE = Path("data/progress.json")

_cfg      = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
RPM       = int(os.getenv("MISTRAL_RPM", str(_cfg.get("mistral_rpm", 30))))
DELAY     = 60.0 / RPM
MODEL     = _cfg.get("mistral_model", "mistral-small-latest")
N_SENTS   = int(_cfg.get("sentences_per_card", 3))
WORDLIMIT = _cfg.get("words_limit")   # None = all


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""\
You are an expert Italian language teacher creating Anki flashcards for German speakers.

For every Italian word I give you, respond with ONLY a single JSON object (no markdown fences,
no extra text). The object must have these keys:

"definition"  – Concise German translation, 2–6 words. Comma-separate synonyms.
                For nouns include the German article and plural marker, e.g. "der Hund, -e".
                For verbs use the infinitive, e.g. "essen, fressen".

"pos"         – One of: "n.m" (masculine noun), "n.f" (feminine noun), "n.f/m" (variable gender),
                "v" (verb), "vi" (intransitive verb), "vt" (transitive verb),
                "vr" (reflexive verb), "adj" (adjective), "adv" (adverb).

"article"     – Italian definite article for nouns: "il", "la", "l'", "lo", "i", "le", "gli".
                null for non-nouns.

"plural"      – Italian plural form for nouns (just the word, no article), null otherwise.

"sentences"   – Array of EXACTLY {N_SENTS} objects. Each has:
                "it": A natural Italian sentence using the word (or an inflected form).
                      Wrap the target word in *asterisks*, e.g. "Ho *mangiato* una pizza."
                "de": German translation of that sentence.
                      Wrap the corresponding German word in *asterisks*.

Across the {N_SENTS} sentences, cover a VARIETY of tenses and conjugations (e.g. presente,
passato prossimo, imperfetto, futuro, condizionale, congiuntivo) so that the learner sees
the word in many grammatical contexts. Also vary structure: statement, question, dialogue line, etc.
For non-verbs, vary the grammatical role (subject, object, prepositional phrase, etc.).
Sentences should be natural and appropriate for B1-B2 language learners.
"""


# ── YAML helpers ──────────────────────────────────────────────────────────────

def _yaml_str(value: str) -> str:
    """Return a YAML scalar representation, quoting only when necessary."""
    if not value and value != 0:
        return "''"
    s = str(value)
    needs_quote = (
        not s                                  or
        s[0] in ':,[]{}#&*?|<>=!%@`"\''       or
        ': ' in s                              or
        ' #' in s                              or
        s.lower() in
            {'true', 'false', 'null', 'yes', 'no', 'on', 'off', '~'}
    )
    if needs_quote:
        escaped = s.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _write_card(rank: int, lemma: str, data: dict) -> Path:
    CARDS_DIR.mkdir(exist_ok=True)

    article   = (data.get("article")  or "").strip()
    plural    = (data.get("plural")   or "").strip()
    # l' elides directly onto the noun (no space)
    if article.endswith("'"):
        wort_mit = f"{article}{lemma}"
    else:
        wort_mit = f"{article} {lemma}".strip() if article else lemma
    pos       = (data.get("pos")      or "").strip()
    defn      = (data.get("definition") or "").strip()

    pairs = []
    for s in (data.get("sentences") or []):
        it = (s.get("it") or "").strip()
        de = (s.get("de") or "").strip()
        if it and de:
            pairs.append(f"{it}\n{de}")
    beispiele = "\n\n".join(pairs)

    safe_lemma = re.sub(r"[^\w\-]", "_", lemma, flags=re.UNICODE)
    path = CARDS_DIR / f"{rank:04d}_{safe_lemma}.yml"

    lines = [
        f"Rang: {rank}",
        f"Wort: {_yaml_str(lemma)}",
        f"Wortart: {_yaml_str(pos)}",
        f"Wort mit Artikel: {_yaml_str(wort_mit)}",
        f"Femininum / Plural: {_yaml_str(plural)}",
        "IPA: ''",
        f"Definition: {_yaml_str(defn)}",
        "Register: ''",
    ]

    if beispiele:
        lines.append("Beispielsätze: |-")
        for sentence_line in beispiele.split("\n"):
            lines.append(f"  {sentence_line}")
    else:
        lines.append("Beispielsätze: ''")

    lines += [
        "Audio: ''",
        "Notiz: ''",
        "Dispersion: ''",
        "Konjugation: ''",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return path


# ── Progress ──────────────────────────────────────────────────────────────────

def _load_done() -> set[str]:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return set(json.load(f).get("done", []))
    return set()


def _save_done(done: set[str]) -> None:
    PROGRESS_FILE.parent.mkdir(exist_ok=True)
    existing: dict = {}
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            existing = json.load(f)
    existing["done"] = sorted(done)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(existing, f, ensure_ascii=False)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=WORDLIMIT,
                        help="Only process the first N words (default: words_limit from config.yaml)")
    parser.add_argument("--refill", action="store_true",
                        help="Re-generate even for already-processed words")
    args = parser.parse_args()

    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise SystemExit("MISTRAL_API_KEY not set in .env")
    if not WORDLIST.exists():
        raise SystemExit(f"Word list not found: {WORDLIST}  ->  run 01_extract_wordlist.py first")

    client = Mistral(api_key=api_key)

    with open(WORDLIST, encoding="utf-8") as f:
        words = list(csv.DictReader(f))

    if args.limit:
        words = words[:args.limit]

    done = _load_done()
    todo = [w for w in words if w["lemma"] not in done or args.refill]
    print(f"Words: {len(words):,}  |  Done: {len(done):,}  |  Remaining: {len(todo):,}")
    print(f"Rate: {RPM} RPM  ({DELAY:.1f}s delay)  est. {len(todo) * DELAY / 3600:.1f}h\n")

    errors: list[str] = []

    for i, row in enumerate(todo):
        rank  = int(row["rank"])
        lemma = row["lemma"]
        pos   = row["pos"]

        print(f"[{rank:4d}/{len(words)}] {lemma:<22} ({pos})", end="  ", flush=True)

        try:
            response = client.chat.complete(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f'Word: "{lemma}" (POS hint: {pos})'},
                ],
                response_format={"type": "json_object"},
                temperature=0.8,
            )
            data = json.loads(response.choices[0].message.content)
        except Exception as exc:
            print(f"ERROR: {exc}")
            errors.append(f"{rank} {lemma}: {exc}")
            time.sleep(DELAY)
            continue

        path = _write_card(rank, lemma, data)
        done.add(lemma)
        print(f"-> {path.name}")

        if (i + 1) % 20 == 0:
            _save_done(done)

        time.sleep(DELAY)

    _save_done(done)
    card_count = len(list(CARDS_DIR.glob("*.yml")))
    print(f"\nFinished.  {card_count:,} cards in {CARDS_DIR}/")
    if errors:
        print(f"\n{len(errors)} errors (re-run to retry):")
        for e in errors[:10]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
