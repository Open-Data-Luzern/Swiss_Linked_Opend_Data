"""Die SQLite-Datenbank einer Oberorganisation: Schema, Katalog, Datentabellen.

Alles, was schreibt, steht hier. ``katalog.py`` erntet, ``tabellen.py`` loest
Dateien auf, ``aufbau.py`` orchestriert — geschrieben wird nur in diesem Modul.

Regel "keine Zahl ohne Herkunft": ``tabelle_anlegen`` setzt die Spalte
``datensammlung_id`` als erste Spalte jeder Datentabelle und fuellt sie bei
jeder Zeile. Es gibt keinen Pfad, auf dem eine Datenzeile ohne Herkunft in die
Datenbank kommt.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from itertools import chain
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swiss_ogd import konfiguration as konf
from swiss_ogd.modelle import Datensammlung, Datensatz, Katalog, Qualitaetsbefund
from swiss_ogd.tabellen import Tabellenquelle

log = logging.getLogger(__name__)

SCHEMA_PFAD = Path(__file__).with_name("schema.sql")


class LeereTabelle(ValueError):
    """Die Quelle hat eine Kopfzeile, aber keine Datenzeilen.

    Kein Fehler, sondern eine leere Datei — der Aufrufer erfasst sie als
    Befund mit Schweregrad `info`.
    """

#: Ein Tabellenname darf nicht beliebig lang sein und nur ASCII enthalten.
_MAX_NAME = 55

_NICHT_ALNUM = re.compile(r"[^a-z0-9]+")
_GANZZAHL = re.compile(r"^[+-]?\d+$")
_DEZIMAL_PUNKT = re.compile(r"^[+-]?\d*\.\d+$|^[+-]?\d+\.\d*$")
_DEZIMAL_KOMMA = re.compile(r"^[+-]?\d*,\d+$|^[+-]?\d+,\d*$")

#: Werte, die als "kein Wert" gelten und NULL werden.
_LEER = frozenset({"", "na", "n/a", "nan", "null", "none", "-", "."})


def jetzt() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Verbindung und Schema
# ---------------------------------------------------------------------------


#: Spalten, die spaeter dazugekommen sind. ``CREATE TABLE IF NOT EXISTS``
#: ruehrt eine bestehende Tabelle nicht an — eine im September gebaute Datei
#: bekaeme die Spalte sonst nie und jede Abfrage darauf braeche ab.
_NACHGETRAGENE_SPALTEN = {
    "dim_datensammlung": {"bezogen_von_url": "TEXT"},
}


def _nachtragen(verbindung: sqlite3.Connection) -> None:
    """Ergaenzt Spalten, die eine aeltere Datei noch nicht hat."""
    for tabelle, spalten in _NACHGETRAGENE_SPALTEN.items():
        vorhanden = {
            zeile[1] for zeile in verbindung.execute(f'PRAGMA table_info("{tabelle}")')
        }
        if not vorhanden:
            continue
        for name, typ in spalten.items():
            if name not in vorhanden:
                verbindung.execute(f'ALTER TABLE "{tabelle}" ADD COLUMN "{name}" {typ}')
                log.info("Spalte %s.%s nachgetragen", tabelle, name)


def oeffnen(pfad: Path) -> sqlite3.Connection:
    """Oeffnet die Datenbank, legt das Schema an und traegt fehlende Spalten nach."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    verbindung = sqlite3.connect(pfad, timeout=60)
    verbindung.execute("PRAGMA foreign_keys = ON")
    # Reihenfolge: Schema zuerst, Spalten danach. SQLite prueft den Rumpf
    # einer Sicht beim Anlegen nicht, sondern erst beim Abfragen — die
    # Sichten duerfen darum vor der nachgetragenen Spalte entstehen.
    verbindung.executescript(SCHEMA_PFAD.read_text(encoding="utf-8"))
    _nachtragen(verbindung)
    verbindung.commit()
    return verbindung


