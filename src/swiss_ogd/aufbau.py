"""Aufbau der Datenbanken — eine Datei je Oberorganisation.

Datenfluss, ohne Abkuerzung:

    group_tree  ->  85 Gruppen [Oberorganisation, Unterorganisationen...]
      je Gruppe:
        package_search  ->  Katalog (Datensaetze, Datensammlungen)
          ->  kataloge/<org>.json          (Rohernte, unabhaengig vom Laden)
          ->  dim_organisation / dim_datensatz / dim_datensammlung
        je ladbarer Datensammlung:
          herunterladen  ->  arbeit/<org>/<datei>
          aufloesen      ->  Tabellenquellen
          laden          ->  daten_<name>   (mit datensammlung_id je Zeile)
          loeschen       ->  die Rohdatei ist danach weg
        VACUUM

Die Rohdatei wird nach dem Laden geloescht — Entscheid vom 22. September 2026.
Ein erneuter Lauf holt sie wieder; was schon geladen ist, wird uebersprungen.

Jede Organisation ist unabhaengig: ein Fehler bei einer kostet die anderen
nichts, und ``--jobs`` baut mehrere gleichzeitig, weil jede in ihre eigene
Datei schreibt.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from swiss_ogd import datenbank, katalog, netz, tabellen
from swiss_ogd import konfiguration as konf
from swiss_ogd.modelle import Datensammlung, Organisation, Qualitaetsbefund

log = logging.getLogger("swiss_ogd")


@dataclass(slots=True)
class Bilanz:
    """Was ein Lauf fuer eine Organisation erreicht hat."""

    organisation: str
    datensaetze: int = 0
    datensammlungen: int = 0
    tabellen: int = 0
    zeilen: int = 0
    bytes_geladen: int = 0
    befunde: int = 0
    fehler: str | None = None

    @property
    def gelungen(self) -> bool:
        return self.fehler is None


# ---------------------------------------------------------------------------
# Eine Datensammlung
# ---------------------------------------------------------------------------


def _endung_fuer(sammlung: Datensammlung) -> str:
    aus_url = katalog.endung(sammlung.url)
    if aus_url in konf.BEKANNTE_ENDUNGEN:
        return aus_url
    return (sammlung.format or "dat").lower()


def platz_pruefen(pfad: Path) -> str | None:
    """Sagt, warum jetzt nichts mehr geladen werden darf — oder None.

    Drei Gruende, in der Reihenfolge ihrer Endgueltigkeit: zu wenig freier
    Platz auf dem Traeger, Datenbank zu gross, sonst nichts.
    """
    if konf.MIN_FREI_BYTES:
        frei = shutil.disk_usage(pfad.parent).free
        if frei < konf.MIN_FREI_BYTES:
            return (
                f"nur noch {frei / 1024**3:.1f} GB frei, Untergrenze "
                f"{konf.MIN_FREI_BYTES / 1024**3:.1f} GB"
            )
    if konf.MAX_DATENBANK_BYTES and pfad.exists():
        gross = pfad.stat().st_size
        if gross > konf.MAX_DATENBANK_BYTES:
            return (
                f"Datenbank bei {gross / 1024**3:.1f} GB, Obergrenze "
                f"{konf.MAX_DATENBANK_BYTES / 1024**3:.1f} GB"
            )
    return None


def ist_zu_gross(sammlung: Datensammlung) -> bool:
    """Wahr, wenn der Katalog die Datei schon als zu gross meldet.

    Geprueft **vor** dem Herunterladen: Eine 6-GB-Datei erst zu holen und dann
    zu verwerfen waere die Netzlast, die die Grenze gerade vermeiden soll.
    Fehlt die Angabe, entscheidet die Bremse in netz.datei_holen.
    """
    return bool(
        konf.MAX_BYTES and sammlung.byte_size and sammlung.byte_size > konf.MAX_BYTES
    )


def datensammlung_laden(
    verbindung,
    sammlung: Datensammlung,
    arbeit: Path,
) -> tuple[int, int, int, list[Qualitaetsbefund], str]:
    """Laedt eine Datensammlung.

    Gibt (Tabellen, Zeilen, Bytes, Befunde, tatsaechlich verwendete URL).

    Ein Fehlschlag ist kein Abbruch, sondern ein Befund: die Datensammlung
    bleibt im Katalog, ``geladen`` bleibt 0, und ``v_nicht_geladen`` nennt den
    Grund.
    """
    befunde: list[Qualitaetsbefund] = []
    ziel = arbeit / f"{datenbank.bezeichner(sammlung.id, praefix='d')}.{_endung_fuer(sammlung)}"

    verwendete_url = sammlung.url
    try:
        groesse, verwendete_url = netz.datei_holen_mit_ersatz(
            sammlung.url, ziel, max_bytes=konf.MAX_BYTES
        )
        if verwendete_url != sammlung.url:
            # Sichtbar, nicht stillschweigend: Der Katalogeintrag war veraltet,
            # die Daten stammen aus einer anderen URL als der publizierten.
            befunde.append(
                Qualitaetsbefund(
                    typ="ersatz_url",
                    schweregrad="warnung",
                    meldung=(
                        "Katalog-URL antwortet mit 404; geladen aus einer "
                        "Schreibvariante desselben Namens"
                    ),
                    datensammlung_id=sammlung.id,
                    details={"katalog": sammlung.url, "verwendet": verwendete_url},
                )
            )
    except Exception as fehler:  # noqa: BLE001
        # Bewusst breit: Eine einzelne kaputte URL darf nie die Organisation
        # kosten. Am 22. September 2026 riss ein UnicodeEncodeError aus einer
        # URL mit Umlaut den ganzen Aufbau des BFE ab, weil hier nur
        # AbrufFehler behandelt wurde — 227 von 255 Datensammlungen blieben
        # ungeladen wegen einer.
        ziel.unlink(missing_ok=True)
        befunde.append(
            Qualitaetsbefund(
                typ="download_fehlgeschlagen",
                schweregrad="warnung",
                meldung=f"{type(fehler).__name__}: {fehler}",
                datensammlung_id=sammlung.id,
                details={"url": sammlung.url, "status": getattr(fehler, "status", None)},
            )
        )
        return 0, 0, 0, befunde, sammlung.url

    anzahl_tabellen = 0
    zeilen_gesamt = 0
    try:
        for quelle in tabellen.quellen(ziel, sammlung.format or "", sammlung.id, arbeit):
            try:
                name, zeilen = datenbank.tabelle_anlegen(verbindung, quelle, sammlung)
                anzahl_tabellen += 1
                zeilen_gesamt += zeilen
            except datenbank.LeereTabelle as fehler:
                # Eine Datei mit Kopfzeile und ohne Zeilen ist kein Fehler,
                # sondern eine leere Datei. Ein Befund mit Schweregrad
                # `fehler` dafuer entwertet die echten Fehler daneben.
                verbindung.rollback()
                befunde.append(
                    Qualitaetsbefund(
                        typ="tabelle_leer",
                        schweregrad="info",
                        meldung=str(fehler),
                        datensammlung_id=sammlung.id,
                        details={"quelle": quelle.quelle_datei},
                    )
                )
            except Exception as fehler:  # noqa: BLE001 — eine Datei darf den Lauf nie kosten
                verbindung.rollback()
                befunde.append(
                    Qualitaetsbefund(
                        typ="laden_fehlgeschlagen",
                        schweregrad="fehler",
                        meldung=f"{type(fehler).__name__}: {fehler}",
                        datensammlung_id=sammlung.id,
                        details={"quelle": quelle.quelle_datei},
                    )
                )
            finally:
                quelle.schliessen()
    except tabellen.NichtLadbar as fehler:
        befunde.append(
            Qualitaetsbefund(
                typ="nicht_aufloesbar",
                schweregrad="warnung",
                meldung=str(fehler),
                datensammlung_id=sammlung.id,
                details={"format": sammlung.format, "url": sammlung.url},
            )
        )
    except Exception as fehler:  # noqa: BLE001
        befunde.append(
            Qualitaetsbefund(
                typ="aufloesen_fehlgeschlagen",
                schweregrad="fehler",
                meldung=f"{type(fehler).__name__}: {fehler}",
                datensammlung_id=sammlung.id,
                details={"format": sammlung.format, "url": sammlung.url},
            )
        )
    finally:
        # Nur die heruntergeladene Datei: Entpackte ZIP-Eintraege raeumt
        # tabellen._aus_zip selbst ab, unter einem kurzen Streuwertnamen.
        ziel.unlink(missing_ok=True)

    return anzahl_tabellen, zeilen_gesamt, groesse, befunde, verwendete_url


# ---------------------------------------------------------------------------
# Eine Organisation
# ---------------------------------------------------------------------------


def organisation_aufbauen(gruppe: list[Organisation], *, mit_daten: bool = True) -> Bilanz:
    """Baut die Datenbank einer Oberorganisation."""
    ober = gruppe[0]
    bilanz = Bilanz(organisation=ober.name)
    pfad = konf.DATENBANK_VERZEICHNIS / f"{ober.name}.sqlite"
    arbeit = konf.ARBEIT_VERZEICHNIS / ober.name
    arbeit.mkdir(parents=True, exist_ok=True)

    verbindung = datenbank.oeffnen(pfad)
    lauf_id = datenbank.lauf_beginnen(verbindung, ober.name)
    try:
        geernteter = katalog.ernten(gruppe)
        _katalog_ablegen(geernteter, ober.name)
        datenbank.katalog_schreiben(verbindung, geernteter)

        bilanz.datensaetze = len(geernteter.datensaetze)
        bilanz.datensammlungen = len(geernteter.datensammlungen)

        if mit_daten:
            schon = datenbank.bereits_geladen(verbindung)
            offen = [
                s
                for s in geernteter.datensammlungen
                if s.verfuegbar and tabellen.ist_tabellarisch(s.format) and s.id not in schon
            ]
            log.info("%s: %d Datensammlungen zu laden", ober.name, len(offen))
            for nummer, sammlung in enumerate(offen, start=1):
                halt = platz_pruefen(pfad)
                if halt:
                    # Der Katalog steht schon vollstaendig in der Datei; ab
                    # hier fehlen nur noch Daten, und das ist sichtbar.
                    log.warning("%s: Laden gestoppt — %s", ober.name, halt)
                    datenbank.befund_schreiben(
                        verbindung,
                        Qualitaetsbefund(
                            typ="grenze_erreicht",
                            schweregrad="warnung",
                            meldung=f"Laden nach {nummer - 1} von {len(offen)} gestoppt: {halt}",
                            details={"offen": len(offen) - nummer + 1},
                        ),
                    )
                    bilanz.befunde += 1
                    break

                if ist_zu_gross(sammlung):
                    datenbank.befund_schreiben(
                        verbindung,
                        Qualitaetsbefund(
                            typ="zu_gross",
                            schweregrad="info",
                            meldung=(
                                f"{sammlung.byte_size / 1024**2:.0f} MB uebersteigen "
                                f"die Obergrenze von {konf.MAX_BYTES / 1024**2:.0f} MB"
                            ),
                            datensammlung_id=sammlung.id,
                            details={"byte_size": sammlung.byte_size, "url": sammlung.url},
                        ),
                    )
                    bilanz.befunde += 1
                    verbindung.commit()
                    continue

                anzahl, zeilen, bytes_, befunde, verwendete_url = datensammlung_laden(
                    verbindung, sammlung, arbeit
                )
                bilanz.tabellen += anzahl
                bilanz.zeilen += zeilen
                bilanz.bytes_geladen += bytes_
                bilanz.befunde += len(befunde)
                for befund in befunde:
                    datenbank.befund_schreiben(verbindung, befund)
                datenbank.ladezustand_setzen(
                    verbindung,
                    sammlung.id,
                    geladen=anzahl > 0,
                    zeilen=zeilen,
                    bytes_geladen=bytes_,
                    bezogen_von_url=(
                        verwendete_url if verwendete_url != sammlung.url else None
                    ),
                )
                verbindung.commit()
                if nummer % 25 == 0:
                    log.info(
                        "%s: %d/%d, %d Tabellen, %d Zeilen",
                        ober.name, nummer, len(offen), bilanz.tabellen, bilanz.zeilen,
                    )
    except Exception as fehler:  # noqa: BLE001 — eine Organisation darf den Lauf nie kosten
        bilanz.fehler = f"{type(fehler).__name__}: {fehler}"
        log.error("%s abgebrochen: %s", ober.name, bilanz.fehler)
        log.debug(traceback.format_exc())
        datenbank.befund_schreiben(
            verbindung,
            Qualitaetsbefund(
                typ="aufbau_abgebrochen", schweregrad="fehler", meldung=bilanz.fehler
            ),
        )
        verbindung.commit()
    finally:
        datenbank.lauf_beenden(
            verbindung,
            lauf_id,
            datensaetze=bilanz.datensaetze,
            datensammlungen=bilanz.datensammlungen,
            tabellen=bilanz.tabellen,
            zeilen=bilanz.zeilen,
            bytes_geladen=bilanz.bytes_geladen,
            befunde=bilanz.befunde,
        )
        try:
            datenbank.aufraeumen(verbindung)
        except Exception:  # noqa: BLE001 — VACUUM darf den Lauf nicht kosten
            log.warning("%s: VACUUM fehlgeschlagen", ober.name)
        verbindung.close()
        shutil.rmtree(arbeit, ignore_errors=True)

    return bilanz


def _katalog_ablegen(geernteter, name: str) -> None:
    import json

    from swiss_ogd.modelle import als_dict

    konf.KATALOG_VERZEICHNIS.mkdir(parents=True, exist_ok=True)
    ziel = konf.KATALOG_VERZEICHNIS / f"{name}.json"
    ziel.write_text(
        json.dumps(als_dict(geernteter), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def _arbeiter(nutzlast: tuple[list[Organisation], bool]) -> Bilanz:
    """Einstieg eines Unterprozesses. Muss auf Modulebene stehen (Windows)."""
    gruppe, mit_daten = nutzlast
    _protokoll_einrichten(gruppe[0].name)
    return organisation_aufbauen(gruppe, mit_daten=mit_daten)


# ---------------------------------------------------------------------------
# Lauf ueber alle Organisationen
# ---------------------------------------------------------------------------


def alle_aufbauen(
    *,
    nur: list[str] | None = None,
    mit_daten: bool = True,
    jobs: int = 1,
) -> list[Bilanz]:
    gruppen = katalog.organisationsbaum()
    if nur:
        gewaehlt = {n.lower() for n in nur}
        gruppen = [g for g in gruppen if g[0].name.lower() in gewaehlt]
        fehlend = gewaehlt - {g[0].name.lower() for g in gruppen}
        if fehlend:
            log.warning("Unbekannte Organisationen uebergangen: %s", ", ".join(sorted(fehlend)))
    # Die kleinen zuerst: ein frueher Fehler zeigt sich in Minuten, nicht erst
    # nachdem das BFS mit 3370 Datensaetzen durchgelaufen ist. Massstab ist
    # die Zahl der Datensaetze, nicht die der Unterorganisationen — das BFS
    # hat keine einzige und ist trotzdem die groesste Organisation im Portal.
    # Die Zahl kostet eine Anfrage je Gruppe (rows=0, ohne Inhalte).
    log.info("Reihenfolge bestimmen: %d Gruppen zaehlen", len(gruppen))
    umfang: dict[str, int] = {}
    for gruppe in gruppen:
        try:
            umfang[gruppe[0].name] = katalog.datensatz_anzahl(gruppe)
        except Exception:  # noqa: BLE001 — die Reihenfolge darf den Lauf nicht kosten
            umfang[gruppe[0].name] = 0
    gruppen.sort(key=lambda g: umfang.get(g[0].name, 0))

    log.info("%d Organisationen, %d gleichzeitig", len(gruppen), jobs)
    bilanzen: list[Bilanz] = []

    if jobs <= 1:
        for gruppe in gruppen:
            bilanzen.append(organisation_aufbauen(gruppe, mit_daten=mit_daten))
            _zwischenstand(bilanzen[-1])
        return bilanzen

    with ProcessPoolExecutor(max_workers=jobs) as pool:
        auftraege = {
            pool.submit(_arbeiter, (gruppe, mit_daten)): gruppe[0].name for gruppe in gruppen
        }
        for auftrag in as_completed(auftraege):
            name = auftraege[auftrag]
            try:
                bilanz = auftrag.result()
            except Exception as fehler:  # noqa: BLE001
                bilanz = Bilanz(organisation=name, fehler=f"{type(fehler).__name__}: {fehler}")
            bilanzen.append(bilanz)
            _zwischenstand(bilanz)
    return bilanzen


def _zwischenstand(bilanz: Bilanz) -> None:
    if bilanz.gelungen:
        log.info(
            "fertig %-45s %5d Datensaetze  %5d Tabellen  %10d Zeilen",
            bilanz.organisation, bilanz.datensaetze, bilanz.tabellen, bilanz.zeilen,
        )
    else:
        log.error("fehlgeschlagen %-40s %s", bilanz.organisation, bilanz.fehler)


# ---------------------------------------------------------------------------
# Protokoll und Befehlszeile
# ---------------------------------------------------------------------------


def _protokoll_einrichten(name: str = "lauf") -> None:
    konf.PROTOKOLL_VERZEICHNIS.mkdir(parents=True, exist_ok=True)
    datei = konf.PROTOKOLL_VERZEICHNIS / f"{datetime.now(UTC):%Y-%m-%d}-{name}.log"
    form = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s")
    wurzel = logging.getLogger()
    wurzel.setLevel(logging.INFO)
    for alter in list(wurzel.handlers):
        wurzel.removeHandler(alter)
    nach_datei = logging.FileHandler(datei, encoding="utf-8")
    nach_datei.setFormatter(form)
    wurzel.addHandler(nach_datei)
    nach_konsole = logging.StreamHandler(sys.stderr)
    nach_konsole.setFormatter(form)
    wurzel.addHandler(nach_konsole)


def main(argv: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(
        prog="swiss-ogd",
        description=(
            "Baut je Oberorganisation auf opendata.swiss eine SQLite-Datenbank "
            "mit Katalog und generisch geladenen Daten."
        ),
    )
    unter = zerleger.add_subparsers(dest="befehl", required=True)

    unter.add_parser("organisationen", help="Die Oberorganisationen auflisten")

    bauen = unter.add_parser("aufbauen", help="Datenbanken bauen")
    bauen.add_argument("--nur", nargs="*", help="Nur diese Oberorganisationen (CKAN-Name)")
    bauen.add_argument(
        "--ohne-daten", action="store_true", help="Nur den Katalog, keine Dateien laden"
    )
    bauen.add_argument("--jobs", type=int, default=1, help="Organisationen gleichzeitig")

    argumente = zerleger.parse_args(argv)
    _protokoll_einrichten()

    if argumente.befehl == "organisationen":
        for gruppe in katalog.organisationsbaum():
            ober = gruppe[0]
            print(f"{ober.name:55s} {len(gruppe) - 1:3d} Unterorganisationen  {ober.titel_de}")
        return 0

    bilanzen = alle_aufbauen(
        nur=argumente.nur,
        mit_daten=not argumente.ohne_daten,
        jobs=max(1, argumente.jobs),
    )

    gelungen = [b for b in bilanzen if b.gelungen]
    print()
    print(f"{len(gelungen)} von {len(bilanzen)} Organisationen gebaut")
    print(f"{sum(b.datensaetze for b in bilanzen):>10d} Datensaetze")
    print(f"{sum(b.tabellen for b in bilanzen):>10d} Datentabellen")
    print(f"{sum(b.zeilen for b in bilanzen):>10d} Zeilen")
    print(f"{sum(b.bytes_geladen for b in bilanzen) / 1e9:>10.1f} GB heruntergeladen")
    for bilanz in bilanzen:
        if not bilanz.gelungen:
            print(f"  fehlgeschlagen: {bilanz.organisation} — {bilanz.fehler}")
    return 0 if len(gelungen) == len(bilanzen) else 1


if __name__ == "__main__":
    raise SystemExit(main())
