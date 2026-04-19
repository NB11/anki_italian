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

import collections
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

RECENT_WINDOW = 50  # number of previous words to pass as context


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
                "it": A natural Italian sentence using the target word (or an inflected form).
                      Wrap ONLY the target word in *asterisks*, e.g. "Ho *mangiato* una pizza."
                      Never wrap any other word in asterisks.
                "de": German translation of that sentence.
                      Wrap ONLY the single German word/phrase that translates the target word
                      in *asterisks*. Never wrap anything else.

Sentence guidelines:
- Across the {N_SENTS} sentences, cover a VARIETY of tenses (presente, passato prossimo,
  imperfetto, futuro, condizionale, congiuntivo) and structures (statement, question,
  dialogue line, subordinate clause, relative clause).
- Aim for B1-B2 complexity: use subordinate clauses, relative pronouns, conjunctions.
  Avoid simple subject-verb-object sentences where possible.
- If a list of "recently learned words" is provided, you MAY incorporate 1–2 of them
  into a sentence, but ONLY if they fit so naturally that a native speaker would use them
  there. A sentence that makes perfect sense without them is always better than one that
  forces them in awkwardly. Quality and naturalness come first.
- These context words must ALWAYS appear as plain text — NEVER in asterisks.
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
        ':' in s                               or
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

    raw_article = data.get("article")
    raw_plural  = data.get("plural")
    article = (raw_article if isinstance(raw_article, str) else "").strip()
    plural  = (raw_plural  if isinstance(raw_plural,  str) else "").strip()
    # l' elides directly onto the noun (no space)
    if article.endswith("'"):
        wort_mit = f"{article}{lemma}"
    else:
        wort_mit = f"{article} {lemma}".strip() if article else lemma
    pos       = (data.get("pos")      or "").strip()
    defn      = (data.get("definition") or "").strip()

    pairs = []
    for s in (data.get("sentences") or []):
        if not isinstance(s, dict):
            continue
        it = _strip_extra_asterisks((s.get("it") or "").strip(), lemma)
        de = _strip_extra_asterisks((s.get("de") or "").strip(), lemma)
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

def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_progress(done: set[str], recent: list[tuple[str, str]]) -> None:
    PROGRESS_FILE.parent.mkdir(exist_ok=True)
    existing = _load_progress()
    existing["done"]   = sorted(done)
    existing["recent"] = [[lemma, defn] for lemma, defn in recent]
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)


def _strip_extra_asterisks(sentence: str, lemma: str) -> str:
    """Remove all *word* markers except the one covering the target lemma."""
    marked = re.findall(r'\*([^*]+)\*', sentence)
    if len(marked) <= 1:
        return sentence
    # Keep only the first marked token that contains (part of) the lemma root,
    # or just the first marked token if none match.
    lemma_root = lemma[:4].lower()
    target = next(
        (m for m in marked if lemma_root in m.lower()),
        marked[0]
    )
    # Remove all asterisk pairs, then re-add only around the chosen token
    cleaned = re.sub(r'\*([^*]+)\*', r'\1', sentence)
    # Re-mark only the first occurrence of the target token
    cleaned = cleaned.replace(target, f'*{target}*', 1)
    return cleaned


def _build_user_message(lemma: str, pos: str, recent: collections.deque) -> str:
    msg = f'Word: "{lemma}" (POS hint: {pos})\n'
    msg += f'RULE: in every sentence, wrap ONLY "{lemma}" (or its inflected form) in *asterisks*. No other word may be wrapped in asterisks.'
    if recent:
        vocab = ", ".join(f"{w} ({d})" for w, d in recent)
        msg += f'\n\nOptional vocabulary (use 1–2 as plain text ONLY if they fit naturally — skip otherwise): {vocab}'
    return msg


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

    progress   = _load_progress()
    done       = set(progress.get("done", []))
    # Pre-fill recent window from saved progress so resume works correctly
    recent: collections.deque = collections.deque(
        ((r[0], r[1]) for r in progress.get("recent", [])),
        maxlen=RECENT_WINDOW,
    )

    todo = [w for w in words if w["lemma"] not in done or args.refill]
    print(f"Words: {len(words):,}  |  Done: {len(done):,}  |  Remaining: {len(todo):,}")
    print(f"Rate: {RPM} RPM  ({DELAY:.1f}s delay)  est. {len(todo) * DELAY / 3600:.1f}h\n")

    errors: list[str] = []

    for i, row in enumerate(todo):
        rank  = int(row["rank"])
        lemma = row["lemma"]
        pos   = row["pos"]

        print(f"[{rank:4d}/{len(words)}] {lemma:<22} ({pos})", end="  ", flush=True)

        user_msg = _build_user_message(lemma, pos, recent)

        try:
            response = client.chat.complete(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
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
        defn = (data.get("definition") or "").strip()

        done.add(lemma)
        recent.append((lemma, defn))
        print(f"-> {path.name}")

        if (i + 1) % 20 == 0:
            _save_progress(done, list(recent))

        time.sleep(DELAY)

    _save_progress(done, list(recent))
    card_count = len(list(CARDS_DIR.glob("*.yml")))
    print(f"\nFinished.  {card_count:,} cards in {CARDS_DIR}/")
    if errors:
        print(f"\n{len(errors)} errors (re-run to retry):")
        for e in errors[:10]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