def bezeichner(text: str, *, praefix: str = "spalte", max_laenge: int = _MAX_NAME) -> str:
    """Macht aus beliebigem Text einen SQLite-tauglichen Bezeichner."""
    umschrift = {
        "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "ae", "Ö": "oe", "Ü": "ue",
        "ß": "ss", "à": "a", "á": "a", "â": "a", "è": "e", "é": "e",
        "ê": "e", "ë": "e", "ì": "i", "í": "i", "î": "i", "ï": "i",
        "ò": "o", "ó": "o", "ô": "o", "ù": "u", "ú": "u", "û": "u",
        "ç": "c", "ñ": "n", "°": "grad", "%": "prozent",
    }
    umgeschrieben = "".join(umschrift.get(z, z) for z in text)
    sauber = _NICHT_ALNUM.sub("_", umgeschrieben.lower()).strip("_")
    if not sauber:
        return praefix
    if sauber[0].isdigit():
        sauber = f"{praefix}_{sauber}"
    return sauber[:max_laenge]


def _kuerzen(name: str, max_laenge: int) -> str:
    """Kuerzt in der Mitte, nicht am Ende.

    Die Namen der Datentabellen beginnen alle mit demselben Datensatztitel und
    unterscheiden sich erst hinten — beim Namen des Eintrags im ZIP-Archiv.
    Wer hinten abschneidet, macht aus zehn verschiedenen Tabellen zehnmal
    denselben Namen mit angehaengter Nummer. Gemessen am 22. September 2026 am
    Arzneimittelarchiv von Swissmedic.
    """
    if len(name) <= max_laenge:
        return name
    kopf = max_laenge // 2 - 1
    schwanz = max_laenge - kopf - 1
    return f"{name[:kopf]}_{name[-schwanz:]}"


def _eindeutig(vorschlag: str, vergeben: set[str]) -> str:
    if vorschlag not in vergeben:
        vergeben.add(vorschlag)
        return vorschlag
    nummer = 2
    while f"{vorschlag}_{nummer}" in vergeben:
        nummer += 1
    eigen = f"{vorschlag}_{nummer}"
    vergeben.add(eigen)
    return eigen


# ---------------------------------------------------------------------------
# Katalog schreiben
# ---------------------------------------------------------------------------


def katalog_schreiben(verbindung: sqlite3.Connection, katalog: Katalog) -> None:
    """Schreibt Organisationen, Datensaetze, Datensammlungen und Themen.

    Idempotent: ein zweiter Lauf aktualisiert die Katalogfelder und laesst den
    Ladezustand (``geladen``, ``zeilen``) unberuehrt.
    """
    verbindung.executemany(
        """INSERT INTO dim_organisation
             (name, titel_de, beschreibung_de, ist_oberorganisation,
              eltern_name, opendata_url, anzahl_datensaetze)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET
             titel_de = excluded.titel_de,
             beschreibung_de = excluded.beschreibung_de,
             anzahl_datensaetze = excluded.anzahl_datensaetze""",
        [
            (
                o.name, o.titel_de, o.beschreibung_de,
                1 if o.ist_oberorganisation else 0,
                o.eltern_name, o.opendata_url, o.anzahl_datensaetze,
            )
            for o in katalog.organisationen
        ],
    )

    verbindung.executemany(
        """INSERT INTO dim_datensatz
             (id, slug, titel_de, beschreibung_de, organisation,
              organisation_name, herausgeber, thema, schlagworte, lizenz,
              lizenz_text, kontakt, veroeffentlicht, aktualisiert,
              aktualisierungsintervall, zeitraum_von, zeitraum_bis, raum,
              landingpage, opendata_url, identifier, dokumentation, i14y_uri)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             titel_de = excluded.titel_de,
             beschreibung_de = excluded.beschreibung_de,
             aktualisiert = excluded.aktualisiert,
             lizenz = excluded.lizenz,
             lizenz_text = excluded.lizenz_text""",
        [_datensatz_zeile(d) for d in katalog.datensaetze],
    )

    verbindung.executemany(
        """INSERT INTO dim_datensammlung
             (id, datensatz_id, titel_de, beschreibung_de, format, url,
              byte_size, lizenz, zeitliche_aufloesung, feldbeschreibung_url,
              zugang, verfuegbar, md5, stand, herkunft_art, ladbar)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             titel_de = excluded.titel_de,
             format = excluded.format,
             url = excluded.url,
             byte_size = excluded.byte_size,
             stand = excluded.stand,
             ladbar = excluded.ladbar""",
        [_datensammlung_zeile(s) for s in katalog.datensammlungen],
    )

    themen: dict[str, int] = {}
    for datensatz in katalog.datensaetze:
        for thema in datensatz.thema:
            if thema:
                themen[thema] = themen.get(thema, 0) + 1
    verbindung.executemany(
        """INSERT INTO dim_thema (code, bezeichnung, anzahl_datensaetze)
           VALUES (?, ?, ?)
           ON CONFLICT(code) DO UPDATE SET
             anzahl_datensaetze = excluded.anzahl_datensaetze""",
        [(bezeichner(t), t, anzahl) for t, anzahl in themen.items()],
    )
    verbindung.commit()


