"""Schema, Katalog und Datentabellen — die Schreibseite."""

from __future__ import annotations

import pytest

from swiss_ogd import datenbank
from swiss_ogd.modelle import (
    Datensammlung,
    Datensatz,
    Katalog,
    Organisation,
    Qualitaetsbefund,
)
from swiss_ogd.tabellen import Tabellenquelle


@pytest.fixture
def verbindung(tmp_path):
    con = datenbank.oeffnen(tmp_path / "test.sqlite")
    yield con
    con.close()


@pytest.fixture
def beispielkatalog() -> Katalog:
    datensatz = Datensatz(
        id="bag-fallzahlen",
        slug="fallzahlen",
        titel_de="Fallzahlen",
        organisation="Bundesamt für Gesundheit BAG",
        organisation_name="bundesamt-fur-gesundheit-bag",
        thema=["Gesundheit"],
        lizenz="terms_by",
        lizenz_text="Freie Nutzung. Quellenangabe ist Pflicht.",
    )
    sammlung = Datensammlung(
        id="bag-fallzahlen--datei",
        datensatz_id="bag-fallzahlen",
        titel_de="Fallzahlen 2026",
        format="CSV",
        url="https://bag.admin.ch/f.csv",
    )
    verweis = Datensammlung(
        id="bag-fallzahlen--dienst",
        datensatz_id="bag-fallzahlen",
        titel_de="Kartendienst",
        format=None,
        url="https://bag.admin.ch/wms",
        zugang="geodatenshop",
        verfuegbar=False,
    )
    return Katalog(
        organisation="bundesamt-fur-gesundheit-bag",
        geerntet_am="2026-09-22T00:00:00+00:00",
        quelle="test",
        organisationen=[
            Organisation(
                name="bundesamt-fur-gesundheit-bag",
                titel_de="Bundesamt für Gesundheit BAG",
                anzahl_datensaetze=1,
            ),
            Organisation(
                name="abteilung-uebertragbare-krankheiten",
                titel_de="Abteilung Übertragbare Krankheiten",
                ist_oberorganisation=False,
                eltern_name="bundesamt-fur-gesundheit-bag",
            ),
        ],
        datensaetze=[datensatz],
        datensammlungen=[sammlung, verweis],
    )


def test_schema_ist_idempotent(tmp_path):
    pfad = tmp_path / "zweimal.sqlite"
    datenbank.oeffnen(pfad).close()
    con = datenbank.oeffnen(pfad)  # darf nicht werfen
    tabellen = {z[0] for z in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"dim_datensatz", "dim_datensammlung", "daten_tabelle", "quality_check"} <= tabellen
    con.close()


def test_katalog_schreiben_setzt_ladbar_und_herkunft(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)

    zeilen = dict(
        verbindung.execute("SELECT id, ladbar FROM dim_datensammlung").fetchall()
    )
    assert zeilen["bag-fallzahlen--datei"] == 1
    # Ein blosser Verweis ist nicht ladbar, steht aber im Katalog.
    assert zeilen["bag-fallzahlen--dienst"] == 0

    (art,) = verbindung.execute(
        "SELECT herkunft_art FROM dim_datensammlung WHERE id = 'bag-fallzahlen--dienst'"
    ).fetchone()
    assert art == "geodatenshop"

    (thema, anzahl) = verbindung.execute(
        "SELECT bezeichnung, anzahl_datensaetze FROM dim_thema"
    ).fetchone()
    assert (thema, anzahl) == ("Gesundheit", 1)


