"""Dateien in Zeilen und Spalten aufloesen."""

from __future__ import annotations

import json
import zipfile

import pytest

from swiss_ogd import tabellen


def _schreiben(pfad, text, kodierung="utf-8"):
    pfad.write_bytes(text.encode(kodierung))
    return pfad


def test_trennzeichen_wird_ausserhalb_der_anfuehrungszeichen_gezaehlt():
    # Das Semikolon im Titel darf nicht als Trennzeichen gewinnen.
    kopf = 'jahr,"Gemeinde; Ortsteil",wert'
    assert tabellen.trennzeichen_erkennen(kopf) == ","
    assert tabellen.trennzeichen_erkennen("jahr;gemeinde;wert") == ";"


def test_kodierung_wird_gemessen(tmp_path):
    utf = _schreiben(tmp_path / "u.csv", "jahr;gemeinde\n2024;Zürich\n", "utf-8")
    ansi = _schreiben(tmp_path / "a.csv", "jahr;gemeinde\n2024;Zürich\n", "cp1252")

    assert tabellen.kodierung_erkennen(utf) == "utf-8"
    assert tabellen.kodierung_erkennen(ansi) == "cp1252"


def test_csv_wird_aufgeloest(tmp_path):
    pfad = _schreiben(tmp_path / "d.csv", "jahr;gemeinde;wert\n2024;Luzern;1,5\n2025;Kriens;2,5\n")

    (quelle,) = list(tabellen.quellen(pfad, "CSV", "d", tmp_path))
    assert quelle.spalten == ["jahr", "gemeinde", "wert"]
    assert quelle.trennzeichen == ";"
    assert list(quelle.zeilen) == [["2024", "Luzern", "1,5"], ["2025", "Kriens", "2,5"]]
    quelle.schliessen()


def test_leere_datei_ist_nicht_ladbar(tmp_path):
    pfad = _schreiben(tmp_path / "leer.csv", "")
    with pytest.raises(tabellen.NichtLadbar):
        list(tabellen.quellen(pfad, "CSV", "leer", tmp_path))


def test_nicht_tabellarisches_format_wird_abgewiesen(tmp_path):
    pfad = _schreiben(tmp_path / "x.pdf", "%PDF-1.4")
    with pytest.raises(tabellen.NichtLadbar):
        list(tabellen.quellen(pfad, "PDF", "x", tmp_path))
    assert tabellen.ist_tabellarisch("PDF") is False
    assert tabellen.ist_tabellarisch("CSV") is True
    assert tabellen.ist_tabellarisch("ZIP") is True
    assert tabellen.ist_tabellarisch(None) is False


def test_geojson_wird_zu_zeilen_mit_geometrie(tmp_path):
    inhalt = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Luzern", "einwohner": 82000},
                "geometry": {"type": "Point", "coordinates": [8.3, 47.05]},
            }
        ],
    }
    pfad = _schreiben(tmp_path / "g.geojson", json.dumps(inhalt))

    (quelle,) = list(tabellen.quellen(pfad, "GEOJSON", "g", tmp_path))
    assert quelle.spalten == ["name", "einwohner", "geometrie_typ", "geometrie_json"]
    (zeile,) = list(quelle.zeilen)
    assert zeile[0] == "Luzern"
    assert zeile[2] == "Point"


def test_json_ohne_flache_liste_ist_nicht_ladbar(tmp_path):
    pfad = _schreiben(tmp_path / "n.json", json.dumps({"a": {"b": 1}}))
    with pytest.raises(tabellen.NichtLadbar):
        list(tabellen.quellen(pfad, "JSON", "n", tmp_path))


def test_zip_liefert_je_tabellarischem_eintrag_eine_quelle(tmp_path):
    archiv = tmp_path / "a.zip"
    with zipfile.ZipFile(archiv, "w") as z:
        z.writestr("eins.csv", "a;b\n1;2\n")
        z.writestr("zwei.csv", "c;d\n3;4\n")
        z.writestr("liesmich.pdf", "%PDF")

    quellen = list(tabellen.quellen(archiv, "ZIP", "a", tmp_path))
    assert len(quellen) == 2
    assert {q.name for q in quellen} == {"a-eins", "a-zwei"}
    assert all(q.quelle_datei.startswith("a.zip!") for q in quellen)
    for q in quellen:
        q.schliessen()


