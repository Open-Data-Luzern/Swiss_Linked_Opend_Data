"""Konfiguration des Aufbaus — eine Datei, keine YAML-Abhaengigkeit.

Wer eine Einstellung aendert, aendert sie hier. Der uebrige Code enthaelt
keine Endpunkte, keine Formatlisten und keine Klartexte.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Quelle
# ---------------------------------------------------------------------------

CKAN_BASIS = "https://ckan.opendata.swiss/api/3/action"
ENDPUNKT_ORGANISATIONSBAUM = f"{CKAN_BASIS}/group_tree?type=organization"
ENDPUNKT_PAKETSUCHE = f"{CKAN_BASIS}/package_search"
OPENDATA_DATENSATZ_URL = "https://opendata.swiss/de/dataset/"
OPENDATA_ORGANISATION_URL = "https://opendata.swiss/de/organization/"

#: Ohne aussagekraeftigen User-Agent antwortet opendata.swiss manchen Clients
#: mit einer Bot-Abwehrseite statt mit JSON.
USER_AGENT = "Swiss-OGD-Aufbau/1.0 (nicolas.buerkler@sim-research.ch)"

# ---------------------------------------------------------------------------
# Drosselung
# ---------------------------------------------------------------------------

#: Mindestabstand zweier Anfragen an denselben Host, in Sekunden.
ABSTAND_JE_HOST_S = 1.0
#: Gesamtzahl der Versuche je Anfrage, inklusive Erstversuch.
VERSUCHE = 4
#: Wartezeit vor dem n-ten erneuten Versuch = BACKOFF_BASIS ** n Sekunden.
BACKOFF_BASIS = 2.0
TIMEOUT_S = 120
#: Zeilen je package_search-Anfrage.
SEITEN_GROESSE = 100

#: Statuscodes, bei denen ein erneuter Versuch sinnvoll ist.
WIEDERHOLBARE_CODES = frozenset({408, 425, 429, 500, 502, 503, 504, 522, 524})

# ---------------------------------------------------------------------------
# Welche Formate geladen werden
#
# Entscheid vom 22. September 2026: Nur tabellarische Formate werden
# heruntergeladen. Ein PDF, ein GeoTIFF oder ein WMS-Endpunkt hat keine Zeilen
# und keine Spalten — es gibt nichts, wohin man ihn laden koennte. Solche
# Datensammlungen stehen vollstaendig in dim_datensammlung und tragen einen
# Befund `nicht_tabellarisch` mit Schweregrad `info`. Herunterladen, um die
# Datei nach dem Lauf wieder zu loeschen, waere reine Netzlast.
# ---------------------------------------------------------------------------

#: Formate, aus denen eine Tabelle entstehen kann.
TABELLARISCHE_FORMATE = frozenset(
    {"CSV", "TSV", "TXT", "XLSX", "XLSB", "PARQUET", "JSON", "GEOJSON", "NDJSON", "XML"}
)

#: Archive werden geoeffnet; die tabellarischen Eintraege darin werden geladen.
ARCHIV_FORMATE = frozenset({"ZIP"})

#: Endungen, an denen ein Format verfeinert wird. CKAN meldet fuer .xlsx und
#: .xlsb pauschal XLS — fuer das Laden ist der Unterschied wesentlich.
BEKANNTE_ENDUNGEN = frozenset(
    {
        "csv", "tsv", "txt", "xlsx", "xlsb", "xls", "json", "geojson",
        "ndjson", "jsonl", "parquet", "zip", "xml", "pdf", "html",
    }
)

#: Endungen innerhalb eines ZIP-Archivs, die geladen werden.
ARCHIV_ENDUNGEN = frozenset(
    {"csv", "tsv", "txt", "xlsx", "parquet", "json", "geojson", "xml"}
)

#: Kandidaten fuer die Zeichenkodierung, in dieser Reihenfolge geprueft.
KODIERUNGEN = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

#: Kandidaten fuer das Trennzeichen einer CSV-Datei.
TRENNZEICHEN = (";", ",", "\t", "|")

#: Zeilen, die vor dem Anlegen der Tabelle zur Typerkennung gelesen werden.
STICHPROBE_ZEILEN = 500

# ---------------------------------------------------------------------------
# Grenzen — "lieber unvollstaendig als kaputt"
#
# Entscheid vom 22. September 2026, nach einer vollen Platte: Ein Portal, das
# jede Datei laedt, gibt es hier nicht. Die Eidgenoessische Zollverwaltung
# publiziert ihre Aussenhandelsstatistik mit 29,7 Millionen Zeilen je Datei
# und je Sprache; 40 von 85 Organisationen belegten 75 GB, davon 51 GB nur
# diese eine. Ein lauffaehiges System mit vollstaendigem Katalog und den
# Dateien, die hineinpassen, ist mehr wert als ein vollstaendiges System, das
# die Platte fuellt und dann abbricht.
#
# Drei Grenzen, jede einzeln abschaltbar (0 = keine Grenze). Was an einer
# Grenze scheitert, bleibt im Katalog und steht mit Grund in v_nicht_geladen —
# weggelassen wird nie stillschweigend.
# ---------------------------------------------------------------------------

#: Obergrenze fuer eine einzelne Datei. Wird schon vor dem Herunterladen an
#: der im Katalog gemeldeten Groesse geprueft und beim Laden noch einmal.
MAX_BYTES = int(os.environ.get("SWISS_OGD_MAX_BYTES", str(300 * 1024**2)))

#: Obergrenze je Organisationsdatenbank. Ist sie erreicht, wird der Katalog
#: fertig geschrieben, aber keine Daten mehr geladen. So kann eine einzelne
#: Organisation nie die ganze Platte belegen.
MAX_DATENBANK_BYTES = int(
    os.environ.get("SWISS_OGD_MAX_DATENBANK_BYTES", str(2 * 1024**3))
)

#: Unterschreitet der freie Platz auf dem Zieltraeger diesen Wert, wird kein
#: Byte mehr geladen. Das ist die Bremse, die am 22. September 2026 gefehlt
#: hat: Die Platte lief voll, und danach scheiterte jede Organisation an
#: "No space left on device", ohne dass jemand es merkte.
MIN_FREI_BYTES = int(os.environ.get("SWISS_OGD_MIN_FREI_BYTES", str(5 * 1024**3)))

# ---------------------------------------------------------------------------
# Klartexte
# ---------------------------------------------------------------------------

#: opendata.swiss liefert nur den Code als URL-Fragment. Der Klartext steht
#: hier, damit jede Auswertung die Lizenz ausweisen kann.
LIZENZTEXTE = {
    "terms_open": "Freie Nutzung.",
    "terms_by": "Freie Nutzung. Quellenangabe ist Pflicht.",
    "terms_ask": (
        "Freie Nutzung. Kommerzielle Nutzung nur mit Bewilligung des "
        "Datenlieferanten zulaessig."
    ),
    "terms_by_ask": (
        "Freie Nutzung. Quellenangabe ist Pflicht. Kommerzielle Nutzung nur "
        "mit Bewilligung des Datenlieferanten zulaessig."
    ),
}

#: EU-Frequenzcode -> deutscher Text.
FREQUENZEN = {
    "ANNUAL": "jaehrlich",
    "ANNUAL_2": "halbjaehrlich",
    "ANNUAL_3": "viermal jaehrlich",
    "BIENNIAL": "zweijaehrlich",
    "TRIENNIAL": "dreijaehrlich",
    "QUADRENNIAL": "vierjaehrlich",
    "QUARTERLY": "quartalsweise",
    "MONTHLY": "monatlich",
    "WEEKLY": "woechentlich",
    "DAILY": "taeglich",
    "CONT": "kontinuierlich",
    "UPDATE_CONT": "laufend aktualisiert",
    "IRREG": "unregelmaessig",
    "NEVER": "nie",
    "UNKNOWN": "unbekannt",
    "OTHER": "anderes",
}

#: ISO-8601-Dauer -> deutscher Text.
AUFLOESUNGEN = {
    "P1Y": "jaehrlich",
    "P6M": "halbjaehrlich",
    "P3M": "quartalsweise",
    "P1M": "monatlich",
    "P1W": "woechentlich",
    "P1D": "taeglich",
    "P2Y": "zweijaehrlich",
    "P3Y": "dreijaehrlich",
    "P4Y": "vierjaehrlich",
}

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

#: Projektwurzel — das Verzeichnis, in dem die Datenbanken liegen.
WURZEL = Path(os.environ.get("SWISS_OGD_WURZEL", Path(__file__).resolve().parents[2]))

#: Hierhin schreibt der Aufbau die Datenbanken, eine je Oberorganisation.
DATENBANK_VERZEICHNIS = WURZEL / "datenbanken"

#: Katalog als JSON je Oberorganisation — die Rohernte, unabhaengig vom Laden.
KATALOG_VERZEICHNIS = WURZEL / "kataloge"

#: Protokolle der Laeufe.
PROTOKOLL_VERZEICHNIS = WURZEL / "protokolle"

#: Arbeitsverzeichnis fuer heruntergeladene Dateien. Sie werden nach dem Laden
#: geloescht (Entscheid vom 22. September 2026: Rohdateien nicht behalten).
ARBEIT_VERZEICHNIS = WURZEL / "arbeit"

VERSION = "1.0"
