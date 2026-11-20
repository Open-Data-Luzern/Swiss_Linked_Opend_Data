"""Die Werkzeuge — die Logik darin, die sich ohne Datenbank pruefen laesst."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]


def _laden(name: str):
    pfad = WURZEL / "werkzeuge" / f"{name}.py"
    spezifikation = importlib.util.spec_from_file_location(f"werkzeuge_{name}", pfad)
    modul = importlib.util.module_from_spec(spezifikation)
    sys.modules[spezifikation.name] = modul
    spezifikation.loader.exec_module(modul)
    return modul


@pytest.fixture(scope="module")
def profilieren():
    return _laden("profilieren")


def test_frage_wird_mit_oder_verknuepft(profilieren):
    # FTS5 verbindet Woerter implizit mit UND. Eine Frage faellt damit auf
    # null Treffer, sobald ein Wort fehlt — das SEM schreibt "Nation" statt
    # "Staatsangehoerigkeit". Rangieren, nicht ausschliessen.
    assert (
        profilieren._fts_ausdruck("Staatsangehoerigkeit Wohnkanton")
        == '"Staatsangehoerigkeit" OR "Wohnkanton"'
    )


def test_satzzeichen_brechen_den_ausdruck_nicht(profilieren):
    # Ein Fragezeichen oder Komma darf FTS5 nicht mit einem Syntaxfehler
    # umbringen.
    assert profilieren._fts_ausdruck("Wie viele, in Zuerich?") == (
        '"Wie" OR "viele" OR "in" OR "Zuerich"'
    )


def test_eigene_fts_syntax_bleibt_unangetastet(profilieren):
    for muster in ('"genaue Wendung"', "kanton*", "a AND b", "a OR b"):
        assert profilieren._fts_ausdruck(muster) == muster


def test_leeres_muster_bleibt_leer(profilieren):
    assert profilieren._fts_ausdruck("   ") == "   "


def test_nachholbare_befunde_sind_nur_die_eigenen_fehler():
    nachholen = _laden("nachholen")
    # `nicht_aufloesbar` heisst: die Datei gibt keine Tabelle her. Ein neuer
    # Versuch aendert daran nichts und gehoert darum nicht in die Liste.
    assert "nicht_aufloesbar" not in nachholen.NACHHOLBAR
    assert "aufloesen_fehlgeschlagen" in nachholen.NACHHOLBAR
