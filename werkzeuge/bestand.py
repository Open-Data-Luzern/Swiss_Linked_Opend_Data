"""Was steht in den Datenbanken? Ein Ueberblick ueber alle Dateien.

    python werkzeuge/bestand.py            # eine Zeile je Organisation
    python werkzeuge/bestand.py --befunde  # dazu die Qualitaetsbefunde

Liest nur — der Aufbau darf nebenher weiterlaufen. Absichtlich ein eigenes
Skript ohne Import von ``swiss_ogd``: Es soll auch dann funktionieren, wenn am
Paket gerade gearbeitet wird.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

# Wo die Daten liegen, entscheidet SWISS_OGD_WURZEL — dieselbe Variable, die
# auch der Aufbau liest. Ohne sie das Projektverzeichnis. Die Datenbanken
# liegen nicht zwingend beim Quellcode: auf einer kleinen Systemplatte werden
# sie auf einen anderen Traeger gelegt (Entscheid vom 22. September 2026).
WURZEL = Path(os.environ.get("SWISS_OGD_WURZEL", Path(__file__).resolve().parents[1]))
DATENBANKEN = WURZEL / "datenbanken"


def _zahl(wert: object) -> str:
    """Tausendertrennung mit Hochkomma, Schweizer Schreibweise."""
    return f"{int(wert or 0):,}".replace(",", "'")


def main(argv: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--befunde", action="store_true", help="Befunde mit ausweisen")
    argumente = zerleger.parse_args(argv)

    dateien = sorted(DATENBANKEN.glob("*.sqlite"))
    if not dateien:
        print(f"Keine Datenbanken in {DATENBANKEN}", file=sys.stderr)
        return 1

    kopf = (
        f"{'Organisation':<42} {'Datensaetze':>11} {'Sammlungen':>11} "
        f"{'ladbar':>7} {'geladen':>8} {'Tabellen':>9} {'Zeilen':>14} {'MB':>9}"
    )
    print(kopf)
    print("-" * len(kopf))

    summe = Counter()
    befunde: Counter[tuple[str, str]] = Counter()
    unvollstaendig: list[str] = []

    for datei in dateien:
        # read-only oeffnen: ein laufender Aufbau wird nicht gestoert.
        verbindung = sqlite3.connect(f"file:{datei}?mode=ro", uri=True, timeout=30)
        verbindung.row_factory = sqlite3.Row
        try:
            zeile = verbindung.execute("SELECT * FROM v_bestand").fetchone()
        except sqlite3.Error as fehler:
            print(f"{datei.stem:<42} nicht lesbar: {fehler}")
            verbindung.close()
            continue

        mb = datei.stat().st_size / 1e6
        print(
            f"{(zeile['organisation'] or datei.stem)[:42]:<42} "
            f"{_zahl(zeile['datensaetze']):>11} {_zahl(zeile['datensammlungen']):>11} "
            f"{_zahl(zeile['ladbar']):>7} {_zahl(zeile['geladen']):>8} "
            f"{_zahl(zeile['datentabellen']):>9} {_zahl(zeile['datenzeilen']):>14} "
            f"{mb:>9.1f}"
        )
        for feld in ("datensaetze", "datensammlungen", "ladbar", "geladen",
                     "datentabellen", "datenzeilen"):
            summe[feld] += zeile[feld] or 0
        summe["mb"] += mb

        for typ, grad, anzahl in verbindung.execute(
            "SELECT typ, schweregrad, COUNT(*) FROM quality_check GROUP BY 1, 2"
        ):
            befunde[(typ, grad)] += anzahl

        # Nur der juengste Lauf zaehlt. Ein abgebrochener Lauf von heute
        # frueh laesst seine Zeile mit abgeschlossen = 0 stehen; sie sagt
        # nichts darueber, ob die Datei jetzt fertig ist.
        letzter = verbindung.execute(
            "SELECT abgeschlossen FROM aufbau_lauf ORDER BY id DESC LIMIT 1"
        ).fetchone()
        offen = 1 if (letzter and not letzter[0]) else 0
        if offen:
            unvollstaendig.append(datei.stem)
        verbindung.close()

    print("-" * len(kopf))
    print(
        f"{len(dateien)} Organisationen{'':<26} "
        f"{_zahl(summe['datensaetze']):>11} {_zahl(summe['datensammlungen']):>11} "
        f"{_zahl(summe['ladbar']):>7} {_zahl(summe['geladen']):>8} "
        f"{_zahl(summe['datentabellen']):>9} {_zahl(summe['datenzeilen']):>14} "
        f"{summe['mb']:>9.1f}"
    )

    if unvollstaendig:
        print(f"\nNoch im Bau: {', '.join(unvollstaendig)}")

    if argumente.befunde and befunde:
        print("\nQualitaetsbefunde")
        for (typ, grad), anzahl in sorted(befunde.items(), key=lambda p: -p[1]):
            print(f"  {anzahl:>7}  {typ} [{grad}]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
