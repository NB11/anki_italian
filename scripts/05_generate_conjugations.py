#!/usr/bin/env python3
"""
Step 5: Generate Italian verb conjugation tables and write them into cards/*.yml.

Produces a compact horizontal table (one row per tense, stem + 6 endings) that
matches the visual style of the French 5000 deck. The existing CSS classes
.tense / .tense_stem / .irregular / .regular are reused, so no template changes
are needed — only back.html's {{#Konjugation}} block needs to be filled.

Usage (from repo root):
    python scripts/05_generate_conjugations.py [--limit N] [--refill]

Reads:   cards/*.yml
Writes:  cards/*.yml  (Konjugation field updated for verb cards)
         data/conjugation_progress.json  (resume checkpoint)
"""

import json
import os
import time
from html import escape
from pathlib import Path

import yaml
from mistralai.client import Mistral
from dotenv import load_dotenv

load_dotenv()

CARDS_DIR     = Path("cards")
PROGRESS_FILE = Path("data/conjugation_progress.json")

_cfg  = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
RPM   = int(os.getenv("MISTRAL_RPM", str(_cfg.get("mistral_rpm", 30))))
DELAY = 60.0 / RPM
MODEL = _cfg.get("mistral_model", "mistral-small-latest")

VERB_POS = {"v", "vi", "vt", "vr"}

PERSONS = ["io", "tu", "lui/lei", "noi", "voi", "loro"]

# Labels shown in the leftmost column of the conjugation table
TENSE_LABELS = {
    "P":  "Presente",
    "IT": "Imperfetto",
    "F":  "Futuro",
    "IF": "Imperativo",
    "G":  "Gerundio",
    "PC": "Pass.&#8239;pross.",
    "C":  "Condizionale",
    "S":  "Congiuntivo",
    "PS": "Pass.&#8239;remoto",
}

# Always-visible tenses; remaining ones are shown via "Alles anzeigen"
TENSE_DEFAULT = ["P", "IT", "F", "IF", "G", "PC", "C"]
TENSE_EXTRA   = ["S", "PS"]
TENSE_ORDER   = TENSE_DEFAULT + TENSE_EXTRA


# ── Mistral prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an Italian grammar expert creating Anki conjugation data for German learners.
Respond with ONLY a single JSON object — no markdown fences, no extra text.

Required keys:

"aux"               – "avere" or "essere"
"reflexive"         – true if the verb requires a reflexive pronoun (e.g. sedersi, alzarsi)
"only_third_person" – true ONLY for truly impersonal verbs (piovere, nevicare, etc.)
"classification"    – verb ending group: "-are", "-ere", "-ire", or "irregolare"

Conjugation arrays — always 6 elements [io, tu, lui/lei, noi, voi, loro]:
"P"   – Presente Indicativo
"IT"  – Imperfetto Indicativo
"F"   – Futuro Semplice
"IF"  – Imperativo  ← use "" for io (no imperative form exists)
"C"   – Condizionale Presente
"S"   – Congiuntivo Presente
"PS"  – Passato Remoto

Single-form strings:
"G"   – Gerundio            (e.g. "mangiando")
"PC"  – Participio Passato  (base -o form, e.g. "mangiato")

Stems — the shared base for each tense (used for display):
"stems" – object with keys for each conjugated tense. Each value is the longest
          grammatically meaningful stem shared by all forms of that tense.
          Examples:
            Presente of "mangiare"  → "mangi"   (io mangio, tu mangi, …)
            Futuro of "mangiare"    → "manger"  (mangerò, mangerai, …)
            Condizionale of "asc."  → "ascolter" (ascolterei, ascolteresti, …)
            Condizionale endings are always -ei/-esti/-ebbe/-emmo/-este/-ebbero,
            so the stem must NOT include the trailing "e" of those endings.
          For highly irregular tenses where there is no shared stem, use "".