def _datensatz_zeile(d: Datensatz) -> tuple[Any, ...]:
    return (
        d.id, d.slug, d.titel_de, d.beschreibung_de, d.organisation,
        d.organisation_name, d.herausgeber,
        json.dumps(d.thema, ensure_ascii=False),
        json.dumps(d.schlagworte, ensure_ascii=False),
        d.lizenz, d.lizenz_text, d.kontakt, d.veroeffentlicht, d.aktualisiert,
        d.aktualisierungsintervall, d.zeitraum_von, d.zeitraum_bis, d.raum,
        d.landingpage, d.opendata_url, d.identifier,
        json.dumps(d.dokumentation, ensure_ascii=False), d.i14y_uri,
    )


def _datensammlung_zeile(s: Datensammlung) -> tuple[Any, ...]:
    from swiss_ogd.tabellen import ist_tabellarisch

    return (
        s.id, s.datensatz_id, s.titel_de, s.beschreibung_de, s.format, s.url,
        s.byte_size, s.lizenz, s.zeitliche_aufloesung, s.feldbeschreibung_url,
        s.zugang, 1 if s.verfuegbar else 0, s.md5, s.stand, s.herkunft_art,
        1 if (s.verfuegbar and ist_tabellarisch(s.format)) else 0,
    )


# ---------------------------------------------------------------------------
# Typerkennung
# ---------------------------------------------------------------------------


def _typ_einer_spalte(werte: list[Any]) -> tuple[str, bool]:
    """Liefert (SQLite-Typ, komma_als_dezimaltrennzeichen).

    Gemessen an der Stichprobe: nur wenn **jeder** nicht leere Wert passt,
    bekommt die Spalte einen Zahlentyp. Im Zweifel TEXT — eine Zahl, die als
    Text ankommt, ist ein Schoenheitsfehler; ein stillschweigend verworfener
    Wert waere ein Datenverlust.
    """
    gesehen = False
    ganz = True
    dezimal_punkt = True
    dezimal_komma = True
    for wert in werte:
        if wert is None:
            continue
        if isinstance(wert, bool):
            return "INTEGER", False
        if isinstance(wert, int):
            # Ein nativer Ganzzahlwert (Parquet, XLSX) passt zu allen drei
            # Kandidaten und schliesst keinen aus.
            gesehen = True
            continue
        if isinstance(wert, float):
            gesehen = True
            ganz = False
            dezimal_komma = False
            continue
        text = str(wert).strip()
        if text.lower() in _LEER:
            continue
        gesehen = True
        if not _GANZZAHL.fullmatch(text):
            ganz = False
        if not (_GANZZAHL.fullmatch(text) or _DEZIMAL_PUNKT.fullmatch(text)):
            dezimal_punkt = False
        if not (_GANZZAHL.fullmatch(text) or _DEZIMAL_KOMMA.fullmatch(text)):
            dezimal_komma = False
        if not (ganz or dezimal_punkt or dezimal_komma):
            return "TEXT", False
    if not gesehen:
        return "TEXT", False
    if ganz:
        return "INTEGER", False
    if dezimal_punkt:
        return "REAL", False
    if dezimal_komma:
        return "REAL", True
    return "TEXT", False


