"""Eine heruntergeladene Datei in Zeilen und Spalten aufloesen.

Der Vertrag gegenueber ``datenbank.py`` ist eine einzige Funktion:

    quellen(pfad, format, name) -> Iterator[Tabellenquelle]

Eine Datei kann mehrere Tabellenquellen ergeben: eine XLSX-Arbeitsmappe hat
mehrere Blaetter, ein ZIP-Archiv mehrere Dateien. Jede Quelle wird eine eigene
Tabelle.

Bewusst nichts geraten, was sich pruefen laesst: Kodierung und Trennzeichen
werden gemessen, nicht angenommen, und das Ergebnis der Messung steht
nachher in ``daten_tabelle``.

Abhaengigkeiten sind optional. Fehlt openpyxl, wird keine XLSX-Datei geladen —
und es entsteht ein Qualitaetsbefund, kein Absturz.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import json
import logging
import shutil
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path
from typing import Any

from swiss_ogd import konfiguration as konf

log = logging.getLogger(__name__)

# CSV-Felder koennen sehr lang sein (eingebettete Geometrien). Der Standard
# von 131'072 Zeichen reicht dafuer nicht.
csv.field_size_limit(1 << 27)


class NichtLadbar(RuntimeError):
    """Die Datei laesst sich nicht in Zeilen und Spalten aufloesen."""


@dataclass
class Tabellenquelle:
    """Eine Tabelle in spe: Name, Spaltennamen, Zeilen als Strom."""

    name: str
    spalten: list[str]
    zeilen: Iterator[list[Any]]
    format: str
    quelle_datei: str
    kodierung: str | None = None
    trennzeichen: str | None = None
    #: Wird nach dem Erschoepfen des Stroms geschlossen (Dateihandles).
    aufraeumen: list[Any] = field(default_factory=list)

    def schliessen(self) -> None:
        for gegenstand in self.aufraeumen:
            try:
                gegenstand.close()
            except Exception:  # noqa: BLE001 — Schliessen darf nie den Lauf kosten
                pass


class _Loeschen:
    """Loescht eine Datei, wenn die Quelle geschlossen wird.

    Unter Windows laesst sich eine geoeffnete Datei nicht loeschen. Ein
    entpackter ZIP-Eintrag darf darum erst weg, wenn der Leser ihn
    losgelassen hat — und nicht schon, wenn der Erzeuger weiterlaeuft.
    Darum steht das Loeschen in derselben Liste wie die Dateihandles, hinter
    ihnen, und wird in derselben Reihenfolge abgearbeitet.
    """

    def __init__(self, pfad: Path) -> None:
        self._pfad = pfad

    def close(self) -> None:
        self._pfad.unlink(missing_ok=True)


class _GeteilterSchluss:
    """Schliesst erst, wenn die letzte Quelle losgelassen hat.

    Eine XLSX-Arbeitsmappe liefert je Blatt eine Quelle, aber alle Blaetter
    lesen aus **derselben** geoeffneten Mappe. Wer die Mappe an jede Quelle
    haengt, schliesst sie beim ersten ``schliessen()`` — und jedes weitere
    Blatt scheitert dann mit "Attempt to use ZIP archive that was already
    closed". Am 22. September 2026 kostete das 24 Datensammlungen.
    """

    def __init__(self, gegenstand: Any, anzahl: int) -> None:
        self._gegenstand = gegenstand
        self._offen = anzahl

    def close(self) -> None:
        self._offen -= 1
        if self._offen <= 0:
            self._gegenstand.close()


# ---------------------------------------------------------------------------
# Messen statt raten
# ---------------------------------------------------------------------------


def kodierung_erkennen(pfad: Path, probe_bytes: int = 1 << 16) -> str:
    """Erste Kodierung aus ``KODIERUNGEN``, mit der sich die Probe liest.

    Die Stueckliste (BOM) wird zuerst geprueft, nicht bloss mitprobiert:
    ``utf-8-sig`` liest auch eine Datei **ohne** BOM anstandslos, und wer es
    nur der Reihe nach versucht, meldet fuer jede UTF-8-Datei ``utf-8-sig``.
    Das Ergebnis der Messung steht nachher in ``daten_tabelle`` — es soll dort
    stimmen.
    """
    with pfad.open("rb") as roh:
        probe = roh.read(probe_bytes)
    if probe.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    # Ein am Ende abgeschnittenes Mehrbytezeichen nicht als Fehler werten.
    probe = probe[: len(probe) - 4] if len(probe) == probe_bytes else probe
    for kandidat in konf.KODIERUNGEN:
        if kandidat == "utf-8-sig":
            continue
        try:
            probe.decode(kandidat)
        except UnicodeDecodeError:
            continue
        return kandidat
    return "latin-1"  # kann jedes Byte lesen, verliert nur die Bedeutung


def trennzeichen_erkennen(kopf: str) -> str:
    """Das Zeichen, das die Kopfzeile in die meisten Felder teilt.

    Gezaehlt wird ausserhalb von Anfuehrungszeichen — ein Semikolon in einem
    Titel darf nicht als Trennzeichen durchgehen.
    """
    beste = (0, konf.TRENNZEICHEN[0])
    for kandidat in konf.TRENNZEICHEN:
        in_zitat = False
        anzahl = 0
        for zeichen in kopf:
            if zeichen == '"':
                in_zitat = not in_zitat
            elif zeichen == kandidat and not in_zitat:
                anzahl += 1
        if anzahl > beste[0]:
            beste = (anzahl, kandidat)
    return beste[1]


def _erste_zeile(pfad: Path, kodierung: str) -> str:
    with pfad.open("r", encoding=kodierung, errors="replace", newline="") as datei:
        for zeile in datei:
            if zeile.strip():
                return zeile
    return ""


# ---------------------------------------------------------------------------
# Die einzelnen Formate
# ---------------------------------------------------------------------------


def _aus_csv(pfad: Path, name: str, format_: str) -> Iterator[Tabellenquelle]:
    kodierung = kodierung_erkennen(pfad)
    kopf = _erste_zeile(pfad, kodierung)
    if not kopf:
        raise NichtLadbar("Datei ist leer")
    trenner = "\t" if format_ == "TSV" else trennzeichen_erkennen(kopf)

    datei = pfad.open("r", encoding=kodierung, errors="replace", newline="")
    leser = csv.reader(datei, delimiter=trenner)
    try:
        spalten = next(leser)
    except StopIteration as fehler:
        datei.close()
        raise NichtLadbar("Datei hat keine Kopfzeile") from fehler
    if len(spalten) < 1 or all(not s.strip() for s in spalten):
        datei.close()
        raise NichtLadbar("Kopfzeile ohne Spaltennamen")

    yield Tabellenquelle(
        name=name,
        spalten=spalten,
        zeilen=leser,
        format=format_,
        quelle_datei=pfad.name,
        kodierung=kodierung,
        trennzeichen=trenner,
        aufraeumen=[datei],
    )


def _aus_xlsx(pfad: Path, name: str) -> Iterator[Tabellenquelle]:
    try:
        from openpyxl import load_workbook
    except ImportError as fehler:  # pragma: no cover — haengt an der Umgebung
        raise NichtLadbar("openpyxl fehlt, XLSX nicht ladbar") from fehler

    mappe = load_workbook(pfad, read_only=True, data_only=True)

    # Nicht ``max_row`` fragen, sondern lesen. Im read_only-Modus stammt
    # max_row aus dem <dimension>-Element der Datei; fehlt es oder ist es
    # falsch, meldet openpyxl 1 fuer ein volles Blatt. Ein Blatt deswegen zu
    # ueberspringen waere stiller Datenverlust. Der Preis ist eine Zeile
    # Vorausschau je Blatt.
    fertig: list[tuple[str, list[str], list, Any]] = []
    for blatt in mappe.worksheets:
        strom = blatt.iter_rows(values_only=True)
        try:
            kopf = next(strom)
        except StopIteration:
            continue
        spalten = [str(z) if z is not None else "" for z in kopf]
        if all(not s.strip() for s in spalten):
            continue
        try:
            erste = next(strom)
        except StopIteration:
            continue  # Kopfzeile ohne Daten — kein Blatt, nur eine Ueberschrift
        fertig.append((blatt.title, spalten, list(erste), strom))

    if not fertig:
        mappe.close()
        raise NichtLadbar("Arbeitsmappe ohne gefuellte Blaetter")

    schluss = _GeteilterSchluss(mappe, len(fertig))
    for titel, spalten, erste, strom in fertig:
        eigen = name if len(fertig) == 1 else f"{name}-{titel}"
        yield Tabellenquelle(
            name=eigen,
            spalten=spalten,
            # Die vorausgelesene Zeile gehoert wieder vorne dran.
            zeilen=chain([erste], (list(zeile) for zeile in strom)),
            format="XLSX",
            quelle_datei=f"{pfad.name}#{titel}",
            aufraeumen=[schluss],
        )


def _aus_parquet(pfad: Path, name: str) -> Iterator[Tabellenquelle]:
    try:
        import pyarrow.parquet as pq
    except ImportError as fehler:  # pragma: no cover — haengt an der Umgebung
        raise NichtLadbar("pyarrow fehlt, Parquet nicht ladbar") from fehler

    datei = pq.ParquetFile(pfad)
    spalten = list(datei.schema_arrow.names)

    def zeilen() -> Iterator[list[Any]]:
        for stapel in datei.iter_batches(batch_size=10_000):
            spaltenweise = [s.to_pylist() for s in stapel.columns]
            for nummer in range(stapel.num_rows):
                yield [s[nummer] for s in spaltenweise]

    yield Tabellenquelle(
        name=name,
        spalten=spalten,
        zeilen=zeilen(),
        format="PARQUET",
        quelle_datei=pfad.name,
    )


def _json_zeilen(gegenstand: Any) -> list[dict[str, Any]] | None:
    """Findet die Liste flacher Objekte in einer JSON-Struktur.

    Erkannt werden drei verbreitete Formen: eine Liste von Objekten, ein
    GeoJSON-FeatureCollection und ein Objekt mit genau einer Liste darin.
    Alles andere ist nicht tabellarisch.
    """
    if isinstance(gegenstand, list):
        objekte = [e for e in gegenstand if isinstance(e, dict)]
        return objekte if len(objekte) == len(gegenstand) and objekte else None

    if isinstance(gegenstand, dict):
        if gegenstand.get("type") == "FeatureCollection":
            zeilen = []
            for merkmal in gegenstand.get("features") or []:
                if not isinstance(merkmal, dict):
                    continue
                zeile = dict(merkmal.get("properties") or {})
                geometrie = merkmal.get("geometry") or {}
                zeile["geometrie_typ"] = (geometrie or {}).get("type")
                zeile["geometrie_json"] = json.dumps(geometrie, ensure_ascii=False)
                zeilen.append(zeile)
            return zeilen or None
        listen = [w for w in gegenstand.values() if isinstance(w, list)]
        if len(listen) == 1:
            return _json_zeilen(listen[0])
    return None


def _aus_json(pfad: Path, name: str, format_: str) -> Iterator[Tabellenquelle]:
    kodierung = kodierung_erkennen(pfad)

    if format_ in ("NDJSON", "JSONL"):
        objekte = []
        with pfad.open("r", encoding=kodierung, errors="replace") as datei:
            for zeile in datei:
                zeile = zeile.strip()
                if not zeile:
                    continue
                try:
                    eintrag = json.loads(zeile)
                except json.JSONDecodeError:
                    continue
                if isinstance(eintrag, dict):
                    objekte.append(eintrag)
    else:
        with pfad.open("r", encoding=kodierung, errors="replace") as datei:
            anfang = datei.read(400).lstrip()
            datei.seek(0)
            if anfang[:1] == "<":
                # Verbreitet: Der Katalog nennt JSON, der Server liefert eine
                # HTML-Seite. Am 22. September 2026 waren so gut 400 Eintraege
                # katalogisiert, unter anderem Kategorieseiten von Wikimedia
                # Commons. Das ist ein Befund ueber den Katalog, kein
                # Lesefehler — und die Meldung soll das auch sagen.
                raise NichtLadbar(
                    "Der Katalog nennt JSON, die Datei ist aber HTML oder XML"
                )
            try:
                gegenstand = json.load(datei)
            except json.JSONDecodeError as fehler:
                raise NichtLadbar(f"JSON nicht lesbar: {fehler}") from fehler
        objekte = _json_zeilen(gegenstand) or []

    if not objekte:
        raise NichtLadbar("JSON enthaelt keine Liste flacher Objekte")

    spalten: list[str] = []
    for eintrag in objekte:
        for schluessel in eintrag:
            if schluessel not in spalten:
                spalten.append(schluessel)

    def flach(wert: Any) -> Any:
        if isinstance(wert, (dict, list)):
            return json.dumps(wert, ensure_ascii=False)
        return wert

    yield Tabellenquelle(
        name=name,
        spalten=spalten,
        zeilen=([flach(e.get(s)) for s in spalten] for e in objekte),
        format=format_,
        quelle_datei=pfad.name,
        kodierung=kodierung,
    )


def _ohne_namensraum(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _xml_satzart(pfad: Path) -> tuple[str | None, list[str]]:
    """Findet das sich wiederholende Element und seine Felder.

    Ein XML ist genau dann tabellarisch, wenn ein Elementname vielfach
    vorkommt und seine Kinder flach sind. Gesucht wird der haeufigste solche
    Name; die Spalten sind die Vereinigung seiner Attribute und direkten
    Kindelemente ueber die ganze Datei — nicht bloss ueber die ersten Zeilen,
    sonst fehlte eine Spalte, die erst spaet zum ersten Mal auftaucht.
    """
    haeufigkeit: dict[str, int] = {}
    felder: dict[str, list[str]] = {}
    for ereignis, element in ET.iterparse(pfad, events=("end",)):
        if ereignis != "end":
            continue
        tag = _ohne_namensraum(element.tag)
        kinder = list(element)
        # Ein Satz hat Attribute oder Kinder, aber keine Enkel.
        if not element.attrib and not kinder:
            continue
        if any(len(kind) for kind in kinder):
            continue
        haeufigkeit[tag] = haeufigkeit.get(tag, 0) + 1
        bekannt = felder.setdefault(tag, [])
        for schluessel in element.attrib:
            if schluessel not in bekannt:
                bekannt.append(schluessel)
        for kind in kinder:
            kindname = _ohne_namensraum(kind.tag)
            if kindname not in bekannt:
                bekannt.append(kindname)
        element.clear()

    kandidaten = [(anzahl, tag) for tag, anzahl in haeufigkeit.items() if anzahl >= 2]
    if not kandidaten:
        return None, []
    tag = max(kandidaten)[1]
    return tag, felder[tag]


def _aus_xml(pfad: Path, name: str) -> Iterator[Tabellenquelle]:
    tag, spalten = _xml_satzart(pfad)
    if not tag or not spalten:
        raise NichtLadbar("XML hat keine sich wiederholende flache Satzart")

    def zeilen() -> Iterator[list[Any]]:
        strom = ET.iterparse(pfad, events=("start", "end"))
        _, wurzel = next(strom)
        for ereignis, element in strom:
            if ereignis != "end" or _ohne_namensraum(element.tag) != tag:
                continue
            satz: dict[str, Any] = dict(element.attrib)
            for kind in element:
                satz[_ohne_namensraum(kind.tag)] = (kind.text or "").strip() or None
            yield [satz.get(s) for s in spalten]
            wurzel.clear()

    yield Tabellenquelle(
        name=name,
        spalten=spalten,
        zeilen=zeilen(),
        format="XML",
        quelle_datei=pfad.name,
    )


def _aus_zip(pfad: Path, name: str, arbeit: Path) -> Iterator[Tabellenquelle]:
    try:
        archiv = zipfile.ZipFile(pfad)
    except zipfile.BadZipFile as fehler:
        raise NichtLadbar("ZIP-Archiv nicht lesbar") from fehler

    eintraege = [
        e
        for e in archiv.namelist()
        if not e.endswith("/")
        and e.rsplit(".", 1)[-1].lower() in konf.ARCHIV_ENDUNGEN
        and "__MACOSX" not in e
    ]
    if not eintraege:
        archiv.close()
        raise NichtLadbar("ZIP-Archiv ohne tabellarische Eintraege")

    # Kurzer Verzeichnisname aus dem Streuwert, nicht aus dem Namen: Eine
    # Datensammlungs-ID ist gut 140 Zeichen lang, und mit dem Arbeitspfad und
    # dem Eintragsnamen darin reisst das die Windows-Grenze von 260 Zeichen.
    # Am 22. September 2026 kostete das zwei Archive des BABS.
    kurz = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    entpackt = arbeit / f"zip-{kurz}"
    entpackt.mkdir(parents=True, exist_ok=True)
    try:
        for eintrag in eintraege:
            end = eintrag.rsplit(".", 1)[-1].upper()
            stamm = Path(eintrag).stem
            eigen = name if len(eintraege) == 1 else f"{name}-{stamm}"
            ziel = entpackt / Path(eintrag).name
            with archiv.open(eintrag) as quelle, ziel.open("wb") as senke:
                while True:
                    block = quelle.read(1 << 20)
                    if not block:
                        break
                    senke.write(block)
            try:
                erzeugt = False
                for tabelle in quellen(ziel, end, eigen, arbeit):
                    tabelle.quelle_datei = f"{pfad.name}!{eintrag}"
                    tabelle.aufraeumen.append(_Loeschen(ziel))
                    erzeugt = True
                    yield tabelle
                if not erzeugt:
                    ziel.unlink(missing_ok=True)
            except NichtLadbar as fehler:
                log.info("ZIP-Eintrag %s uebersprungen: %s", eintrag, fehler)
                ziel.unlink(missing_ok=True)
    finally:
        archiv.close()
        # Was der Leser nicht geschlossen hat, faellt hier weg; noch offene
        # Dateien bleiben unter Windows liegen und stoeren nicht.
        shutil.rmtree(entpackt, ignore_errors=True)


# ---------------------------------------------------------------------------
# Vertrag
# ---------------------------------------------------------------------------


def ist_tabellarisch(format_: str | None) -> bool:
    """Wahr, wenn aus diesem Format eine Tabelle entstehen kann."""
    if not format_:
        return False
    oben = format_.upper()
    return oben in konf.TABELLARISCHE_FORMATE or oben in konf.ARCHIV_FORMATE


def quellen(pfad: Path, format_: str, name: str, arbeit: Path) -> Iterator[Tabellenquelle]:
    """Loest ``pfad`` in Tabellenquellen auf.

    Wirft ``NichtLadbar``, wenn das Format nicht tabellarisch ist oder die
    Datei sich nicht aufloesen laesst. Das ist kein Fehler des Laufs, sondern
    ein Befund.
    """
    oben = (format_ or "").upper()
    if oben in ("CSV", "TSV", "TXT"):
        yield from _aus_csv(pfad, name, oben)
    elif oben in ("XLSX", "XLSB"):
        yield from _aus_xlsx(pfad, name)
    elif oben == "PARQUET":
        yield from _aus_parquet(pfad, name)
    elif oben in ("JSON", "GEOJSON", "NDJSON", "JSONL"):
        yield from _aus_json(pfad, name, oben)
    elif oben == "XML":
        yield from _aus_xml(pfad, name)
    elif oben == "ZIP":
        yield from _aus_zip(pfad, name, arbeit)
    else:
        raise NichtLadbar(f"Format {format_ or '(ohne)'} ist nicht tabellarisch")
