"""Macht die Tabellen auffindbar: Spaltenprofil, Datenkarte, Volltextindex.

    python werkzeuge/profilieren.py                    # alle Datenbanken
    python werkzeuge/profilieren.py --nur swissmedic
    python werkzeuge/profilieren.py --suche "Bewilligung Kanton"

Das Problem, das dieses Werkzeug loest
--------------------------------------
Eine Datenbank mit zehntausend Tabellen ist fuer ein Sprachmodell so gut wie
leer, solange es nicht **finden** kann, welche Tabelle zu einer Frage passt.
Der Katalog allein reicht dafuer nicht: Er sagt, wie ein Datensatz heisst,
nicht was in seinen Spalten steht.

Drei Stufen, jede deterministisch aus den Daten gerechnet:

1.  **Profil** je Spalte — Typ, Zahl der verschiedenen Werte, Anteil leer,
    Minimum, Maximum und, bei kleiner Kardinalitaet, die Werte selbst.
    Dass eine Spalte `Bewilligung` heisst, sagt wenig; dass darin
    "FZA/VEP Bewilligung" und "Kurzaufenthalter (L)" stehen, entscheidet.
2.  **Datenkarte** je Tabelle — ein Fliesstext aus Titel, Organisation,
    Beschreibung, Spalten und Vokabular.
3.  **Volltextindex** (FTS5, in derselben Datei) ueber die Karten.

Kein Sprachmodell ist daran beteiligt. Die Karte beschreibt, was da ist; sie
behauptet nichts ueber die Zahlen.

Grosse Tabellen werden an einer Stichprobe profiliert; `daten_profil`
vermerkt das in `vollstaendig = 0`, damit niemand eine Stichprobe fuer eine
Zaehlung haelt.
"""

from __future__ import annotations

import argparse
import os
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

# Wo die Daten liegen, entscheidet SWISS_OGD_WURZEL — dieselbe Variable, die
# auch der Aufbau liest. Ohne sie das Projektverzeichnis. Die Datenbanken
# liegen nicht zwingend beim Quellcode: auf einer kleinen Systemplatte werden
# sie auf einen anderen Traeger gelegt (Entscheid vom 22. September 2026).
WURZEL = Path(os.environ.get("SWISS_OGD_WURZEL", Path(__file__).resolve().parents[1]))
DATENBANKEN = WURZEL / "datenbanken"

# Die Datei wird ueber datenbank.oeffnen geoeffnet und nicht ueber sqlite3
# direkt: Dort steht das Schema **und** das Nachtragen von Spalten, die eine
# aeltere Datei noch nicht hat. Wer das Schema hier ein zweites Mal ausfuehrte,
# haette zwei Wahrheiten und eine davon veraltet.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from swiss_ogd import datenbank as _datenbank  # noqa: E402

#: Ab dieser Zeilenzahl wird nur eine Stichprobe geprueft.
STICHPROBE_AB = 200_000
STICHPROBE_ZEILEN = 50_000

#: Bis zu dieser Zahl verschiedener Werte wird das Vokabular mitgeschrieben.
VOKABULAR_BIS = 60
#: So viele Werte hoechstens je Spalte in die Karte.
VOKABULAR_IN_KARTE = 12


def jetzt() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _spalten_der_tabelle(verbindung: sqlite3.Connection, tabelle: str) -> list[tuple[str, str]]:
    return [
        (zeile[1], (zeile[2] or "TEXT").upper())
        for zeile in verbindung.execute(f'PRAGMA table_info("{tabelle}")')
        if zeile[1] != "datensammlung_id"
    ]