def _wandler(typ: str, komma: bool):
    """Gibt die Funktion, die einen Rohwert in den Spaltentyp ueberfuehrt."""

    def als_text(wert: Any) -> Any:
        if wert is None:
            return None
        if isinstance(wert, (int, float, str)):
            text = str(wert)
            return None if text.strip().lower() in _LEER else text
        return str(wert)

    def als_zahl(wert: Any) -> Any:
        if wert is None:
            return None
        if isinstance(wert, (int, float)) and not isinstance(wert, bool):
            return wert
        text = str(wert).strip()
        if text.lower() in _LEER:
            return None
        if komma:
            text = text.replace(",", ".")
        try:
            return int(text) if typ == "INTEGER" else float(text)
        except ValueError:
            return None

    return als_text if typ == "TEXT" else als_zahl


# ---------------------------------------------------------------------------
# Datentabellen
# ---------------------------------------------------------------------------


def _tabellenname(verbindung: sqlite3.Connection, vorschlag: str) -> str:
    voll = bezeichner(vorschlag, praefix="t", max_laenge=1000)
    stamm = f"daten_{_kuerzen(voll, _MAX_NAME)}"
    name = stamm
    nummer = 2
    while verbindung.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone():
        name = f"{stamm}_{nummer}"
        nummer += 1
    return name


def tabelle_anlegen(
    verbindung: sqlite3.Connection,
    quelle: Tabellenquelle,
    datensammlung: Datensammlung,
) -> tuple[str, int]:
    """Legt eine Datentabelle an und fuellt sie. Gibt (Tabellenname, Zeilen).

    Zweistufig: die ersten ``STICHPROBE_ZEILEN`` Zeilen werden gepuffert, um
    die Spaltentypen zu messen; danach laeuft der Rest stroemend durch. Auch
    eine Datei mit Millionen Zeilen liegt so nie ganz im Arbeitsspeicher.
    """
    vergeben: set[str] = {"datensammlung_id"}
    spalten = [
        _eindeutig(bezeichner(name, praefix=f"spalte_{nummer}"), vergeben)
        for nummer, name in enumerate(quelle.spalten, start=1)
    ]
    breite = len(spalten)

    puffer: list[list[Any]] = []
    for zeile in quelle.zeilen:
        puffer.append(list(zeile))
        if len(puffer) >= konf.STICHPROBE_ZEILEN:
            break
    if not puffer:
        raise LeereTabelle("Tabelle ohne Datenzeilen")

    typen: list[str] = []
    wandler = []
    for nummer in range(breite):
        werte = [z[nummer] if nummer < len(z) else None for z in puffer]
        typ, komma = _typ_einer_spalte(werte)
        typen.append(typ)
        wandler.append(_wandler(typ, komma))

    tabelle = _tabellenname(verbindung, quelle.name)
    ddl = ", ".join(f'"{name}" {typ}' for name, typ in zip(spalten, typen, strict=True))
    verbindung.execute(
        f'CREATE TABLE "{tabelle}" ('
        f"datensammlung_id TEXT NOT NULL REFERENCES dim_datensammlung(id), {ddl})"
    )

    platzhalter = ", ".join("?" * (breite + 1))
    einfuegen = f'INSERT INTO "{tabelle}" VALUES ({platzhalter})'

    def aufbereitet(zeilen: Iterator[list[Any]]) -> Iterator[tuple[Any, ...]]:
        for zeile in zeilen:
            # Zu kurze Zeilen werden mit NULL aufgefuellt, zu lange
            # abgeschnitten — beides steht nachher als Befund in quality_check.
            werte = [
                wandler[i](zeile[i]) if i < len(zeile) else None for i in range(breite)
            ]
            yield (datensammlung.id, *werte)

    geschrieben = 0
    stapel: list[tuple[Any, ...]] = []
    # chain, nicht puffer + list(...): der Rest der Datei laeuft stroemend
    # durch und liegt nie als Liste im Arbeitsspeicher.
    for zeile in aufbereitet(chain(puffer, quelle.zeilen)):
        stapel.append(zeile)
        if len(stapel) >= 5_000:
            verbindung.executemany(einfuegen, stapel)
            geschrieben += len(stapel)
            stapel.clear()
    if stapel:
        verbindung.executemany(einfuegen, stapel)
        geschrieben += len(stapel)

    verbindung.execute(
        """INSERT INTO daten_tabelle
             (tabelle, datensammlung_id, datensatz_id, quelle_datei, format,
              zeilen, spalten, kodierung, trennzeichen, geladen_am)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tabelle, datensammlung.id, datensammlung.datensatz_id,
            quelle.quelle_datei, quelle.format, geschrieben, breite,
            quelle.kodierung, quelle.trennzeichen, jetzt(),
        ),
    )
    verbindung.executemany(
        """INSERT INTO daten_spalte (tabelle, position, name, name_original, typ)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (tabelle, nummer, spalten[nummer], str(quelle.spalten[nummer]), typen[nummer])
            for nummer in range(breite)
        ],
    )
    verbindung.commit()
    return tabelle, geschrieben