def test_zip_ohne_tabellen_ist_nicht_ladbar(tmp_path):
    archiv = tmp_path / "b.zip"
    with zipfile.ZipFile(archiv, "w") as z:
        z.writestr("nur.pdf", "%PDF")
    with pytest.raises(tabellen.NichtLadbar):
        list(tabellen.quellen(archiv, "ZIP", "b", tmp_path))


def test_xlsx_wird_je_blatt_aufgeloest(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")

    mappe = openpyxl.Workbook()
    erstes = mappe.active
    erstes.title = "Bestand"
    erstes.append(["jahr", "wert"])
    erstes.append([2024, 12])
    zweites = mappe.create_sheet("Notizen")
    zweites.append(["bemerkung"])
    zweites.append(["gerundet"])
    pfad = tmp_path / "m.xlsx"
    mappe.save(pfad)

    quellen = list(tabellen.quellen(pfad, "XLSX", "m", tmp_path))
    assert {q.name for q in quellen} == {"m-Bestand", "m-Notizen"}

    # Alle Blaetter lesen aus derselben geoeffneten Mappe. Wird sie beim
    # ersten schliessen() zugemacht, scheitert jedes weitere Blatt mit
    # "Attempt to use ZIP archive that was already closed" — am 22.9.2026
    # kostete genau das 24 Datensammlungen.
    erstes, zweites = quellen
    assert list(erstes.zeilen) == [[2024, 12]]
    erstes.schliessen()
    assert list(zweites.zeilen) == [["gerundet"]]
    zweites.schliessen()


def test_xml_mit_wiederholter_flacher_satzart(tmp_path):
    pfad = _schreiben(
        tmp_path / "x.xml",
        "<Praeparate>"
        "<Praeparat nr='1'><Name>Aspirin</Name><Zulassung>1950</Zulassung></Praeparat>"
        "<Praeparat nr='2'><Name>Dafalgan</Name></Praeparat>"
        "</Praeparate>",
    )

    (quelle,) = list(tabellen.quellen(pfad, "XML", "x", tmp_path))
    assert quelle.spalten == ["nr", "Name", "Zulassung"]
    zeilen = list(quelle.zeilen)
    assert zeilen[0] == ["1", "Aspirin", "1950"]
    # Ein Feld, das nur der erste Satz hat, wird beim zweiten NULL.
    assert zeilen[1] == ["2", "Dafalgan", None]


def test_xml_ohne_wiederholung_ist_nicht_ladbar(tmp_path):
    pfad = _schreiben(tmp_path / "e.xml", "<a><b><c>1</c></b></a>")
    with pytest.raises(tabellen.NichtLadbar):
        list(tabellen.quellen(pfad, "XML", "e", tmp_path))


def test_blatt_mit_nur_einer_ueberschrift_wird_uebergangen(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")

    mappe = openpyxl.Workbook()
    leer = mappe.active
    leer.title = "NurKopf"
    leer.append(["bemerkung"])          # Ueberschrift ohne Daten
    voll = mappe.create_sheet("Daten")
    voll.append(["jahr", "wert"])
    voll.append([2024, 12])
    voll.append([2025, 13])
    pfad = tmp_path / "gemischt.xlsx"
    mappe.save(pfad)

    quellen = list(tabellen.quellen(pfad, "XLSX", "g", tmp_path))

    # Nur das gefuellte Blatt, und weil es allein bleibt ohne Namenszusatz.
    assert len(quellen) == 1
    assert quellen[0].name == "g"
    # Die zur Pruefung vorausgelesene Zeile darf nicht verloren gehen.
    assert list(quellen[0].zeilen) == [[2024, 12], [2025, 13]]
    quellen[0].schliessen()


def test_arbeitsmappe_ganz_ohne_daten_ist_nicht_ladbar(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")

    mappe = openpyxl.Workbook()
    mappe.active.append(["nur", "ueberschriften"])
    pfad = tmp_path / "leer.xlsx"
    mappe.save(pfad)

    with pytest.raises(tabellen.NichtLadbar):
        list(tabellen.quellen(pfad, "XLSX", "l", tmp_path))


def test_als_json_katalogisiertes_html_nennt_den_katalog_als_ursache(tmp_path):
    # Wikimedia-Kategorieseiten stehen im Katalog als JSON und liefern HTML.
    pfad = _schreiben(tmp_path / "s.json", "<!DOCTYPE html>\n<html><body>x</body></html>")

    with pytest.raises(tabellen.NichtLadbar) as fehler:
        list(tabellen.quellen(pfad, "JSON", "s", tmp_path))
    assert "Katalog" in str(fehler.value)