def profil_einer_tabelle(
    verbindung: sqlite3.Connection, tabelle: str, zeilen: int
) -> list[tuple]:
    """Profiliert alle Spalten einer Tabelle. Gibt Zeilen fuer daten_profil."""
    vollstaendig = zeilen <= STICHPROBE_AB
    quelle = (
        f'"{tabelle}"'
        if vollstaendig
        else f'(SELECT * FROM "{tabelle}" LIMIT {STICHPROBE_ZEILEN})'
    )
    geprueft = zeilen if vollstaendig else min(zeilen, STICHPROBE_ZEILEN)
    ergebnis: list[tuple] = []

    for name, typ in _spalten_der_tabelle(verbindung, tabelle):
        try:
            anzahl, leer, kleinster, groesster = verbindung.execute(
                f'SELECT COUNT(DISTINCT "{name}"), '
                f'SUM(CASE WHEN "{name}" IS NULL THEN 1 ELSE 0 END), '
                f'MIN("{name}"), MAX("{name}") FROM {quelle}'
            ).fetchone()
        except sqlite3.Error:
            continue

        top = None
        if typ == "TEXT" and anzahl and anzahl <= VOKABULAR_BIS:
            werte = verbindung.execute(
                f'SELECT "{name}", COUNT(*) FROM {quelle} '
                f'WHERE "{name}" IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT ?',
                (VOKABULAR_BIS,),
            ).fetchall()
            top = json.dumps([[str(w), n] for w, n in werte], ensure_ascii=False)

        ergebnis.append(
            (
                tabelle, name, typ, geprueft, 1 if vollstaendig else 0,
                anzahl, (leer or 0) / geprueft if geprueft else None,
                None if kleinster is None else str(kleinster)[:200],
                None if groesster is None else str(groesster)[:200],
                top, jetzt(),
            )
        )
    return ergebnis


def karte_bauen(verbindung: sqlite3.Connection, tabelle: str) -> str:
    """Baut den Fliesstext, an dem eine Tabelle gefunden wird."""
    kopf = verbindung.execute(
        """SELECT h.datensatz, h.organisation, h.datensammlung, h.zeilen,
                  h.spalten, d.beschreibung_de, d.schlagworte, d.thema,
                  d.zeitraum_von, d.zeitraum_bis, d.aktualisierungsintervall
             FROM v_herkunft h
             JOIN dim_datensatz d ON d.id = h.datensatz_id
            WHERE h.tabelle = ?""",
        (tabelle,),
    ).fetchone()
    if not kopf:
        return ""
    (datensatz, organisation, sammlung, zeilen, spalten, beschreibung,
     schlagworte, thema, von, bis, intervall) = kopf

    zeilen_text = [
        f"{datensatz} — {sammlung}",
        f"Organisation: {organisation}",
    ]
    if beschreibung:
        zeilen_text.append(f"Beschreibung: {beschreibung}")
    for feld, etikett in ((thema, "Themen"), (schlagworte, "Schlagworte")):
        try:
            werte = json.loads(feld or "[]")
        except json.JSONDecodeError:
            werte = []
        if werte:
            zeilen_text.append(f"{etikett}: {', '.join(str(w) for w in werte)}")
    if von or bis:
        zeilen_text.append(f"Zeitraum: {von or '?'} bis {bis or '?'}")
    if intervall:
        zeilen_text.append(f"Aktualisierung: {intervall}")
    zeilen_text.append(f"Tabelle {tabelle}: {zeilen} Zeilen, {spalten} Spalten")

    for spalte, typ, top, kleinster, groesster in verbindung.execute(
        """SELECT p.spalte, p.typ, p.top_werte, p.min_wert, p.max_wert
             FROM daten_profil p
            WHERE p.tabelle = ?
            ORDER BY rowid""",
        (tabelle,),
    ):
        urname = verbindung.execute(
            "SELECT name_original FROM daten_spalte WHERE tabelle = ? AND name = ?",
            (tabelle, spalte),
        ).fetchone()
        stueck = f"  {spalte}"
        if urname and urname[0] and urname[0] != spalte:
            stueck += f" ({urname[0]})"
        stueck += f" [{typ}]"
        if top:
            try:
                werte = [w for w, _ in json.loads(top)][:VOKABULAR_IN_KARTE]
            except (json.JSONDecodeError, ValueError):
                werte = []
            if werte:
                stueck += ": " + ", ".join(werte)
        elif typ in ("INTEGER", "REAL") and kleinster is not None:
            stueck += f": {kleinster} bis {groesster}"
        zeilen_text.append(stueck)

    return "\n".join(zeilen_text)