# ---------------------------------------------------------------------------
# Betrieb
# ---------------------------------------------------------------------------


def befund_schreiben(verbindung: sqlite3.Connection, befund: Qualitaetsbefund) -> None:
    verbindung.execute(
        """INSERT INTO quality_check
             (datensammlung_id, typ, schweregrad, meldung, details_json, geprueft_am)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            befund.datensammlung_id, befund.typ, befund.schweregrad, befund.meldung,
            json.dumps(befund.details, ensure_ascii=False) if befund.details else None,
            jetzt(),
        ),
    )


def ladezustand_setzen(
    verbindung: sqlite3.Connection,
    datensammlung_id: str,
    *,
    geladen: bool,
    zeilen: int,
    bytes_geladen: int,
    bezogen_von_url: str | None = None,
) -> None:
    verbindung.execute(
        """UPDATE dim_datensammlung
              SET geladen = ?, zeilen = ?, bytes_geladen = ?, geladen_am = ?,
                  bezogen_von_url = ?
            WHERE id = ?""",
        (
            1 if geladen else 0, zeilen, bytes_geladen, jetzt(),
            bezogen_von_url, datensammlung_id,
        ),
    )


def lauf_beginnen(verbindung: sqlite3.Connection, organisation: str) -> int:
    zeiger = verbindung.execute(
        """INSERT INTO aufbau_lauf (organisation, version, begonnen_am)
           VALUES (?, ?, ?)""",
        (organisation, konf.VERSION, jetzt()),
    )
    verbindung.commit()
    return int(zeiger.lastrowid or 0)


def lauf_beenden(verbindung: sqlite3.Connection, lauf_id: int, **zahlen: int) -> None:
    verbindung.execute(
        """UPDATE aufbau_lauf
              SET beendet_am = ?, datensaetze = ?, datensammlungen = ?,
                  tabellen = ?, zeilen = ?, bytes_geladen = ?, befunde = ?,
                  abgeschlossen = 1
            WHERE id = ?""",
        (
            jetzt(), zahlen.get("datensaetze", 0), zahlen.get("datensammlungen", 0),
            zahlen.get("tabellen", 0), zahlen.get("zeilen", 0),
            zahlen.get("bytes_geladen", 0), zahlen.get("befunde", 0), lauf_id,
        ),
    )
    verbindung.commit()


def bereits_geladen(verbindung: sqlite3.Connection) -> set[str]:
    """IDs der Datensammlungen, die ein frueherer Lauf schon geladen hat."""
    return {
        zeile[0]
        for zeile in verbindung.execute(
            "SELECT id FROM dim_datensammlung WHERE geladen = 1"
        )
    }


def aufraeumen(verbindung: sqlite3.Connection) -> None:
    """Gibt den Platz frei, den WAL und geloeschte Seiten belegen."""
    verbindung.commit()
    verbindung.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    verbindung.execute("VACUUM")
    verbindung.execute("ANALYZE")
    verbindung.commit()
