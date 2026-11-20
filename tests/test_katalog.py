"""Abbildung CKAN -> Katalogmodell, ohne Netz."""

from __future__ import annotations

import pytest

from swiss_ogd import katalog
from swiss_ogd.modelle import Organisation


def test_slug_transliteriert_umlaute():
    assert katalog.slug("Fruchtfolgeflächen") == "fruchtfolgeflaechen"
    assert katalog.slug("Zürich / Stadt") == "zuerich-stadt"


def test_sprachtext_nimmt_deutsch_und_faellt_zurueck():
    assert katalog.sprachtext({"de": "Titel", "fr": "Titre"}) == "Titel"
    assert katalog.sprachtext({"de": "", "fr": "Titre"}) == "Titre"
    assert katalog.sprachtext("schlicht") == "schlicht"
    assert katalog.sprachtext(None) == ""


def test_sprachtext_liest_auch_das_als_zeichenkette_verpackte_objekt():
    # group_tree liefert title als Zeichenkette, die ein Objekt enthaelt.
    verpackt = '{"de": "Eidgenoessische Elektrizitaetskommission ElCom", "en": "ElCom"}'
    assert katalog.sprachtext(verpackt) == "Eidgenoessische Elektrizitaetskommission ElCom"
    # Eine Zeichenkette, die nur aussieht wie ein Objekt, bleibt, was sie ist.
    assert katalog.sprachtext("{kein json}") == "{kein json}"


def test_zweig_setzt_den_titel_und_nicht_das_json():
    knoten = {"name": "elcom", "title": '{"de": "ElCom", "fr": "ElCom FR"}'}
    (organisation,) = katalog._zweig(knoten, eltern=None, oberste=True)
    assert organisation.titel_de == "ElCom"


def test_datum_schneidet_zeitstempel_und_weist_muell_ab():
    assert katalog.datum("2026-09-22T10:11:12Z") == "2026-09-22"
    assert katalog.datum("22.09.2026") is None
    assert katalog.datum(None) is None


def test_format_wird_an_der_endung_verfeinert():
    # CKAN meldet fuer .xlsx pauschal XLS — die Endung ist genauer.
    assert katalog.format_verfeinern("XLS", "https://x/y/daten.xlsx") == "XLSX"
    assert katalog.format_verfeinern("CSV", "https://x/y/daten.csv") == "CSV"
    # Ohne bekannte Endung bleibt es beim gemeldeten Format.
    assert katalog.format_verfeinern("WMS", "https://x/wms?service=WMS") == "WMS"


def test_lizenzcode_aus_rechte_url():
    assert katalog.lizenz_code("https://example.org/rights#terms_by") == "terms_by"
    assert katalog.lizenz_code("") is None


@pytest.fixture
def paket() -> dict:
    return {
        "name": "bevoelkerung-nach-alter",
        "title": {"de": "Bevölkerung nach Alter"},
        "description": {"de": "Wohnbevölkerung, jährlich."},
        "organization": {"name": "bfs-unterabteilung", "title": {"de": "BFS Unterabteilung"}},
        "publisher": {"name": {"de": "Bundesamt für Statistik"}},
        "groups": [{"name": "population", "display_name": {"de": "Bevölkerung"}}],
        "keywords": {"de": ["bevoelkerung", "alter"]},
        "contact_points": [{"email": "info@bfs.admin.ch"}],
        "accrual_periodicity": "http://publications.europa.eu/resource/authority/frequency/ANNUAL",
        "issued": "2020-01-01T00:00:00",
        "modified": "2026-09-01T12:00:00",
        "temporals": [{"start_date": "2010-01-01", "end_date": "2025-12-31"}],
        "identifier": "abc@bfs",
        "resources": [
            {
                "title": {"de": "Datei 2026"},
                "download_url": "https://dam.bfs.admin.ch/hub/bev-alter.csv",
                "format": "CSV",
                "rights": "https://example.org/rights#terms_by",
                "byte_size": "4096",
                "modified": "2026-09-01T00:00:00",
            },
            {
                "title": {"de": "Kartendienst"},
                "url": "https://geo.admin.ch/wms",
                "format": "",
            },
        ],
    }


def test_datensatz_traegt_organisation_lizenz_und_intervall(paket):
    datensatz = katalog._datensatz_bauen(paket, "bundesamt-fur-statistik-bfs")

    assert datensatz.id == "bundesamt-fur-statistik-bfs-bevoelkerung-nach-alter"
    assert datensatz.titel_de == "Bevölkerung nach Alter"
    assert datensatz.organisation == "BFS Unterabteilung"
    assert datensatz.organisation_name == "bfs-unterabteilung"
    assert datensatz.herausgeber == "Bundesamt für Statistik"
    assert datensatz.thema == ["Bevölkerung"]
    assert datensatz.lizenz == "terms_by"
    assert datensatz.lizenz_text == "Freie Nutzung. Quellenangabe ist Pflicht."
    assert datensatz.aktualisierungsintervall == "jaehrlich"
    assert datensatz.zeitraum_von == "2010-01-01"
    assert datensatz.kontakt == "info@bfs.admin.ch"
    assert datensatz.opendata_url.endswith("/bevoelkerung-nach-alter")


def test_datensammlung_ohne_format_gilt_als_verweis(paket):
    datensatz = katalog._datensatz_bauen(paket, "bfs")
    datei = katalog._datensammlung_bauen(paket, paket["resources"][0], datensatz, 1)
    dienst = katalog._datensammlung_bauen(paket, paket["resources"][1], datensatz, 2)

    assert datei.format == "CSV"
    assert datei.verfuegbar is True
    assert datei.zugang == "direkt"
    assert datei.herkunft_art == "automatisch"
    assert datei.byte_size == 4096
    assert datei.datensatz_id == datensatz.id

    # Ein WMS-Endpunkt hat weder Format noch Dateinamen: nur ein Verweis.
    assert dienst.verfuegbar is False
    assert dienst.zugang == "geodatenshop"
    assert dienst.herkunft_art == "geodatenshop"


def test_zweig_kennzeichnet_ober_und_unterorganisationen():
    knoten = {
        "name": "bundesamt-fur-gesundheit-bag",
        "title": {"de": "Bundesamt für Gesundheit BAG"},
        "children": [
            {"name": "abteilung-uebertragbare-krankheiten", "title": {"de": "Abteilung ÜK"}},
        ],
    }
    zweig = katalog._zweig(knoten, eltern=None, oberste=True)

    assert len(zweig) == 2
    assert zweig[0].ist_oberorganisation is True
    assert zweig[0].eltern_name is None
    assert zweig[1].ist_oberorganisation is False
    assert zweig[1].eltern_name == "bundesamt-fur-gesundheit-bag"


def test_organisation_ist_serialisierbar():
    # Der Prozesspool schickt Gruppen an Unterprozesse; sie muessen picklebar sein.
    import pickle

    original = Organisation(name="x", titel_de="X")
    assert pickle.loads(pickle.dumps(original)) == original
