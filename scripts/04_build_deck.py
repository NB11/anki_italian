#!/usr/bin/env python3
"""
Step 4: Compile card templates and build the Anki .apkg deck file.

Usage (from repo root):
    python scripts/04_build_deck.py

Reads:   cards/*.yml
         audio/*.mp3
         card_templates/*
         .env  (GOOGLE_TTS_KEY)

Writes:  Italian_5000.apkg

The deck contains two card types per note:
  • Italienisch → Deutsch  (Italian word on front)
  • Deutsch → Italienisch  (German definition on front)
"""

import os
import re
import time
from datetime import datetime
from pathlib import Path

import genanki
import yaml
from dotenv import load_dotenv

_cfg    = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))

try:
    import sass
    def compile_scss(path: Path) -> str:
        return sass.compile(filename=str(path))
except ImportError:
    def compile_scss(path: Path) -> str:
        # libsass not installed – return raw content (styling will be degraded)
        print("  WARNING: libsass not installed. Install it: pip install libsass")
        return path.read_text(encoding="utf-8")

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT      = Path(".")
TMPL      = ROOT / "card_templates"
CARDS_DIR = ROOT / "cards"
AUDIO_DIR = ROOT / "audio"
OUTPUT    = ROOT / _cfg.get("output_file", "Italiano_5000.apkg")

# ── Stable IDs (must not change between builds or Anki will duplicate cards) ──

DECK_ID_ITDE  = 1122334455   # IT → DE sub-deck
DECK_ID_DEIT  = 1122334456   # DE → IT sub-deck
MODEL_ID_ITDE = 1234567890   # IT → DE note type
MODEL_ID_DEIT = 1234567891   # DE → IT note type


# ── Anki note fields (order must match the model definition below) ────────────

FIELD_NAMES = [
    "Rang",
    "Wort",
    "Wortart",
    "Wort mit Artikel",
    "Femininum / Plural",
    "IPA",
    "Definition",
    "Register",
    "Beispielsätze",
    "Audio",
    "Notiz",
    "Dispersion",
    "Konjugation",
]


# ── Template compilation ──────────────────────────────────────────────────────

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _compile_common_js() -> str:
    """Resolve common.js: inject cloze_game.js."""
    common = _read(TMPL / "common.js")
    cloze  = _read(TMPL / "cloze_game.js")
    return common.replace("___CLOZE_GAME___;", cloze)


def _compile_back_js(config_path: Path, common_js: str, version_ms: int) -> str:
    """Resolve back.js: inject config + common + placeholders."""
    back = _read(TMPL / "back.js")
    back = back.replace("___CONFIG___;",  _read(config_path))
    back = back.replace("___COMMONJS___;", common_js)
    back = back.replace("___DICT___;",    "")          # no Italian dictionary
    back = back.replace("___VERSION___",  str(version_ms))
    return back


def _compile_back_html(back_js: str, version_ms: int, tts_api_key: str) -> str:
    """Resolve back.html: inject JS + replace all placeholders."""
    persistence = _read(TMPL / "persistence.js")
    html = _read(TMPL / "back.html")

    # Remove the grammar JSON prefetch link (no Italian grammar file)
    html = re.sub(r'<link[^>]+prefetch[^>]*>\s*', '', html)

    html = html.replace("___PERSISTENCE___;",       persistence)
    html = html.replace("___BACKJS___;",            back_js)
    html = html.replace("___DATE___",               datetime.now().strftime("%d.%m.%Y"))
    html = html.replace("___GOOGLE_TTS_KEY___", tts_api_key)

    return html


def _compile_front_html(
    front_html_name: str,
    front_js_name: str,
    common_js: str,
    tts_api_key: str,
) -> str:
    """Resolve a front template: inject persistence + common + front JS."""
    persistence = _read(TMPL / "persistence.js")
    html = _read(TMPL / front_html_name)
    js   = _read(TMPL / front_js_name)

    html = html.replace("___PERSISTENCE___;", persistence)
    html = html.replace("___COMMONJS___;",    common_js)

    # The placeholder name matches the JS filename stem, e.g. ___FRONT_ITDE___
    stem = Path(front_js_name).stem.upper()          # "front_ITDE" → "FRONT_ITDE"
    html = html.replace(f"___{stem}___;", js)
    html = html.replace("___GOOGLE_TTS_KEY___", tts_api_key)

    return html


# ── YAML → Anki field list ────────────────────────────────────────────────────

