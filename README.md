# Italiano 5000

Ein Anki-Deck mit den **5000 häufigsten italienischen Wörtern** – mit Audio, Beispielsätzen und Verbkonjugationen.

> Herunterladen auf [AnkiWeb](https://ankiweb.net/shared/info/XXXXXXX) *(Link einfügen)*

---

## Inhalt

Jede Karte enthält:

- **Aussprache-Audio** (Google Cloud TTS)
- **5 Beispielsätze** mit deutscher Übersetzung
- **Wortart**, Artikel, Plural- und Femininform
- **Konjugationstabelle** für Verben
- **Häufigkeitsrang** 

Zwei Kartentypen pro Wort: **Italienisch → Deutsch** und **Deutsch → Italienisch**

---

## Wortliste

Die Wörter wurden aus zwei Korpora kombiniert:

| Korpus | Quelle | Beschreibung |
|---|---|---|
| SUBTLEX-IT | [crr.ugent.be](http://crr.ugent.be/programs-data/subtitle-frequencies/subtlex-it) | Worthäufigkeiten aus Film- und TV-Untertiteln |
| Leipzig News 2024 | [wortschatz.uni-leipzig.de](https://wortschatz.uni-leipzig.de) | Worthäufigkeiten aus Nachrichtentexten |

---

## Projekt selbst bauen

### Voraussetzungen

```bash
pip install -r requirements.txt
```

Erstelle eine `.env`-Datei mit:

```
MISTRAL_API_KEY=...
GOOGLE_TTS_KEY=...
```

### Pipeline

```bash
python scripts/run_pipeline.py
```

Oder einzeln:

| Schritt | Skript | Beschreibung |
|---|---|---|
| 1 | `01_extract_wordlist.py` | Wortliste aus Korpora extrahieren |
| 2 | `02_generate_cards.py` | Karten-YAML via Mistral API generieren |
| 3 | `03_generate_audio.py` | Satz-Audio via Google TTS generieren |
| 4 | `05_generate_conjugations.py` | Verbkonjugationen generieren |
| 5 | `06_generate_word_audio.py` | Wort-Audio via Google TTS generieren |
| 6 | `04_build_deck.py` | `.apkg`-Datei zusammenbauen |

Einstellungen (Anzahl Wörter, Stimme, Modell etc.) in [`config.yaml`](config.yaml).

---

## Karten bearbeiten

Die Karten liegen als YAML-Dateien im Ordner [`cards/`](cards).

1. Forke dieses Repository
2. Bearbeite die Dateien in `cards/`
3. Committe deine Änderungen
4. Erstelle einen Pull Request

---

## Lizenz

Die Karteninhalte stehen unter [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/deed.de).  
Der Quellcode in [`card_templates/`](card_templates) steht unter der Apache-2.0-Lizenz.