def datenbank_profilieren(pfad: Path, *, neu: bool = False) -> tuple[int, int]:
    verbindung = _datenbank.oeffnen(pfad)

    tabellen = [
        (zeile[0], zeile[1])
        for zeile in verbindung.execute("SELECT tabelle, zeilen FROM daten_tabelle")
    ]
    if not neu:
        schon = {z[0] for z in verbindung.execute("SELECT tabelle FROM datenkarte")}
        tabellen = [t for t in tabellen if t[0] not in schon]

    profiliert = karten = 0
    for tabelle, zeilen in tabellen:
        try:
            zeilen_profil = profil_einer_tabelle(verbindung, tabelle, zeilen or 0)
        except sqlite3.Error:
            continue
        verbindung.execute("DELETE FROM daten_profil WHERE tabelle = ?", (tabelle,))
        verbindung.executemany(
            "INSERT INTO daten_profil VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            zeilen_profil,
        )
        profiliert += len(zeilen_profil)

        karte = karte_bauen(verbindung, tabelle)
        if karte:
            verbindung.execute("DELETE FROM datenkarte WHERE tabelle = ?", (tabelle,))
            verbindung.execute("DELETE FROM datenkarte_fts WHERE tabelle = ?", (tabelle,))
            verbindung.execute(
                "INSERT INTO datenkarte VALUES (?, ?, ?)", (tabelle, karte, jetzt())
            )
            verbindung.execute(
                "INSERT INTO datenkarte_fts (tabelle, karte) VALUES (?, ?)",
                (tabelle, karte),
            )
            karten += 1
        verbindung.commit()

    verbindung.commit()
    verbindung.close()
    return profiliert, karten


def _fts_ausdruck(muster: str) -> str:
    """Verknuepft die Woerter einer Frage mit ODER, nicht mit UND.

    FTS5 verbindet nebeneinander stehende Woerter implizit mit UND. Eine Frage
    wie "Staatsangehoerigkeit Wohnkanton Bewilligung" faellt damit auf null
    Treffer, sobald **ein** Wort fehlt — und das SEM schreibt "Nation" statt
    "Staatsangehoerigkeit". Eine Suchschicht soll aber rangieren, nicht
    ausschliessen: Wer drei von vier Begriffen trifft, ist der beste Treffer,
    nicht gar keiner.

    Enthaelt das Muster bereits FTS-Operatoren, bleibt es unveraendert.
    """
    if any(wort in muster for wort in (" OR ", " AND ", " NOT ", "*", '"')):
        return muster
    woerter = [w for w in "".join(z if z.isalnum() else " " for z in muster).split() if w]
    if not woerter:
        return muster
    return " OR ".join(f'"{w}"' for w in woerter)


def suchen(muster: str, grenze: int = 10) -> None:
    """Sucht ueber alle Datenbanken — das, was ein Chatbot zuerst taete."""
    muster = _fts_ausdruck(muster)
    treffer: list[tuple[float, str, str, str]] = []
    for datei in sorted(DATENBANKEN.glob("*.sqlite")):
        try:
            verbindung = sqlite3.connect(f"file:{datei}?mode=ro", uri=True, timeout=30)
            for tabelle, karte, rang in verbindung.execute(
                "SELECT tabelle, karte, rank FROM datenkarte_fts "
                "WHERE datenkarte_fts MATCH ? ORDER BY rank LIMIT ?",
                (muster, grenze),
            ):
                treffer.append((rang, datei.stem, tabelle, karte.splitlines()[0]))
            verbindung.close()
        except sqlite3.Error:
            continue
    treffer.sort()
    if not treffer:
        print("Kein Treffer. Zuerst profilieren?")
        return
    for rang, organisation, tabelle, kopf in treffer[:grenze]:
        print(f"{rang:8.3f}  {organisation}")
        print(f"          {tabelle}")
        print(f"          {kopf}")


def main(argv: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--nur", nargs="*", help="nur diese Datenbanken")
    zerleger.add_argument("--neu", action="store_true", help="auch schon Profiliertes neu")
    zerleger.add_argument("--suche", help="statt profilieren: im Index suchen")
    argumente = zerleger.parse_args(argv)

    if argumente.suche:
        suchen(argumente.suche)
        return 0

    dateien = sorted(DATENBANKEN.glob("*.sqlite"))
    if argumente.nur:
        gewaehlt = {n.lower() for n in argumente.nur}
        dateien = [d for d in dateien if d.stem.lower() in gewaehlt]
    if not dateien:
        print("Keine Datenbanken gefunden", file=sys.stderr)
        return 1

    summe_profil = summe_karten = 0
    for datei in dateien:
        try:
            profil, karten = datenbank_profilieren(datei, neu=argumente.neu)
        except sqlite3.Error as fehler:
            print(f"{datei.stem:<50} uebersprungen: {fehler}")
            continue
        if karten:
            print(f"{datei.stem:<50} {karten:5d} Karten, {profil:6d} Spaltenprofile")
        summe_profil += profil
        summe_karten += karten

    print(f"\n{summe_karten} Datenkarten, {summe_profil} Spaltenprofile")
    print('Suchen mit: python werkzeuge/profilieren.py --suche "..."')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
