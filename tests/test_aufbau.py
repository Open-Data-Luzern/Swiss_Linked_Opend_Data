"""Die Grenzen — was geladen wird und was nicht."""

from __future__ import annotations

from pathlib import Path

import pytest

from swiss_ogd import aufbau
from swiss_ogd import konfiguration as konf
from swiss_ogd.modelle import Datensammlung


def _sammlung(byte_size=None):
    return Datensammlung(
        id="x--y", datensatz_id="x", titel_de="y", format="CSV",
        url="https://x.ch/y.csv", byte_size=byte_size,
    )


def test_grosse_datei_wird_vor_dem_download_abgewiesen(monkeypatch):
    monkeypatch.setattr(konf, "MAX_BYTES", 300 * 1024**2)
    # Die Aussenhandelsstatistik der Zollverwaltung: 6 GB in einer Datei.
    assert aufbau.ist_zu_gross(_sammlung(6 * 1024**3)) is True
    assert aufbau.ist_zu_gross(_sammlung(10 * 1024**2)) is False


def test_ohne_groessenangabe_entscheidet_erst_der_download(monkeypatch):
    monkeypatch.setattr(konf, "MAX_BYTES", 300 * 1024**2)
    # Der Katalog meldet die Groesse oft nicht. Dann darf hier nichts
    # abgewiesen werden — die Bremse sitzt in netz.datei_holen.
    assert aufbau.ist_zu_gross(_sammlung(None)) is False


def test_ohne_grenze_wird_nichts_abgewiesen(monkeypatch):
    monkeypatch.setattr(konf, "MAX_BYTES", 0)
    assert aufbau.ist_zu_gross(_sammlung(99 * 1024**3)) is False


def test_wenig_platz_stoppt_das_laden(monkeypatch, tmp_path):
    monkeypatch.setattr(konf, "MIN_FREI_BYTES", 5 * 1024**3)
    monkeypatch.setattr(konf, "MAX_DATENBANK_BYTES", 0)

    class Platte:
        free = 1 * 1024**3

    monkeypatch.setattr(aufbau.shutil, "disk_usage", lambda _: Platte)
    grund = aufbau.platz_pruefen(tmp_path / "a.sqlite")
    assert grund is not None and "frei" in grund


def test_zu_grosse_datenbank_stoppt_das_laden(monkeypatch, tmp_path):
    monkeypatch.setattr(konf, "MIN_FREI_BYTES", 0)
    monkeypatch.setattr(konf, "MAX_DATENBANK_BYTES", 1000)
    pfad = tmp_path / "a.sqlite"
    pfad.write_bytes(b"x" * 2000)

    grund = aufbau.platz_pruefen(pfad)
    assert grund is not None and "Datenbank" in grund


def test_genug_platz_laesst_laden(monkeypatch, tmp_path):
    monkeypatch.setattr(konf, "MIN_FREI_BYTES", 1024)
    monkeypatch.setattr(konf, "MAX_DATENBANK_BYTES", 10**9)

    class Platte:
        free = 500 * 1024**3

    monkeypatch.setattr(aufbau.shutil, "disk_usage", lambda _: Platte)
    assert aufbau.platz_pruefen(tmp_path / "fehlt.sqlite") is None
