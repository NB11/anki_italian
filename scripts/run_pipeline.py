#!/usr/bin/env python3
"""
Full pipeline: runs steps 01 → 02 → 03 → 04 in sequence.

Usage (from repo root):
    python scripts/run_pipeline.py           # all steps
    python scripts/run_pipeline.py --from 2  # resume from step 2
    python scripts/run_pipeline.py --only 2  # run only step 2

Each step is skipped if its output already exists (unless --force is passed).
"""

import argparse
import subprocess
import sys
from pathlib import Path


STEPS = [
    {
        "n": 1,
        "script": "scripts/01_extract_wordlist.py",
        "desc":   "Extract word list from corpus",
        "check":  Path("data/wordlist.csv"),
    },
    {
        "n": 2,
        "script": "scripts/02_generate_cards.py",
        "desc":   "Generate card YAML files via Mistral",
        "check":  None,   # always run (handles resume internally)
    },
    {
        "n": 3,
        "script": "scripts/03_generate_audio.py",
        "desc":   "Generate audio MP3s via Google TTS",
        "check":  None,   # always run (handles resume internally)
    },
    {
        "n": 4,
        "script": "scripts/04_build_deck.py",
        "desc":   "Build Anki .apkg deck",
        "check":  None,
    },
]


def run_step(step: dict, force: bool) -> bool:
    n      = step["n"]
    script = step["script"]
    desc   = step["desc"]
    check  = step["check"]

    print(f"\n{'='*60}")
    print(f"  Step {n}: {desc}")
    print(f"{'='*60}")

    if not force and check and check.exists():
        print(f"  Skipping — {check} already exists (use --force to rerun)")
        return True

    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        print(f"\n  Step {n} failed with exit code {result.returncode}. Stopping.")
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from",  dest="from_step", type=int, default=1,
                        help="Start from this step number (default: 1)")
    parser.add_argument("--only",  dest="only_step", type=int, default=None,
                        help="Run only this step number")
    parser.add_argument("--force", action="store_true",
                        help="Re-run steps even if output already exists")
    args = parser.parse_args()

    steps = STEPS
    if args.only_step:
        steps = [s for s in STEPS if s["n"] == args.only_step]
        if not steps:
            raise SystemExit(f"Unknown step: {args.only_step}")
    else:
        steps = [s for s in STEPS if s["n"] >= args.from_step]

    print(f"Running {len(steps)} step(s): {[s['n'] for s in steps]}")

    for step in steps:
        if not run_step(step, force=args.force):
            sys.exit(1)

    print(f"\n{'='*60}")
    print("  Pipeline complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
