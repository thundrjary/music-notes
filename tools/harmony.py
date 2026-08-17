#!/usr/bin/env python3
"""
harmony_drill.py

A piano-first Roman-numeral harmony drill.

Example prompt:
    A♭ major: ii6 → V7 → I

Press Enter after playing it at the piano. The program then reveals the
correctly spelled chord tones and asks whether the response felt automatic.
Missed/slow items receive extra weight in later rounds.

Standard library only. Python 3.10+ recommended.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# ---------- Pitch / spelling ----------

PC = {
    "C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11,
}

LETTERS = ["C", "D", "E", "F", "G", "A", "B"]

ACCIDENTAL_TO_OFFSET = {
    "bb": -2,
    "b": -1,
    "": 0,
    "#": 1,
    "##": 2,
}

OFFSET_TO_ACCIDENTAL = {
    -2: "bb",
    -1: "b",
    0: "",
    1: "#",
    2: "##",
}

PRETTY = str.maketrans({
    "b": "♭",
    "#": "♯",
})

MAJOR_KEYS = [
    "C", "G", "D", "A", "E", "B", "F#",
    "F", "Bb", "Eb", "Ab", "Db", "Gb",
]

MINOR_KEYS = [
    "A", "E", "B", "F#", "C#", "G#", "D#",
    "D", "G", "C", "F", "Bb", "Eb",
]

# Scale semitone patterns from tonic.
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
NATURAL_MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]


def parse_note(note: str) -> tuple[str, str]:
    m = re.fullmatch(r"([A-G])((?:bb|##|b|#)?)", note)
    if not m:
        raise ValueError(f"Invalid note name: {note}")
    return m.group(1), m.group(2)


def note_pc(note: str) -> int:
    letter, accidental = parse_note(note)
    return (PC[letter] + ACCIDENTAL_TO_OFFSET[accidental]) % 12


def signed_pc_delta(target_pc: int, natural_pc: int) -> int:
    """Return smallest accidental offset needed to turn natural_pc into target_pc."""
    d = (target_pc - natural_pc) % 12
    if d > 6:
        d -= 12
    return d


def spell_scale(tonic: str, mode: str) -> list[str]:
    tonic_letter, _ = parse_note(tonic)
    tonic_pc = note_pc(tonic)
    pattern = MAJOR_SCALE if mode == "major" else NATURAL_MINOR_SCALE

    start = LETTERS.index(tonic_letter)
    out = []
    for degree, interval in enumerate(pattern):
        letter = LETTERS[(start + degree) % 7]
        target_pc = (tonic_pc + interval) % 12
        delta = signed_pc_delta(target_pc, PC[letter])
        if delta not in OFFSET_TO_ACCIDENTAL:
            raise ValueError(
                f"Cannot spell {tonic} {mode} cleanly at degree {degree+1}"
            )
        out.append(letter + OFFSET_TO_ACCIDENTAL[delta])
    return out


def respell_letter_to_pc(letter: str, target_pc: int) -> str:
    delta = signed_pc_delta(target_pc, PC[letter])
    if delta not in OFFSET_TO_ACCIDENTAL:
        raise ValueError(f"Need unsupported accidental offset {delta} for {letter}")
    return letter + OFFSET_TO_ACCIDENTAL[delta]


def pretty_note(note: str) -> str:
    return note.translate(PRETTY)


def pretty_key(key: str) -> str:
    return pretty_note(key)


# ---------- Roman numeral parsing ----------

ROMAN_TO_DEGREE = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
}

@dataclass(frozen=True)
class RomanChord:
    raw: str
    degree: int
    seventh: bool
    inversion: int  # 0=root, 1=first, 2=second, 3=third


def parse_roman(symbol: str) -> RomanChord:
    """
    Supported examples:
        I, ii, IV6, V7, ii65, V43, V42, vii°7
    Case/quality markings are accepted for readability; notes are generated
    diatonically from the key, except V/V7 in minor uses a raised leading tone.
    """
    s = symbol.strip().replace("ø", "").replace("°", "")
    m = re.fullmatch(r"([ivIV]+)(64|65|43|42|7|6)?", s)
    if not m:
        raise ValueError(f"Unsupported Roman numeral: {symbol}")

    roman = m.group(1).upper()
    if roman not in ROMAN_TO_DEGREE:
        raise ValueError(f"Unsupported Roman numeral: {symbol}")

    figure = m.group(2) or ""
    seventh = figure in {"7", "65", "43", "42"}

    if seventh:
        inversion = {"7": 0, "65": 1, "43": 2, "42": 3}[figure]
    else:
        inversion = {"": 0, "6": 1, "64": 2}[figure]

    return RomanChord(
        raw=symbol,
        degree=ROMAN_TO_DEGREE[roman],
        seventh=seventh,
        inversion=inversion,
    )


def diatonic_chord_notes(
    tonic: str,
    mode: str,
    symbol: str,
    harmonic_minor_dominant: bool = True,
) -> list[str]:
    chord = parse_roman(symbol)
    scale = spell_scale(tonic, mode)

    count = 4 if chord.seventh else 3
    indices = [((chord.degree - 1) + 2 * i) % 7 for i in range(count)]
    notes = [scale[i] for i in indices]

    # In minor, conventional functional V and vii use the raised leading tone.
    # This gives E minor: V7 = B-D#-F#-A rather than B-D-F#-A.
    if mode == "minor" and harmonic_minor_dominant and chord.degree in {5, 7}:
        seventh_degree_idx = 6
        raised_pc = (note_pc(scale[seventh_degree_idx]) + 1) % 12
        raised_letter = parse_note(scale[seventh_degree_idx])[0]
        raised_leading_tone = respell_letter_to_pc(raised_letter, raised_pc)
        notes = [
            raised_leading_tone if parse_note(n)[0] == raised_letter else n
            for n in notes
        ]

    # Rotate into inversion order, which is useful at the keyboard.
    inv = chord.inversion
    return notes[inv:] + notes[:inv]


# ---------- Drill content ----------

DEFAULT_TEMPLATES = [
    ("ii6 → V7 → I", ["ii6", "V7", "I"]),
    ("I → IV → V7 → I", ["I", "IV", "V7", "I"]),
    ("I → vi → ii → V7 → I", ["I", "vi", "ii", "V7", "I"]),
    ("I6 → ii6 → V7 → I", ["I6", "ii6", "V7", "I"]),
    ("IV → ii6 → V7 → I", ["IV", "ii6", "V7", "I"]),
    ("I → V6 → vi → IV → ii6 → V7 → I", ["I", "V6", "vi", "IV", "ii6", "V7", "I"]),
]

MINOR_TEMPLATES = [
    ("i → iv → V7 → i", ["i", "iv", "V7", "i"]),
    ("ii°6 → V7 → i", ["ii°6", "V7", "i"]),
    ("i → VI → ii°6 → V7 → i", ["i", "VI", "ii°6", "V7", "i"]),
    ("i6 → iv → V7 → i", ["i6", "iv", "V7", "i"]),
]


@dataclass
class Drill:
    key: str
    mode: str
    label: str
    chords: list[str]

    @property
    def id(self) -> str:
        return f"{self.key}|{self.mode}|{self.label}"


def make_drills(mode: str, keys: list[str] | None = None) -> list[Drill]:
    drills: list[Drill] = []
    modes = ["major", "minor"] if mode == "both" else [mode]

    for m in modes:
        default_keys = MAJOR_KEYS if m == "major" else MINOR_KEYS
        selected = keys if keys else default_keys
        templates = DEFAULT_TEMPLATES if m == "major" else MINOR_TEMPLATES

        valid_keys = [k for k in selected if k in default_keys]
        for key in valid_keys:
            for label, chords in templates:
                drills.append(Drill(key, m, label, chords))

    if not drills:
        raise ValueError("No drills matched the selected mode/keys.")
    return drills


# ---------- Adaptive scoring ----------

def load_stats(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_stats(path: Path, stats: dict) -> None:
    path.write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")


def drill_weight(drill: Drill, stats: dict) -> float:
    s = stats.get(drill.id)
    if not s:
        return 2.0
    attempts = max(1, s.get("attempts", 0))
    fluent = s.get("fluent", 0)
    fluency = fluent / attempts
    # New/weak material appears more often; mastered material never disappears.
    return 0.5 + 3.5 * (1.0 - fluency)


def choose_drill(drills: list[Drill], stats: dict) -> Drill:
    weights = [drill_weight(d, stats) for d in drills]
    return random.choices(drills, weights=weights, k=1)[0]


def reveal(drill: Drill) -> None:
    print()
    for symbol in drill.chords:
        notes = diatonic_chord_notes(drill.key, drill.mode, symbol)
        rendered = " – ".join(pretty_note(n) for n in notes)
        print(f"  {symbol:<5} {rendered}")
    print()


def update_stats(stats: dict, drill: Drill, fluent: bool, elapsed: float) -> None:
    s = stats.setdefault(drill.id, {
        "attempts": 0,
        "fluent": 0,
        "slow_or_missed": 0,
        "best_seconds": None,
        "last_seconds": None,
    })
    s["attempts"] += 1
    if fluent:
        s["fluent"] += 1
    else:
        s["slow_or_missed"] += 1
    s["last_seconds"] = round(elapsed, 2)
    if s["best_seconds"] is None or elapsed < s["best_seconds"]:
        s["best_seconds"] = round(elapsed, 2)


def print_summary(stats: dict, session: list[tuple[Drill, bool, float]]) -> None:
    if not session:
        return
    total = len(session)
    fluent = sum(1 for _, ok, _ in session if ok)
    avg = sum(t for _, _, t in session) / total

    print("\nSession summary")
    print("---------------")
    print(f"Drills:          {total}")
    print(f"Automatic:       {fluent}/{total} ({100*fluent/total:.0f}%)")
    print(f"Mean play time:  {avg:.1f}s")

    weak = sorted(
        session,
        key=lambda x: (x[1], -x[2])
    )[:5]
    weak_items = []
    seen = set()
    for d, ok, t in weak:
        if d.id not in seen and (not ok or t > avg):
            weak_items.append((d, ok, t))
            seen.add(d.id)
    if weak_items:
        print("\nReview:")
        for d, ok, t in weak_items:
            mark = "slow/missed" if not ok else "slow"
            print(f"  {pretty_key(d.key)} {d.mode}: {d.label}  [{mark}, {t:.1f}s]")


# ---------- CLI ----------

def normalize_key_token(token: str) -> str:
    return (
        token.strip()
        .replace("♭", "b")
        .replace("♯", "#")
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Procedural Roman-numeral piano harmony drill."
    )
    p.add_argument(
        "--mode",
        choices=["major", "minor", "both"],
        default="major",
        help="Key mode to drill (default: major).",
    )
    p.add_argument(
        "--keys",
        nargs="*",
        help='Restrict keys, e.g. --keys C F Bb Eb Ab',
    )
    p.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of drills; 0 means continue until q (default: 0).",
    )
    p.add_argument(
        "--stats",
        default=str(Path.home() / ".harmony_drill_stats.json"),
        help="Path to adaptive stats JSON.",
    )
    p.add_argument(
        "--no-adaptive",
        action="store_true",
        help="Choose drills uniformly instead of weighting weak material.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible sessions.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    keys = [normalize_key_token(k) for k in args.keys] if args.keys else None
    drills = make_drills(args.mode, keys)
    stats_path = Path(args.stats).expanduser()
    stats = load_stats(stats_path)

    print("Harmony Drill")
    print("=============")
    print("Play the progression before revealing it.")
    print("Enter = reveal | q = quit")
    print("After reveal: y = automatic, n = slow/missed\n")

    session: list[tuple[Drill, bool, float]] = []
    n = 0

    try:
        while args.count <= 0 or n < args.count:
            drill = (
                random.choice(drills)
                if args.no_adaptive
                else choose_drill(drills, stats)
            )
            n += 1

            print(f"[{n}] {pretty_key(drill.key)} {drill.mode}: {drill.label}")
            start = time.monotonic()
            cmd = input("    play it, then press Enter > ").strip().lower()
            elapsed = time.monotonic() - start

            if cmd == "q":
                break

            reveal(drill)

            while True:
                answer = input("Automatic? [y/n/q] > ").strip().lower()
                if answer in {"y", "n", "q"}:
                    break

            if answer == "q":
                break

            fluent = answer == "y"
            update_stats(stats, drill, fluent, elapsed)
            session.append((drill, fluent, elapsed))
            save_stats(stats_path, stats)
            print()

    except KeyboardInterrupt:
        print()

    print_summary(stats, session)
    if session:
        save_stats(stats_path, stats)


if __name__ == "__main__":
    main()