def _card_to_fields(card: dict) -> list[str]:
    """Return field values in FIELD_NAMES order."""
    beispiele_raw = card.get("Beispielsätze", "") or ""
    beispiele = beispiele_raw.strip()

    rank = str(card.get("Rang", ""))
    word_audio_file = AUDIO_DIR / f"{int(rank):04d}_w.mp3" if rank.isdigit() else None
    audio = f"[sound:{int(rank):04d}_w.mp3]" if word_audio_file and word_audio_file.exists() else (card.get("Audio") or "")

    return [
        rank,
        card.get("Wort",               "") or "",
        card.get("Wortart",            "") or "",
        card.get("Wort mit Artikel",   "") or "",
        card.get("Femininum / Plural", "") or "",
        card.get("IPA",                "") or "",
        card.get("Definition",         "") or "",
        card.get("Register",           "") or "",
        beispiele,
        audio,
        card.get("Notiz",              "") or "",
        card.get("Dispersion",         "") or "",
        card.get("Konjugation",        "") or "",
    ]


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    card_files = sorted(CARDS_DIR.glob("*.yml"))
    if not card_files:
        raise SystemExit(f"No cards found in {CARDS_DIR}/  →  run 02_generate_cards.py first")

    tts_api_key = os.getenv("GOOGLE_TTS_KEY", "")
    if not tts_api_key:
        print("  NOTE: GOOGLE_TTS_KEY not set – live TTS playback will use Google Translate free API")

    version_ms = int(time.time() * 1000)
    print(f"Build date : {datetime.now().strftime('%d.%m.%Y')}")
    print(f"Cards      : {len(card_files):,}")
    print(f"Audio files: {len(list(AUDIO_DIR.glob('*.mp3'))):,}")
    print()

    # ── Compile templates ────────────────────────────────────────────────────

    print("Compiling templates …")
    common_js = _compile_common_js()

    back_itde_js   = _compile_back_js(TMPL / "back_ITDE_config.js", common_js, version_ms)
    back_deit_js   = _compile_back_js(TMPL / "back_DEIT_config.js", common_js, version_ms)

    back_itde_html = _compile_back_html(back_itde_js, version_ms, tts_api_key)
    back_deit_html = _compile_back_html(back_deit_js, version_ms, tts_api_key)

    front_itde_html = _compile_front_html(
        "front_ITDE.html", "front_ITDE.js", common_js, tts_api_key
    )
    front_deit_html = _compile_front_html(
        "front_DEIT.html", "front_DEIT.js", common_js, tts_api_key
    )

    # ── Compile CSS ──────────────────────────────────────────────────────────

    print("Compiling CSS …")
    css = compile_scss(TMPL / "style.scss")

    # ── Build genanki models (one per direction) ─────────────────────────────

    deck_name = _cfg.get("deck_name", "Italiano 5000")
    fields    = [{"name": n} for n in FIELD_NAMES]

    model_itde = genanki.Model(
        model_id  = MODEL_ID_ITDE,
        name      = f"{deck_name} IT→DE",
        fields    = fields,
        templates = [{"name": "Italienisch → Deutsch",
                      "qfmt": front_itde_html,
                      "afmt": back_itde_html}],
        css       = css,
    )

    model_deit = genanki.Model(
        model_id  = MODEL_ID_DEIT,
        name      = f"{deck_name} DE→IT",
        fields    = fields,
        templates = [{"name": "Deutsch → Italienisch",
                      "qfmt": front_deit_html,
                      "afmt": back_deit_html}],
        css       = css,
    )

    # ── Build two sub-decks ───────────────────────────────────────────────────

    deck_itde = genanki.Deck(DECK_ID_ITDE, f"{deck_name}::IT → DE")
    deck_deit = genanki.Deck(DECK_ID_DEIT, f"{deck_name}::DE → IT")

    print("Adding notes …")
    skipped = 0
    for card_path in card_files:
        with open(card_path, encoding="utf-8") as f:
            card = yaml.safe_load(f)

        if not card or not card.get("Wort"):
            skipped += 1
            continue

        card_fields = _card_to_fields(card)
        word        = card["Wort"]

        deck_itde.add_note(genanki.Note(
            model  = model_itde,
            fields = card_fields,
            guid   = genanki.guid_for(word + "_itde"),
        ))
        deck_deit.add_note(genanki.Note(
            model  = model_deit,
            fields = card_fields,
            guid   = genanki.guid_for(word + "_deit"),
        ))

    if skipped:
        print(f"  Skipped {skipped} cards with missing Wort field")

    # ── Collect audio media ───────────────────────────────────────────────────

    print("Collecting audio files …")
    media_files = [str(p) for p in sorted(AUDIO_DIR.glob("*.mp3"))]

    # ── Write .apkg ──────────────────────────────────────────────────────────

    package = genanki.Package([deck_itde, deck_deit])
    package.media_files = media_files
    package.write_to_file(str(OUTPUT))

    total_notes = len(deck_itde.notes)
    print(f"\nWritten to {OUTPUT}")
    print(f"   Notes   : {total_notes:,}  ({total_notes*2:,} cards total)")
    print(f"   Audio   : {len(media_files):,} MP3 files")
    size_mb = OUTPUT.stat().st_size / 1_048_576
    print(f"   Size    : {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
