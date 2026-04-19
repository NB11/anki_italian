#!/usr/bin/env python3
"""
Step 6: Generate one TTS audio file per card for the word pronunciation.

Files are named:  {rank:04d}_w.mp3
These are played by the card template when the user taps the word.

Usage (from repo root):
    python scripts/06_generate_word_audio.py [--limit N]

Reads:   cards/*.yml
Writes:  audio/{rank:04d}_w.mp3
"""

import json
import os
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
DELAY    = 0.15


def _synthesize(api_key: str, text: str) -> bytes:
    import base64
    payload = {
        "input":       {"text": text},
        "voice":       {"languageCode": LANGUAGE, "name": VOICE_NAME},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    resp = requests.post(TTS_URL, params={"key": api_key}, json=payload, timeout=30)
    resp.raise_for_status()
    return base64.b64decode(resp.json()["audioContent"])


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    api_key = os.getenv("GOOGLE_TTS_KEY")
    if not api_key:
        raise SystemExit("GOOGLE_TTS_KEY not set in .env")

    AUDIO_DIR.mkdir(exist_ok=True)

    card_files = sorted(CARDS_DIR.glob("*.yml"))
    todo = []
    for path in card_files:
        card = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not card:
            continue
        rank = int(card.get("Rang", 0))
        out  = AUDIO_DIR / f"{rank:04d}_w.mp3"
        if not out.exists():
            todo.append((rank, card.get("Wort mit Artikel") or card.get("Wort", ""), out))

    if args.limit:
        todo = todo[:args.limit]

    print(f"Word audio missing: {len(todo):,}  |  Voice: {VOICE_NAME}")
    print(f"Est. time: {len(todo) * DELAY / 60:.1f} min\n")

    errors = []
    for i, (rank, text, out_path) in enumerate(todo):
        text = text.strip()
        if not text:
            continue
        print(f"[{rank:4d}] {text:<28}", end="  ", flush=True)
        try:
            out_path.write_bytes(_synthesize(api_key, text))
            print("✓")
        except Exception as exc:
            print(f"ERROR: {exc}")
            errors.append(f"{rank} {text}: {exc}")
        time.sleep(DELAY)

    print(f"\nDone.  {len(todo) - len(errors):,} word audio files written.")
    if errors:
        print(f"{len(errors)} errors (re-run to retry):")
        for e in errors[:10]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
