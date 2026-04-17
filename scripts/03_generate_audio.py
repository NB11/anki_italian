#!/usr/bin/env python3
"""
Step 3: Generate TTS audio for each card's Italian example sentences.

Uses the Google Cloud TTS REST API with an API key (same key the card template
uses for live playback). Standard voices are free up to 4 M chars/month, which
covers all 1.5 M chars at zero cost.

Audio files are named:  {rank:04d}_s{1|2|3}.mp3
The deck builder (script 04) passes these filenames to the card template via
back.js, which resolves them from Anki's media collection.

Usage (from repo root):
    python scripts/03_generate_audio.py

Reads:   cards/*.yml
Writes:  audio/{rank:04d}_s{n}.mp3
         data/progress.json  (audio_done section, resume support)

Env vars:
    GOOGLE_TTS_API_KEY   – Google Cloud TTS API key (required)
    TTS_VOICE            – Voice name (default: it-IT-Standard-A)
"""

import json
import os
import re
import time
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

CARDS_DIR     = Path("cards")
AUDIO_DIR     = Path("audio")
PROGRESS_FILE = Path("data/progress.json")

_cfg       = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
VOICE_NAME = os.getenv("TTS_VOICE", _cfg.get("tts_voice", "it-IT-Standard-A"))

TTS_URL  = "https://texttospeech.googleapis.com/v1/text:synthesize"
LANGUAGE = "it-IT"

# Google TTS Standard voices have generous rate limits; 0.1s is ample
DELAY = 0.15


# ── Sentence extraction ───────────────────────────────────────────────────────

def _strip_markup(text: str) -> str:
    """Remove *asterisks* and HTML tags for clean TTS input."""
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _extract_italian_sentences(beispielsaetze: str) -> list[str]:
    """Return list of Italian sentences (first line of each pair)."""
    if not beispielsaetze:
        return []
    pairs = beispielsaetze.strip().split("\n\n")
    sentences = []
    for pair in pairs:
        lines = pair.strip().split("\n")
        if lines and lines[0].strip():
            sentences.append(lines[0].strip())
    return sentences


# ── TTS call ─────────────────────────────────────────────────────────────────

def _synthesize(api_key: str, text: str) -> bytes:
    clean = _strip_markup(text)
    if not clean:
        raise ValueError("Empty text after stripping markup")

    payload = {
        "input":       {"text": clean},
        "voice":       {"languageCode": LANGUAGE, "name": VOICE_NAME},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    resp = requests.post(
        TTS_URL,
        params={"key": api_key},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    import base64
    return base64.b64decode(resp.json()["audioContent"])


# ── Progress ─────────────────────────────────────────────────────────────────

def _load_audio_done() -> set[str]:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return set(json.load(f).get("audio_done", []))
    return set()


def _save_audio_done(done: set[str]) -> None:
    PROGRESS_FILE.parent.mkdir(exist_ok=True)
    existing: dict = {}
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            existing = json.load(f)
    existing["audio_done"] = sorted(done)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(existing, f, ensure_ascii=False)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    api_key = os.getenv("GOOGLE_TTS_KEY")
    if not api_key:
        raise SystemExit("GOOGLE_TTS_KEY not set in .env")

    card_files = sorted(CARDS_DIR.glob("*.yml"))
    if not card_files:
        raise SystemExit(f"No YAML cards found in {CARDS_DIR}/  →  run 02_generate_cards.py first")

    AUDIO_DIR.mkdir(exist_ok=True)
    done = _load_audio_done()

    print(f"Cards: {len(card_files):,}  |  Audio already done: {len(done):,}")
    print(f"Voice: {VOICE_NAME}\n")

    total_chars = 0

    for i, card_path in enumerate(card_files):
        with open(card_path, encoding="utf-8") as f:
            card = yaml.safe_load(f)

        rank      = int(card.get("Rang", 0))
        lemma     = card.get("Wort", card_path.stem)
        card_key  = f"{rank:04d}"

        if card_key in done:
            continue

        beispiele  = card.get("Beispielsätze", "") or ""
        sentences  = _extract_italian_sentences(beispiele)

        if not sentences:
            print(f"[{rank:4d}] {lemma:<22}  (no sentences – skipped)")
            done.add(card_key)
            continue

        print(f"[{rank:4d}] {lemma:<22}", end="  ", flush=True)
        success = True

        for j, sentence in enumerate(sentences, 1):
            out_path = AUDIO_DIR / f"{rank:04d}_s{j}.mp3"
            if out_path.exists():
                print(f"s{j}✓ ", end="", flush=True)
                continue
            try:
                audio_bytes   = _synthesize(api_key, sentence)
                out_path.write_bytes(audio_bytes)
                total_chars  += len(_strip_markup(sentence))
                print(f"s{j} ", end="", flush=True)
                time.sleep(DELAY)
            except Exception as exc:
                print(f"\n  ERROR {out_path.name}: {exc}")
                success = False
                break

        if success:
            done.add(card_key)
            print("✓")

        if (i + 1) % 100 == 0:
            _save_audio_done(done)

    _save_audio_done(done)

    mp3_count = len(list(AUDIO_DIR.glob("*.mp3")))
    print(f"\nDone.  {mp3_count:,} MP3 files in {AUDIO_DIR}/")
    print(f"Characters synthesised this run: ~{total_chars:,}")
    print(f"  (Standard voices: 4 M free/month  →  running total stays under free tier)")


if __name__ == "__main__":
    main()
