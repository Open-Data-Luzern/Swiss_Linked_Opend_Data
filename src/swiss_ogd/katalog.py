"""Katalog ernten — Organisationsbaum und die beiden Katalogebenen.

Zwei Schritte:

1.  ``organisationsbaum()`` holt ueber ``group_tree`` die Organisationen der
    obersten Ebene mitsamt ihren Unterorganisationen. Gemessen am
    22. September 2026: 85 Oberorganisationen, 176 Organisationen insgesamt.
2.  ``ernten(oberorganisation)`` fragt ``package_search`` mit einem Filter
    ueber die Oberorganisation **und alle ihre Unterorganisationen** ab und
    bildet die CKAN-Pakete auf ``Datensatz`` und ``Datensammlung`` ab.

Warum der Filter die Kinder einschliesst: Das Bundesamt fuer Gesundheit BAG
haengt seine Datensaetze teils an sich selbst, teils an die Abteilung
Uebertragbare Krankheiten. Eine Datenbank je Oberorganisation muss beide
haben — sonst faende man unter "BAG" nicht, was das BAG publiziert.

Die Abbildung CKAN -> Katalogmodell ist bewusst dieselbe wie im LU
Datenportal (``ingest/src/ogd_ingest/harvest.py``), damit eine Auswertung, die
dort laeuft, auch hier laeuft.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

from swiss_ogd import konfiguration as konf
from swiss_ogd import netz
from swiss_ogd.modelle import Datensammlung, Datensatz, Katalog, Organisation

log = logging.getLogger(__name__)

#: Kalendarisch nicht geprueft, nur die Form YYYY-MM-DD.
_ISO_DATUM = re.compile(r"\d{4}-\d{2}-\d{2}")

#: Transliteration fuer stabile ASCII-Slugs. Schweizer Rechtschreibung: ss.
_UMSCHRIFT = {
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
    "ß": "ss", "à": "a", "á": "a", "â": "a", "è": "e", "é": "e", "ê": "e",
    "ë": "e", "ì": "i", "í": "i", "î": "i", "ï": "i", "ò": "o", "ó": "o",
    "ô": "o", "ù": "u", "ú": "u", "û": "u", "ç": "c", "ñ": "n",
}


# ---------------------------------------------------------------------------
# Reine Hilfsfunktionen
# ---------------------------------------------------------------------------


def slug(text: str) -> str:
    """Kleinbuchstaben, Bindestriche, keine Umlaute.

    Umlaute werden transliteriert (ae, oe, ue), nicht entfernt — damit
    ``Fruchtfolgeflaechen`` und nicht ``Fruchtfolgeflchen`` entsteht.
    """
    umgeschrieben = "".join(_UMSCHRIFT.get(z, z) for z in text)
    zeichen = [z if z.isalnum() and z.isascii() else "-" for z in umgeschrieben.lower()]
    return "-".join(t for t in "".join(zeichen).split("-") if t)


def sprachtext(wert: Any, sprache: str = "de") -> str:
    """Holt den deutschen Text aus einem mehrsprachigen CKAN-Feld.

    Zwei Schreibweisen, dieselbe Sache: ``package_search`` liefert das Feld
    ``title`` als Objekt, ``group_tree`` als **Zeichenkette, die ein Objekt
    enthaelt**. Wer nur die erste behandelt, schreibt in
    ``dim_organisation.titel_de`` den JSON-Text statt des Namens. Gemessen am
    22. September 2026 an ElCom und ZIVI.
    """
    if isinstance(wert, str):
        text = wert.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                zerlegt = json.loads(text)
            except json.JSONDecodeError:
                return text
            if isinstance(zerlegt, dict):
                return sprachtext(zerlegt, sprache)
        return text
    if isinstance(wert, dict):
        for schluessel in (sprache, "de", "en", "fr", "it"):
            text = wert.get(schluessel)
            if isinstance(text, str) and text.strip():
                return text.strip()
        return ""
    return ""


def datum(wert: Any) -> str | None:
    """Schneidet einen ISO-Zeitstempel auf ``YYYY-MM-DD``."""
    text = (wert if isinstance(wert, str) else "").strip()
    if len(text) < 10:
        return None
    kandidat = text[:10]
    return kandidat if _ISO_DATUM.fullmatch(kandidat) else None


def dateiname(url: str) -> str:
    """Letztes Pfadsegment einer URL, ohne Abfrageteil."""
    return urlsplit(url).path.rsplit("/", 1)[-1]


def endung(url: str) -> str:
    name = dateiname(url)
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def format_verfeinern(ckan_format: Any, url: str) -> str | None:
    """Normalisiert das Format und verfeinert es an der Dateiendung.

    CKAN meldet fuer ``.xlsx`` und ``.xlsb`` pauschal ``XLS``. Fuer das Laden
    ist der Unterschied wesentlich: openpyxl liest das eine, nicht das andere.
    """
    roh = (sprachtext(ckan_format) or "").strip().upper()
    end = endung(url)
    if end in konf.BEKANNTE_ENDUNGEN:
        return end.upper()
    return roh or None


def lizenz_code(rechte: Any) -> str | None:
    """Extrahiert den Lizenzcode aus der opendata.swiss-Rechte-URL."""
    text = sprachtext(rechte)
    if not text:
        return None
    return (text.rsplit("#", 1)[-1] or None) if "#" in text else text


# ---------------------------------------------------------------------------
# Organisationsbaum
# ---------------------------------------------------------------------------


def organisationsbaum() -> list[list[Organisation]]:
    """Alle Oberorganisationen, je als Liste [Ober, Unter, Unter, ...].

    Die erste Zeile jeder Liste ist die Oberorganisation; sie bestimmt den
    Dateinamen der Datenbank.
    """
    baum = netz.ckan(konf.ENDPUNKT_ORGANISATIONSBAUM)
    gruppen: list[list[Organisation]] = []
    for knoten in baum:
        gruppen.append(_zweig(knoten, eltern=None, oberste=True))
    return gruppen


def _zweig(knoten: dict[str, Any], *, eltern: str | None, oberste: bool) -> list[Organisation]:
    name = knoten.get("name") or ""
    titel = sprachtext(knoten.get("title")) or sprachtext(knoten.get("display_name")) or name
    hier = Organisation(
        name=name,
        titel_de=titel,
        beschreibung_de=sprachtext(knoten.get("description")),
        ist_oberorganisation=oberste,
        eltern_name=eltern,
        opendata_url=f"{konf.OPENDATA_ORGANISATION_URL}{name}",
    )
    alle = [hier]
    for kind in knoten.get("children") or []:
        alle.extend(_zweig(kind, eltern=name, oberste=False))
    return alle


# ---------------------------------------------------------------------------
# Abbildung CKAN -> Katalogmodell
# ---------------------------------------------------------------------------


def _datensatz_bauen(paket: dict[str, Any], praefix: str) -> Datensatz:
    org = paket.get("organization") or {}
    org_name = org.get("name") or ""
    ckan_name = paket.get("name") or ""

    kontakt = None
    for eintrag in paket.get("contact_points") or []:
        if isinstance(eintrag, dict) and eintrag.get("email"):
            kontakt = eintrag["email"]
            break

    zeitraum = (paket.get("temporals") or [{}])[0] or {}

    lizenzen = Counter(
        code
        for code in (
            lizenz_code(r.get("rights") or r.get("license"))
            for r in paket.get("resources") or []
        )
        if code
    )
    lizenz = lizenzen.most_common(1)[0][0] if lizenzen else lizenz_code(paket.get("license_id"))

    frequenz_uri = sprachtext(paket.get("accrual_periodicity"))
    frequenz_code = frequenz_uri.rsplit("/", 1)[-1] if frequenz_uri else ""
    intervall = konf.FREQUENZEN.get(frequenz_code) or (frequenz_code.lower() or None)

    i14y_uri = None
    for extra in paket.get("extras") or []:
        wert = str(extra.get("value") or "")
        if extra.get("key") == "uri" and wert.startswith("https://register.ld.admin.ch"):
            i14y_uri = wert
            break

    dokumentation: list[str] = []
    for eintrag in paket.get("documentation") or []:
        if isinstance(eintrag, str) and eintrag not in dokumentation:
            dokumentation.append(eintrag)
        elif isinstance(eintrag, dict) and isinstance(eintrag.get("uri"), str):
            if eintrag["uri"] not in dokumentation:
                dokumentation.append(eintrag["uri"])

    return Datensatz(
        id=f"{praefix}-{slug(ckan_name)}",
        slug=ckan_name,
        titel_de=sprachtext(paket.get("title")) or ckan_name,
        beschreibung_de=sprachtext(paket.get("description")),
        organisation=sprachtext(org.get("title")) or org_name,
        organisation_name=org_name,
        herausgeber=sprachtext((paket.get("publisher") or {}).get("name")) or None,
        thema=[
            sprachtext(gruppe.get("display_name")) or gruppe.get("name") or ""
            for gruppe in paket.get("groups") or []
        ],
        schlagworte=list((paket.get("keywords") or {}).get("de") or []),
        lizenz=lizenz,
        lizenz_text=konf.LIZENZTEXTE.get(lizenz or ""),
        kontakt=kontakt,
        veroeffentlicht=datum(paket.get("issued")),
        aktualisiert=datum(paket.get("modified")) or datum(paket.get("metadata_modified")),
        aktualisierungsintervall=intervall,
        zeitraum_von=datum(zeitraum.get("start_date")),
        zeitraum_bis=datum(zeitraum.get("end_date")),
        raum=sprachtext(paket.get("spatial")) or None,
        landingpage=sprachtext(paket.get("url")) or None,
        opendata_url=f"{konf.OPENDATA_DATENSATZ_URL}{ckan_name}",
        identifier=paket.get("identifier") or None,
        dokumentation=dokumentation,
        i14y_uri=i14y_uri,
    )


def _datensammlung_bauen(
    paket: dict[str, Any],
    ressource: dict[str, Any],
    datensatz: Datensatz,
    laufnummer: int,
) -> Datensammlung:
    url = (ressource.get("download_url") or ressource.get("url") or "").strip()
    format_ = format_verfeinern(ressource.get("format"), url)

    # Ohne Format und ohne Dateinamen ist die Datensammlung nur ein Verweis —
    # ein Kartendienst, eine Shop-Seite, eine API. Sie bleibt im Katalog
    # sichtbar, wird aber nie geladen.
    nur_verweis = not format_ and not endung(url)

    stamm = dateiname(url).rsplit(".", 1)[0]
    kern = slug(stamm) or f"teil-{laufnummer}"
    eigen_id = f"{datensatz.id}--{kern}"

    byte_size = ressource.get("byte_size")
    if byte_size in ("", None):
        byte_size = ressource.get("size")
    try:
        byte_size = int(byte_size) if byte_size not in ("", None) else None
    except (TypeError, ValueError):
        byte_size = None

    aufloesung_code = (sprachtext(ressource.get("temporal_resolution")) or "").strip()
    aufloesung = konf.AUFLOESUNGEN.get(aufloesung_code) or (aufloesung_code or None)

    return Datensammlung(
        id=eigen_id,
        datensatz_id=datensatz.id,
        titel_de=(
            sprachtext(ressource.get("title"))
            or sprachtext(ressource.get("name"))
            or kern
        ),
        beschreibung_de=sprachtext(ressource.get("description")),
        format=format_,
        url=url,
        byte_size=byte_size,
        lizenz=lizenz_code(ressource.get("rights") or ressource.get("license")),
        zeitliche_aufloesung=aufloesung,
        feldbeschreibung_url=_feldbeschreibung(paket, ressource, url),
        zugang="geodatenshop" if nur_verweis else "direkt",
        verfuegbar=not nur_verweis,
        md5=(sprachtext(ressource.get("hash")) or "").strip() or None,
        stand=datum(ressource.get("modified")) or datum(ressource.get("last_modified")),
    )


def _feldbeschreibung(paket: dict[str, Any], ressource: dict[str, Any], url: str) -> str | None:
    """Sucht die Feldbeschreibung zur Datei.

    Verbreitete Ablageformen sind ``<stamm>-fields.csv`` und
    ``<stamm>_Meta.csv``. Gewaehlt wird der Kandidat, dessen Stamm der
    laengste Prefix des Dateistamms ist.
    """
    stamm = dateiname(url).rsplit(".", 1)[0].lower().replace("_", "-")
    kandidaten: list[str] = []
    for quelle in (ressource.get("documentation"), paket.get("documentation")):
        for eintrag in quelle or []:
            if isinstance(eintrag, str):
                kandidaten.append(eintrag)
            elif isinstance(eintrag, dict) and isinstance(eintrag.get("uri"), str):
                kandidaten.append(eintrag["uri"])

    beste: tuple[int, str] | None = None
    for kandidat in kandidaten:
        name = dateiname(kandidat).lower()
        if name.endswith("-fields.csv"):
            kern = name[: -len("-fields.csv")]
        elif name.endswith("_meta.csv"):
            kern = name[: -len("_meta.csv")]
        else:
            continue
        kern = kern.replace("_", "-")
        if stamm.startswith(kern) and (beste is None or len(kern) > beste[0]):
            beste = (len(kern), kandidat)
    return beste[1] if beste else None


# ---------------------------------------------------------------------------
# Ernte
# ---------------------------------------------------------------------------


def pakete_holen(organisationen: list[str]) -> list[dict[str, Any]]:
    """Alle CKAN-Pakete der genannten Organisationen, seitenweise."""
    filter_ = "organization:(%s)" % " OR ".join(organisationen)
    pakete: list[dict[str, Any]] = []
    start = 0
    while True:
        url = (
            f"{konf.ENDPUNKT_PAKETSUCHE}?rows={konf.SEITEN_GROESSE}"
            f"&start={start}&fq={quote(filter_)}"
        )
        ergebnis = netz.ckan(url)
        treffer = ergebnis.get("results") or []
        pakete.extend(treffer)
        gesamt = int(ergebnis.get("count") or 0)
        start += konf.SEITEN_GROESSE
        if start >= gesamt or not treffer:
            break
    return pakete


def datensatz_anzahl(gruppe: list[Organisation]) -> int:
    """Wie viele Datensaetze diese Gruppe hat — eine Anfrage, ohne Inhalte.

    ``rows=0`` liefert nur die Trefferzahl. Damit laesst sich der Lauf nach
    Aufwand ordnen, bevor auch nur ein Datensatz geholt ist.
    """
    filter_ = "organization:(%s)" % " OR ".join(o.name for o in gruppe)
    ergebnis = netz.ckan(f"{konf.ENDPUNKT_PAKETSUCHE}?rows=0&fq={quote(filter_)}")
    return int(ergebnis.get("count") or 0)


def ernten(gruppe: list[Organisation]) -> Katalog:
    """Erntet den Katalog einer Oberorganisation samt Unterorganisationen."""
    ober = gruppe[0]
    namen = [o.name for o in gruppe]
    log.info("Ernte %s (%d Organisationen)", ober.name, len(namen))
    pakete = pakete_holen(namen)

    praefix = slug(ober.name)
    datensaetze: list[Datensatz] = []
    datensammlungen: list[Datensammlung] = []
    gesehen: set[str] = set()
    je_organisation: Counter[str] = Counter()

    for paket in pakete:
        datensatz = _datensatz_bauen(paket, praefix)
        if datensatz.id in gesehen:
            continue
        gesehen.add(datensatz.id)
        datensaetze.append(datensatz)
        je_organisation[datensatz.organisation_name] += 1

        eigene: set[str] = set()
        for nummer, ressource in enumerate(paket.get("resources") or [], start=1):
            sammlung = _datensammlung_bauen(paket, ressource, datensatz, nummer)
            # Zwei Ressourcen desselben Datensatzes koennen auf denselben
            # Dateinamen zeigen. Die ID muss trotzdem eindeutig bleiben.
            if sammlung.id in eigene:
                sammlung.id = f"{sammlung.id}-{nummer}"
            eigene.add(sammlung.id)
            datensammlungen.append(sammlung)

    for organisation in gruppe:
        organisation.anzahl_datensaetze = je_organisation.get(organisation.name, 0)

    return Katalog(
        organisation=ober.name,
        geerntet_am=datetime.now(UTC).isoformat(timespec="seconds"),
        quelle=konf.ENDPUNKT_PAKETSUCHE,
        organisationen=list(gruppe),
        datensaetze=datensaetze,
        datensammlungen=datensammlungen,
    )
