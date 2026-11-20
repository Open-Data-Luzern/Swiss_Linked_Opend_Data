"""Setzt zurueck, was ein fehlerhafter Lauf halb geladen hat.

    python werkzeuge/nachholen.py --probe   # nur zeigen, was geschehen wuerde
    python werkzeuge/nachholen.py           # zuruecksetzen

Wozu
----
Der Aufbau merkt sich in ``dim_datensammlung.geladen``, was er schon hat, und
ueberspringt es beim naechsten Lauf. Das ist richtig — solange "geladen" auch
"vollstaendig geladen" heisst.

Am 22. September 2026 hiess es das nicht: Eine XLSX-Arbeitsmappe mit mehreren
Blaettern schloss ihre Datei nach dem ersten Blatt, die uebrigen scheiterten.
Die Datensammlung hatte danach **eine** Tabelle, galt als geladen, und ein
zweiter Lauf haette sie nie wieder angefasst.

Dieses Werkzeug setzt genau die betroffenen Datensammlungen zurueck: Es loescht
ihre Datentabellen, raeumt die Verzeichniseintraege ab und setzt geladen = 0.
Der naechste ``aufbauen``-Lauf holt sie vollstaendig nach. Alles, was sauber
geladen ist, bleibt unberuehrt.

Zurueckgesetzt wird eine Datensammlung, wenn zu ihr ein Befund einer der
folgenden Arten steht — das sind die, hinter denen ein Fehler dieses
Werkzeugs und nicht der Quelle stehen kann:

    aufloesen_fehlgeschlagen, laden_fehlgeschlagen, download_fehlgeschlagen

Ein Befund ``nicht_aufloesbar`` bleibt stehen: Er sagt, dass die Datei keine
Tabelle hergibt, und das aendert sich durch einen neuen Versuch nicht.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Wo die Daten liegen, entscheidet SWISS_OGD_WURZEL — dieselbe Variable, die
# auch der Aufbau liest. Ohne sie das Projektverzeichnis. Die Datenbanken
# liegen nicht zwingend beim Quellcode: auf einer kleinen Systemplatte werden
# sie auf einen anderen Traeger gelegt (Entscheid vom 22. September 2026).
WURZEL = Path(os.environ.get("SWISS_OGD_WURZEL", Path(__file__).resolve().parents[1]))
DATENBANKEN = WURZEL / "datenbanken"

#: Befundarten, nach denen ein erneuter Versuch sinnvoll ist.
NACHHOLBAR = ("aufloesen_fehlgeschlagen", "laden_fehlgeschlagen", "download_fehlgeschlagen")


def zuruecksetzen(pfad: Path, *, probe: bool) -> tuple[int, int]:
    """Setzt eine Datenbank zurueck. Gibt (Datensammlungen, Tabellen)."""
    verbindung = sqlite3.connect(pfad, timeout=60)
    verbindung.execute("PRAGMA foreign_keys = OFF")
    platzhalter = ", ".join("?" * len(NACHHOLBAR))

    betroffen = [
        zeile[0]
        for zeile in verbindung.execute(
            f"""SELECT DISTINCT datensammlung_id
                  FROM quality_check
                 WHERE typ IN ({platzhalter})
                   AND datensammlung_id IS NOT NULL""",
            NACHHOLBAR,
        )
    ]
    # Dazu die Organisationen, deren Lauf gar nicht zu Ende kam: dort ist
    # nicht eine Datensammlung betroffen, sondern der Rest der Liste.
    abgebrochen = verbindung.execute(
        "SELECT COUNT(*) FROM quality_check WHERE typ = 'aufbau_abgebrochen'"
    ).fetchone()[0]

    if not betroffen and not abgebrochen:
        verbindung.close()
        return 0, 0

    tabellen = [
        zeile[0]
        for zeile in verbindung.execute(
            "SELECT tabelle FROM daten_tabelle WHERE datensammlung_id IN "
            f"({', '.join('?' * len(betroffen))})",
            betroffen,
        )
    ] if betroffen else []

    if probe:
        verbindung.close()
        return len(betroffen), len(tabellen)

    for tabelle in tabellen:
        verbindung.execute(f'DROP TABLE IF EXISTS "{tabelle}"')
        verbindung.execute("DELETE FROM daten_spalte WHERE tabelle = ?", (tabelle,))
        verbindung.execute("DELETE FROM daten_tabelle WHERE tabelle = ?", (tabelle,))

    if betroffen:
        verbindung.execute(
            "UPDATE dim_datensammlung SET geladen = 0, zeilen = NULL, "
            "bytes_geladen = NULL, geladen_am = NULL "
            f"WHERE id IN ({', '.join('?' * len(betroffen))})",
            betroffen,
        )
        # Die alten Befunde sind abgearbeitet; stehen sie weiter da, zaehlt
        # der naechste Bestand sie ein zweites Mal.
        verbindung.execute(
            f"DELETE FROM quality_check WHERE typ IN ({platzhalter})", NACHHOLBAR
        )
    verbindung.execute("DELETE FROM quality_check WHERE typ = 'aufbau_abgebrochen'")
    verbindung.commit()
    verbindung.execute("VACUUM")
    verbindung.close()
    return len(betroffen), len(tabellen)


def main(argv: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--probe", action="store_true", help="nur zeigen, nichts aendern")
    argumente = zerleger.parse_args(argv)

    dateien = sorted(DATENBANKEN.glob("*.sqlite"))
    if not dateien:
        print(f"Keine Datenbanken in {DATENBANKEN}", file=sys.stderr)
        return 1

    summe_sammlungen = summe_tabellen = 0
    for datei in dateien:
        try:
            sammlungen, tabellen = zuruecksetzen(datei, probe=argumente.probe)
        except sqlite3.Error as fehler:
            print(f"{datei.stem:<50} uebersprungen: {fehler}")
            continue
        if sammlungen or tabellen:
            wort = "zurueckzusetzen" if argumente.probe else "zurueckgesetzt"
            print(f"{datei.stem:<50} {sammlungen:5d} Datensammlungen {wort}, "
                  f"{tabellen} Tabellen geloescht")
        summe_sammlungen += sammlungen
        summe_tabellen += tabellen

    print(f"\n{summe_sammlungen} Datensammlungen, {summe_tabellen} Tabellen")
    if argumente.probe:
        print("Probe — nichts geaendert. Ohne --probe ausfuehren, dann `aufbauen`.")
    else:
        print("Jetzt `python -m swiss_ogd aufbauen --jobs 3` laufen lassen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
