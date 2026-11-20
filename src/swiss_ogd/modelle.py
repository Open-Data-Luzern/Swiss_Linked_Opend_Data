"""Geteilter Vertrag fuer das zweistufige Katalogmodell.

Dieselben zwei Ebenen wie im LU Datenportal, konsequent getrennt:

*   ``Datensatz``     — der Katalogeintrag einer Dienststelle (DCAT Dataset)
*   ``Datensammlung`` — die einzelne Datei darin (DCAT Distribution)

Nie "Ressource", nie "Dataset" im deutschen Text.

Dieses Modul ist die einzige Definition der Struktur. ``katalog.py`` baut sie
aus den CKAN-Paketen, ``datenbank.py`` schreibt sie nach ``dim_datensatz`` und
``dim_datensammlung``.

Bewusst nur Standardbibliothek: Dev-Bedingung "Limit Libraries" aus dem
Strategie-Meeting vom 23. September 2026. Wo das LU Datenportal pydantic
verwendet, stehen hier dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

Schweregrad = Literal["info", "warnung", "fehler"]

#: Wie eine Datensammlung erreichbar ist.
ZUGANG = ("direkt", "geodatenshop", "handbezug")

#: Wie eine Datensammlung in die Datenbank gekommen ist.
HERKUNFT_ART = ("automatisch", "handbezug", "geodatenshop")


@dataclass(slots=True)
class Organisation:
    """Eine Organisation auf opendata.swiss.

    ``ist_oberorganisation`` unterscheidet die 85 Organisationen der obersten
    Ebene von ihren Unterorganisationen. Je Oberorganisation entsteht genau
    eine Datenbankdatei; die Unterorganisationen stehen darin als Zeilen mit
    ``eltern_name``, nicht als eigene Datei.
    """

    name: str
    titel_de: str
    beschreibung_de: str = ""
    ist_oberorganisation: bool = True
    eltern_name: str | None = None
    opendata_url: str | None = None
    anzahl_datensaetze: int = 0


@dataclass(slots=True)
class Datensammlung:
    """Eine einzelne Datei eines Datensatzes (DCAT Distribution)."""

    id: str
    datensatz_id: str
    titel_de: str
    beschreibung_de: str = ""
    format: str | None = None
    url: str = ""
    byte_size: int | None = None
    lizenz: str | None = None
    zeitliche_aufloesung: str | None = None
    feldbeschreibung_url: str | None = None
    zugang: str = "direkt"
    verfuegbar: bool = True
    md5: str | None = None
    stand: str | None = None

    @property
    def herkunft_art(self) -> str:
        """Abgeleitet, nie gepflegt — die Angabe kann nicht von der Wahrheit
        abweichen, weil sie aus ``zugang`` folgt."""
        if self.zugang == "handbezug":
            return "handbezug"
        if self.zugang == "geodatenshop":
            return "geodatenshop"
        return "automatisch"


@dataclass(slots=True)
class Datensatz:
    """Der Katalogeintrag einer Dienststelle (DCAT Dataset)."""

    id: str
    slug: str
    titel_de: str
    organisation: str
    organisation_name: str
    beschreibung_de: str = ""
    herausgeber: str | None = None
    thema: list[str] = field(default_factory=list)
    schlagworte: list[str] = field(default_factory=list)
    lizenz: str | None = None
    lizenz_text: str | None = None
    kontakt: str | None = None
    veroeffentlicht: str | None = None
    aktualisiert: str | None = None
    aktualisierungsintervall: str | None = None
    zeitraum_von: str | None = None
    zeitraum_bis: str | None = None
    raum: str | None = None
    landingpage: str | None = None
    opendata_url: str | None = None
    identifier: str | None = None
    dokumentation: list[str] = field(default_factory=list)
    i14y_uri: str | None = None


@dataclass(slots=True)
class Katalog:
    """Der geerntete Katalog einer Oberorganisation."""

    organisation: str
    geerntet_am: str
    quelle: str
    organisationen: list[Organisation] = field(default_factory=list)
    datensaetze: list[Datensatz] = field(default_factory=list)
    datensammlungen: list[Datensammlung] = field(default_factory=list)

    def datensammlungen_von(self, datensatz_id: str) -> list[Datensammlung]:
        return [d for d in self.datensammlungen if d.datensatz_id == datensatz_id]


@dataclass(slots=True)
class Qualitaetsbefund:
    """Ein Befund, Zielform der Tabelle ``quality_check``."""

    typ: str
    meldung: str
    schweregrad: Schweregrad = "warnung"
    datensammlung_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Ladeergebnis:
    """Was beim Laden einer Datensammlung herausgekommen ist.

    ``tabellen`` ist eine Liste, weil ein ZIP-Archiv mehrere tabellarische
    Dateien enthalten kann — jede wird eine eigene Tabelle.
    """

    datensammlung_id: str
    geladen: bool
    tabellen: list[str] = field(default_factory=list)
    zeilen: int = 0
    bytes_geladen: int = 0
    befunde: list[Qualitaetsbefund] = field(default_factory=list)


def als_dict(gegenstand: Any) -> dict[str, Any]:
    """dataclass -> dict, fuer die JSON-Ablage des Katalogs."""
    return asdict(gegenstand)