Rules:
- For reflexive verbs include the reflexive pronoun in every form (e.g. "mi siedo").
- For only_third_person verbs use a 1-element array with just the 3rd-person singular.
- Do NOT include subject pronouns (io/tu/…) in forms — they are displayed separately.
- All forms must be the actual conjugated Italian word, not the infinitive.
"""


# ── Stem / ending helpers ──────────────────────────────────────────────────────

def _longest_common_prefix(words: list[str]) -> str:
    if not words:
        return ""
    prefix = words[0]
    for w in words[1:]:
        i = 0
        while i < len(prefix) and i < len(w) and prefix[i] == w[i]:
            i += 1
        prefix = prefix[:i]
        if not prefix:
            break
    return prefix


def _stem_and_endings(forms: list[str]) -> tuple[str, list[str]]:
    """
    Find the longest common prefix of all non-empty forms.
    Returns (stem, endings) where each ending is "-suffix" or "·" when no suffix.
    Falls back to ("", forms) when the common prefix is shorter than 3 characters.
    """
    forms = [f[0] if isinstance(f, list) else str(f) if f is not None else "" for f in forms]
    real = [f for f in forms if f and f != "—"]
    if not real:
        return "", list(forms)

    prefix = _longest_common_prefix(real)

    if len(prefix) < 3:
        return "", list(forms)

    endings: list[str] = []
    for f in forms:
        if not f or f == "—":
            endings.append("—")
        else:
            suffix = f[len(prefix):]
            endings.append(f"-{suffix}" if suffix else "·")
    return prefix, endings


# ── HTML builder ───────────────────────────────────────────────────────────────

def _td(css_class: str, content: str, data_full: str = "", extra: str = "") -> str:
    df = f' data-full="{escape(data_full)}"' if data_full else ""
    return f'<td class="{css_class}"{df}{extra}><div>{content}</div></td>'


def _endings_from_stem(forms: list[str], stem: str) -> list[str]:
    """Compute endings given a known stem. Falls back to LCP-computed stem if needed."""
    if not stem:
        return list(forms)
    endings: list[str] = []
    for f in forms:
        if isinstance(f, list):
            f = f[0] if f else ""
        f = str(f) if f is not None else ""
        if not f or f == "—":
            endings.append("—")
        elif f.startswith(stem):
            suffix = f[len(stem):]
            endings.append(f"-{suffix}" if suffix else "·")
        else:
            endings.append(f)
    return endings


def _build_html(data: dict) -> str:
    aux        = (data.get("aux") or "avere").strip().lower()
    reflexive  = bool(data.get("reflexive"))
    only_third = bool(data.get("only_third_person"))
    cls        = (data.get("classification") or "").strip()
    # Mistral-supplied stems take priority over the LCP algorithm
    mistral_stems: dict = data.get("stems") or {}

    rows: list[str] = []

    for tense in TENSE_ORDER:
        val = data.get(tense)
        if val is None:
            continue

        label     = TENSE_LABELS[tense]
        row_class = "regular_tense" if tense in TENSE_EXTRA else ""
        row_open  = f'<tr data-tense="{tense}"' + (f' class="{row_class}"' if row_class else "") + ">"

        # ── Single-form tenses: Gerundio and Participio passato ──────────────
        if tense in ("G", "PC"):
            form = str(val[0] if isinstance(val, list) else val).strip()
            stem_text = f"(con {escape(aux)})" if tense == "PC" else ""
            cells = (
                _td("tense", label)
                + _td("tense_stem", stem_text)
                + _td("irregular", escape(form), data_full=form, extra=' colspan="6"')
            )
            rows.append(row_open + cells + "</tr>")
            continue

        # ── Six-form tenses ───────────────────────────────────────────────────
        forms   = val if isinstance(val, list) else [str(val)]
        # Coerce every form to a plain string (Mistral occasionally returns lists)
        forms   = [f[0] if isinstance(f, list) else str(f) if f is not None else "" for f in forms]
        persons = ["lui/lei"] if only_third else PERSONS

        # Pad / trim to match number of persons
        forms = (forms + [""] * len(persons))[: len(persons)]

        # Replace empty io-imperativo with an em-dash
        if tense == "IF" and len(forms) >= 1 and not forms[0]:
            forms[0] = "—"

        # Use Mistral's stem if provided; otherwise fall back to LCP
        if tense in mistral_stems and isinstance(mistral_stems[tense], str):
            stem    = mistral_stems[tense].strip()
            endings = _endings_from_stem(forms, stem)
        else:
            stem, endings = _stem_and_endings(forms)

        cells = _td("tense", label) + _td("tense_stem", escape(stem))

        for i, (form, ending) in enumerate(zip(forms, endings)):
            display = escape(ending if stem else form)
            cells += _td("irregular", display, data_full=form)

        # Pad to always emit 6 form cells so the table grid is uniform
        for _ in range(6 - len(persons)):
            cells += "<td></td>"

        rows.append(row_open + cells + "</tr>")

    if not rows:
        raise ValueError("Mistral returned no recognisable tense data — will retry")

    table = (
        f'<table class="section-conjugation-table" data-aux="{escape(aux)}">\n'
        + "\n".join(rows)
        + "\n</table>"
    )

    return (
        f'<div id="verb-classification">{escape(cls)}</div>\n'
        f'<div id="conjugation-table"'
        f' data-aux="{escape(aux)}"'
        f' data-h-aspire="false"'
        f' data-only-third-person="{str(only_third).lower()}"'
        f' data-reflexive="{str(reflexive).lower()}">\n'
        f"{table}\n"
        f"</div>"
    )


# ── YAML helpers ───────────────────────────────────────────────────────────────

def _yaml_str(value: str) -> str:
    if not value and value != 0:
        return "''"
    s = str(value)
    needs_quote = (
        not s
        or s[0] in ':,[]{}#&*?|<>=!%@`"\''
        or ': ' in s
        or ' #' in s
        or s.lower() in {"true", "false", "null", "yes", "no", "on", "off", "~"}
    )
    if needs_quote:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _write_card(card: dict, path: Path) -> None:
    beispiele   = (card.get("Beispielsätze") or "").strip()
    konjugation = (card.get("Konjugation")   or "").strip()

    lines = [
        f"Rang: {card.get('Rang', '')}",
        f"Wort: {_yaml_str(str(card.get('Wort', '')))}",
        f"Wortart: {_yaml_str(str(card.get('Wortart', '')))}",
        f"Wort mit Artikel: {_yaml_str(str(card.get('Wort mit Artikel', '')))}",
        f"Femininum / Plural: {_yaml_str(str(card.get('Femininum / Plural') or ''))}",
        f"IPA: {_yaml_str(str(card.get('IPA') or ''))}",
        f"Definition: {_yaml_str(str(card.get('Definition', '')))}",
        f"Register: {_yaml_str(str(card.get('Register') or ''))}",
    ]

    if beispiele:
        lines.append("Beispielsätze: |-")
        for line in beispiele.split("\n"):
            lines.append(f"  {line}")
    else:
        lines.append("Beispielsätze: ''")

    lines += [
        f"Audio: {_yaml_str(str(card.get('Audio') or ''))}",
        f"Notiz: {_yaml_str(str(card.get('Notiz') or ''))}",
        f"Dispersion: {_yaml_str(str(card.get('Dispersion') or ''))}",
    ]

    if konjugation:
        lines.append("Konjugation: |-")
        for line in konjugation.split("\n"):
            lines.append(f"  {line}")
    else:
        lines.append("Konjugation: ''")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Progress tracking ──────────────────────────────────────────────────────────

def _load_done() -> set[str]:
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text(encoding="utf-8")).get("done", []))
    return set()


def _save_done(done: set[str]) -> None:
    PROGRESS_FILE.parent.mkdir(exist_ok=True)
    existing: dict = {}
    if PROGRESS_FILE.exists():
        existing = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    existing["done"] = sorted(done)
    PROGRESS_FILE.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N verb cards (default: all)")
    parser.add_argument("--refill", action="store_true",
                        help="Re-generate even for already-filled cards")
    args = parser.parse_args()

    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise SystemExit("MISTRAL_API_KEY not set in .env")

    client = Mistral(api_key=api_key)

    verb_cards: list[tuple[Path, dict]] = []
    for path in sorted(CARDS_DIR.glob("*.yml")):
        card = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not card:
            continue
        pos     = (card.get("Wortart") or "").strip().lower()
        is_verb = pos in VERB_POS or pos.startswith("v")
        if not is_verb:
            continue
        already = bool(str(card.get("Konjugation") or "").strip())
        if already and not args.refill:
            continue
        verb_cards.append((path, card))

    done = _load_done()
    todo = [(p, c) for p, c in verb_cards if c.get("Wort") not in done]
    if args.limit:
        todo = todo[: args.limit]

    print(f"Verb cards needing conjugation : {len(verb_cards):,}")
    print(f"Already in progress file       : {len(done):,}")
    print(f"To process this run            : {len(todo):,}")
    print(f"Rate: {RPM} RPM  ({DELAY:.1f}s delay)  "
          f"est. {len(todo) * DELAY / 3600:.1f}h\n")

    errors: list[str] = []

    for i, (path, card) in enumerate(todo):
        lemma = card.get("Wort", "")
        pos   = card.get("Wortart", "")

        print(f"[{i + 1:>4}/{len(todo)}] {lemma:<22} ({pos})", end="  ", flush=True)

        try:
            resp = client.chat.complete(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": f'Verb: "{lemma}"'},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            data = json.loads(resp.choices[0].message.content)
        except Exception as exc:
            print(f"ERROR: {exc}")
            errors.append(f"{lemma}: {exc}")
            time.sleep(DELAY)
            continue

        try:
            html = _build_html(data)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            errors.append(f"{lemma}: {exc}")
            time.sleep(DELAY)
            continue

        card["Konjugation"] = html
        _write_card(card, path)

        done.add(lemma)
        print(f"-> {path.name}")

        if (i + 1) % 20 == 0:
            _save_done(done)

        time.sleep(DELAY)

    _save_done(done)
    print(f"\nFinished.  {len(done)} conjugations total in progress file.")
    if errors:
        print(f"\n{len(errors)} errors (re-run to retry):")
        for e in errors[:10]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
