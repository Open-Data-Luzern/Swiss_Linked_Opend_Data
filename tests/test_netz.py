"""HTTP-Schicht — die Teile, die ohne Netz pruefbar sind."""

from __future__ import annotations

import time

import pytest

from swiss_ogd import netz


def test_reine_ascii_url_bleibt_unveraendert():
    url = "https://data.geo.admin.ch/ch.babs/kulturgueter_2056.xtf.zip"
    assert netz.ascii_url(url) is url


def test_umlaut_in_der_url_wird_kodiert():
    # Genau dieser Fall riss am 22.9.2026 den Aufbau des BFE ab: urllib wirft
    # UnicodeEncodeError statt zu kodieren.
    assert (
        netz.ascii_url("https://www.bfe.admin.ch/daten/grüne-energie.csv")
        == "https://www.bfe.admin.ch/daten/gr%C3%BCne-energie.csv"
    )


def test_bereits_kodierte_url_wird_nicht_doppelt_kodiert():
    url = "https://x.ch/a%20b.csv?q=%C3%BC"
    assert netz.ascii_url(url) == url


def test_umlaut_in_abfrage_und_fragment():
    kodiert = netz.ascii_url("https://x.ch/a.csv?ort=Zürich#kopf")
    assert kodiert == "https://x.ch/a.csv?ort=Z%C3%BCrich#kopf"


def test_umlaut_im_hostnamen_wird_zu_punycode():
    assert netz.ascii_url("https://münchen.de/a.csv") == "https://xn--mnchen-3ya.de/a.csv"


def test_drossel_haelt_den_abstand_je_host_ein():
    drossel = netz._HostDrossel(abstand_s=0.3)

    beginn = time.monotonic()
    drossel.warten("https://a.ch/x")
    drossel.warten("https://a.ch/y")
    gleicher_host = time.monotonic() - beginn

    beginn = time.monotonic()
    drossel.warten("https://b.ch/x")
    anderer_host = time.monotonic() - beginn

    # Nicht exakt 0.3: Die Uhr von Windows tickt in rund 15 ms, und
    # time.sleep kehrt gemessen an time.monotonic ein paar Millisekunden zu
    # frueh zurueck (gemessen: 0.297). Geprueft wird, dass gewartet wurde,
    # nicht eine Genauigkeit, die die Plattform nicht hergibt.
    assert gleicher_host >= 0.25
    # Ein anderer Host wartet nicht: sonst bremste ein Lauf ueber 85
    # Organisationen jeden Server wegen aller uebrigen.
    assert anderer_host < 0.1


def test_abruffehler_traegt_url_und_status():
    fehler = netz.AbrufFehler("kaputt", url="https://x.ch", status=404)
    assert fehler.url == "https://x.ch"
    assert fehler.status == 404
    assert isinstance(netz.BotErkennung("x", url="y"), netz.AbrufFehler)


def test_wiederholung_gibt_nach_allen_versuchen_auf(monkeypatch):
    monkeypatch.setattr(netz.konf, "VERSUCHE", 3)
    monkeypatch.setattr(netz.konf, "BACKOFF_BASIS", 1.0)
    monkeypatch.setattr(netz.time, "sleep", lambda _: None)
    versuche = []

    def scheitern():
        versuche.append(1)
        raise ConnectionError("weg")

    with pytest.raises(netz.AbrufFehler):
        netz._mit_wiederholung("https://x.ch/a", scheitern)
    assert len(versuche) == 3


# ---------------------------------------------------------------------------
# Ersatz-URL bei veraltetem Katalogeintrag
# ---------------------------------------------------------------------------

SEM = (
    "https://www.sem.admin.ch/dam/sem/de/data/publiservice/statistik/"
    "auslaenderstatistik/2019/csv/2-30-Best-Flu-d-2019.csv.download.csv/"
    "2-30-Best-Flu-d-2019.csv"
)


def test_ersatzvarianten_schreiben_klein_und_lassen_kurze_marker_weg():
    varianten = netz.ersatzvarianten(SEM)

    # Der Name steht in einer DAM-URL zweimal; beide Vorkommen muessen mit.
    assert all(v.count("2-30") == 2 for v in varianten)
    namen = [v.rsplit("/", 1)[-1] for v in varianten]
    assert "2-30-best-flu-d-2019.csv" in namen      # nur kleingeschrieben
    assert "2-30-best-flu-2019.csv" in namen        # zusaetzlich ohne "d"


def test_ersatzvarianten_lassen_nur_kurze_marker_weg():
    namen = [v.rsplit("/", 1)[-1] for v in netz.ersatzvarianten(SEM)]
    # "best" und "flu" sind Woerter, keine Marker — sie wegzulassen ergaebe
    # eine andere Datei, nicht dieselbe anders geschrieben.
    assert not any("best" not in n for n in namen)
    assert not any("flu" not in n for n in namen)


def test_ersatzvarianten_koennen_nie_auf_eine_andere_datensammlung_zeigen():
    # Der franzoesische Eintrag darf niemals die deutsche Datei bekommen.
    franzoesisch = SEM.replace("Best-Flu-d", "Effectif-Refu-f")
    namen = [v.rsplit("/", 1)[-1] for v in netz.ersatzvarianten(franzoesisch)]
    assert all("effectif" in n for n in namen)
    assert not any("best-flu" in n for n in namen)


def test_ohne_dateinamen_gibt_es_keine_varianten():
    assert netz.ersatzvarianten("https://x.ch/dienst?a=1") == []


def test_ersatz_wird_nur_bei_404_versucht(monkeypatch, tmp_path):
    versucht: list[str] = []

    def holen(url, ziel, *, max_bytes=0):
        versucht.append(url)
        raise netz.AbrufFehler("kaputt", url=url, status=500)

    monkeypatch.setattr(netz, "datei_holen", holen)
    with pytest.raises(netz.AbrufFehler):
        netz.datei_holen_mit_ersatz(SEM, tmp_path / "x.csv")
    # Ein 500 ist ein Serverproblem, kein veralteter Name: nicht weitersuchen.
    assert versucht == [SEM]


def test_ersatz_nimmt_die_erste_variante_die_antwortet(monkeypatch, tmp_path):
    gut = SEM.replace("Best-Flu-d-2019", "best-flu-2019").replace(
        "Best-Flu-d-2019", "best-flu-2019"
    )

    def holen(url, ziel, *, max_bytes=0):
        if url.rsplit("/", 1)[-1] == "2-30-best-flu-2019.csv":
            return 4711
        raise netz.AbrufFehler("weg", url=url, status=404)

    monkeypatch.setattr(netz, "datei_holen", holen)
    groesse, verwendet = netz.datei_holen_mit_ersatz(SEM, tmp_path / "x.csv")

    assert groesse == 4711
    assert verwendet.endswith("2-30-best-flu-2019.csv")
    assert verwendet != SEM