def test_katalog_schreiben_ist_idempotent(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    datenbank.katalog_schreiben(verbindung, beispielkatalog)

    (anzahl,) = verbindung.execute("SELECT COUNT(*) FROM dim_datensatz").fetchone()
    assert anzahl == 1


def test_zweiter_lauf_loescht_den_ladezustand_nicht(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    datenbank.ladezustand_setzen(
        verbindung, "bag-fallzahlen--datei", geladen=True, zeilen=7, bytes_geladen=99
    )
    verbindung.commit()

    datenbank.katalog_schreiben(verbindung, beispielkatalog)

    (geladen, zeilen) = verbindung.execute(
        "SELECT geladen, zeilen FROM dim_datensammlung WHERE id = 'bag-fallzahlen--datei'"
    ).fetchone()
    assert (geladen, zeilen) == (1, 7)


# ---------------------------------------------------------------------------
# Typerkennung
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("werte", "erwartet"),
    [
        (["1", "2", "3"], ("INTEGER", False)),
        (["1.5", "2", ""], ("REAL", False)),
        (["1,5", "2", "na"], ("REAL", True)),          # Schweizer Dezimalkomma
        (["1", "zwei"], ("TEXT", False)),
        (["", "", ""], ("TEXT", False)),               # nur Leerwerte: kein Zahlentyp
        ([1, 2, None], ("INTEGER", False)),            # native Werte aus Parquet/XLSX
        ([1.5, 2], ("REAL", False)),
        (["2024-01-01"], ("TEXT", False)),             # ein Datum ist keine Zahl
    ],
)
def test_spaltentyp_wird_gemessen(werte, erwartet):
    assert datenbank._typ_einer_spalte(werte) == erwartet


def test_bezeichner_wird_sql_tauglich():
    assert datenbank.bezeichner("Bevölkerung (Anzahl)") == "bevoelkerung_anzahl"
    assert datenbank.bezeichner("2024") == "spalte_2024"
    assert datenbank.bezeichner("%") == "prozent"
    assert datenbank.bezeichner("") == "spalte"


# ---------------------------------------------------------------------------
# Datentabellen
# ---------------------------------------------------------------------------


def _quelle(name="d", spalten=None, zeilen=None) -> Tabellenquelle:
    return Tabellenquelle(
        name=name,
        spalten=spalten if spalten is not None else ["Jahr", "Gemeinde", "Wert"],
        zeilen=iter(zeilen if zeilen is not None else [["2024", "Luzern", "1,5"]]),
        format="CSV",
        quelle_datei="d.csv",
        kodierung="utf-8",
        trennzeichen=";",
    )


def test_jede_datenzeile_traegt_ihre_herkunft(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    sammlung = beispielkatalog.datensammlungen[0]

    name, zeilen = datenbank.tabelle_anlegen(verbindung, _quelle(), sammlung)

    assert zeilen == 1
    spalten = [z[1] for z in verbindung.execute(f'PRAGMA table_info("{name}")')]
    assert spalten[0] == "datensammlung_id"
    zeile = verbindung.execute(f'SELECT * FROM "{name}"').fetchone()
    assert zeile[0] == sammlung.id
    # Das Dezimalkomma ist in eine echte Zahl gewandelt.
    assert zeile[3] == pytest.approx(1.5)


def test_herkunft_ohne_datensammlung_ist_unmoeglich(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    sammlung = beispielkatalog.datensammlungen[0]
    name, _ = datenbank.tabelle_anlegen(verbindung, _quelle(), sammlung)

    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        verbindung.execute(f'INSERT INTO "{name}" VALUES (NULL, 1, 2, 3)')


def test_doppelte_spaltennamen_werden_eindeutig(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    sammlung = beispielkatalog.datensammlungen[0]

    name, _ = datenbank.tabelle_anlegen(
        verbindung,
        _quelle(spalten=["Wert", "Wert", ""], zeilen=[["1", "2", "3"]]),
        sammlung,
    )

    spalten = [z[1] for z in verbindung.execute(f'PRAGMA table_info("{name}")')]
    assert spalten == ["datensammlung_id", "wert", "wert_2", "spalte_3"]


def test_zwei_tabellen_gleichen_namens_kollidieren_nicht(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    sammlung = beispielkatalog.datensammlungen[0]

    erste, _ = datenbank.tabelle_anlegen(verbindung, _quelle(), sammlung)
    zweite, _ = datenbank.tabelle_anlegen(verbindung, _quelle(), sammlung)

    assert erste != zweite
    assert zweite.endswith("_2")


def test_kurze_und_lange_zeilen_brechen_nicht(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    sammlung = beispielkatalog.datensammlungen[0]

    name, zeilen = datenbank.tabelle_anlegen(
        verbindung,
        _quelle(zeilen=[["2024", "Luzern"], ["2025", "Kriens", "2", "ueberzaehlig"]]),
        sammlung,
    )

    assert zeilen == 2
    werte = verbindung.execute(f'SELECT * FROM "{name}" ORDER BY 2').fetchall()
    assert werte[0][3] is None          # fehlendes Feld wird NULL
    assert len(werte[1]) == 4           # ueberzaehliges Feld wird verworfen


def test_herkunftssicht_verbindet_tabelle_bis_lizenz(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    sammlung = beispielkatalog.datensammlungen[0]
    name, _ = datenbank.tabelle_anlegen(verbindung, _quelle(), sammlung)

    zeile = verbindung.execute(
        "SELECT tabelle, datensatz, organisation, lizenz_text FROM v_herkunft"
    ).fetchone()
    assert zeile[0] == name
    assert zeile[1] == "Fallzahlen"
    assert zeile[2] == "Bundesamt für Gesundheit BAG"
    assert zeile[3].startswith("Freie Nutzung")


def test_nicht_geladene_nennen_ihren_grund(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)

    gruende = dict(
        verbindung.execute("SELECT datensammlung_id, grund FROM v_nicht_geladen").fetchall()
    )
    assert gruende["bag-fallzahlen--dienst"] == "nur als Verweis publiziert"


def test_befund_und_lauf_werden_protokolliert(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    lauf = datenbank.lauf_beginnen(verbindung, "bundesamt-fur-gesundheit-bag")
    datenbank.befund_schreiben(
        verbindung,
        Qualitaetsbefund(
            typ="download_fehlgeschlagen",
            meldung="HTTP 404",
            datensammlung_id="bag-fallzahlen--datei",
            details={"url": "https://bag.admin.ch/f.csv"},
        ),
    )
    datenbank.lauf_beenden(verbindung, lauf, datensaetze=1, tabellen=0, befunde=1)

    (typ, grad) = verbindung.execute(
        "SELECT typ, schweregrad FROM quality_check"
    ).fetchone()
    assert (typ, grad) == ("download_fehlgeschlagen", "warnung")

    (abgeschlossen,) = verbindung.execute(
        "SELECT abgeschlossen FROM aufbau_lauf WHERE id = ?", (lauf,)
    ).fetchone()
    assert abgeschlossen == 1


def test_bestandssicht_zaehlt(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    zeile = verbindung.execute(
        "SELECT organisation, datensaetze, datensammlungen, ladbar FROM v_bestand"
    ).fetchone()
    assert zeile == ("Bundesamt für Gesundheit BAG", 1, 2, 1)


def test_lange_tabellennamen_behalten_ihr_unterscheidendes_ende(verbindung, beispielkatalog):
    datenbank.katalog_schreiben(verbindung, beispielkatalog)
    sammlung = beispielkatalog.datensammlungen[0]
    stamm = "daten-von-human-und-tierarzneimitteln-ogd-ogd-"

    erste, _ = datenbank.tabelle_anlegen(verbindung, _quelle(name=stamm + "packungen"), sammlung)
    zweite, _ = datenbank.tabelle_anlegen(verbindung, _quelle(name=stamm + "praeparate"), sammlung)

    # Nicht durch eine angehaengte Nummer unterschieden, sondern am Inhalt.
    assert not zweite.endswith("_2")
    assert erste.endswith("packungen")
    assert zweite.endswith("praeparate")
