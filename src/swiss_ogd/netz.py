"""HTTP-Zugriff mit Drosselung je Host, Wiederholung und Bot-Erkennung.

Nur Standardbibliothek (``urllib``) — Dev-Bedingung "Limit Libraries".

Drei Massnahmen, wie im LU Datenportal:

*   ein aussagekraeftiger User-Agent,
*   Drosselung auf eine Anfrage je Sekunde **und Host** (nicht global: ein
    Lauf beruehrt 85 Organisationen auf ebenso vielen Servern, eine globale
    Drossel wuerde jeden davon unnoetig bremsen),
*   Wiederholung mit exponentiellem Backoff bei Transportfehlern, bei 429 und
    5xx sowie bei einer Antwort, die kein JSON ist.
"""

from __future__ import annotations

import gzip
import json
import os
import logging
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from swiss_ogd import konfiguration as konf

log = logging.getLogger(__name__)


class AbrufFehler(RuntimeError):
    """Ein Abruf ist auch nach allen Wiederholungen fehlgeschlagen."""

    def __init__(self, meldung: str, *, url: str, status: int | None = None) -> None:
        super().__init__(meldung)
        self.url = url
        self.status = status


class BotErkennung(AbrufFehler):
    """Die Gegenstelle hat statt JSON eine Abwehrseite geliefert."""


class _HostDrossel:
    """Haelt den Mindestabstand zweier Anfragen je Host ein."""

    def __init__(self, abstand_s: float) -> None:
        self._abstand = abstand_s
        self._letzte: dict[str, float] = {}
        self._schloss = threading.Lock()

    def warten(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        with self._schloss:
            jetzt = time.monotonic()
            vorher = self._letzte.get(host, 0.0)
            rest = self._abstand - (jetzt - vorher)
            if rest > 0:
                time.sleep(rest)
                jetzt = time.monotonic()
            self._letzte[host] = jetzt


_drossel = _HostDrossel(konf.ABSTAND_JE_HOST_S)


def _ssl_kontext() -> ssl.SSLContext:
    """Der TLS-Kontext fuer alle Abrufe — mit einem verlaesslichen Wurzelspeicher.

    Warum das noetig ist: Windows installiert Wurzelzertifikate **bei Bedarf**.
    Bis ein Programm eine Kette gegen eine noch fehlende Wurzel prueft, steht
    sie nicht im Speicher, und Pythons ``enum_certificates("ROOT")`` stoesst
    diese Nachinstallation nicht an. Am 22. September 2026 scheiterten darum
    **alle 1451** Dateien der Stadt Zuerich an
    ``CERTIFICATE_VERIFY_FAILED``, obwohl ihre Kette einwandfrei ist
    (DigiCert -> QuoVadis Root CA 2 G3, ``openssl`` und ``curl`` sagen
    "Verify return code: 0"). Nach einem einzigen curl-Aufruf gegen denselben
    Host holte Windows die Wurzel nach, und derselbe Python-Code lief.

    Ein Ergebnis, das davon abhaengt, ob zufaellig vorher jemand curl
    aufgerufen hat, ist kein Ergebnis. Darum in dieser Reihenfolge:

    1. ``SSL_CERT_FILE`` — wer einen eigenen Speicher setzt, bekommt ihn,
    2. ``certifi`` — plattformunabhaengig und immer gleich,
    3. der Standard des Systems.

    Die Pruefung wird **nie** abgeschaltet. Ein nicht pruefbares Zertifikat
    ist ein Befund, kein Grund, alles zu glauben.
    """
    eigener = os.environ.get("SSL_CERT_FILE")
    if eigener and Path(eigener).exists():
        return ssl.create_default_context(cafile=eigener)
    try:
        import certifi
    except ImportError:
        log.debug("certifi fehlt, Wurzelspeicher des Systems")
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


#: Einmal gebaut und geteilt: Ein Kontext je Anfrage kostet bei zehntausenden
#: Abrufen spuerbar Zeit.
_KONTEXT = _ssl_kontext()


def ascii_url(url: str) -> str:
    """Prozentkodiert die Nicht-ASCII-Zeichen einer URL.

    ``urllib`` kodiert nicht selbst: Eine URL mit Umlaut wirft
    ``UnicodeEncodeError: 'ascii' codec can't encode character``. Am
    22. September 2026 kostete eine einzige solche URL den ganzen Aufbau des
    Bundesamts fuer Energie — der Fehler ist kein AbrufFehler und lief darum
    an der Behandlung je Datensammlung vorbei.

    Kodiert wird nur, was kodiert werden muss; eine bereits kodierte URL
    bleibt unveraendert (``%`` steht in der Liste der sicheren Zeichen).
    """
    if url.isascii():
        return url
    teile = urlsplit(url)
    host = teile.netloc.encode("idna").decode("ascii") if not teile.netloc.isascii() else teile.netloc
    return urlunsplit(
        (
            teile.scheme,
            host,
            quote(teile.path, safe="/%:@&=+$,;~!*'()-._"),
            quote(teile.query, safe="/%:@&=+$,;~!*'()-._?"),
            quote(teile.fragment, safe="/%:@&=+$,;~!*'()-._?"),
        )
    )


def _anfrage(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        ascii_url(url),
        headers={
            "User-Agent": konf.USER_AGENT,
            "Accept-Encoding": "gzip",
            "Accept": "*/*",
        },
    )


def _mit_wiederholung(url: str, tun: Callable[[], Any]) -> Any:
    """Fuehrt ``tun`` aus und wiederholt bei erholbaren Fehlern."""
    letzter: Exception | None = None
    for versuch in range(konf.VERSUCHE):
        if versuch:
            wartezeit = konf.BACKOFF_BASIS**versuch
            log.debug("Versuch %d fuer %s in %.0fs", versuch + 1, url, wartezeit)
            time.sleep(wartezeit)
        _drossel.warten(url)
        try:
            return tun()
        except urllib.error.HTTPError as fehler:
            letzter = fehler
            if fehler.code not in konf.WIEDERHOLBARE_CODES:
                raise AbrufFehler(
                    f"HTTP {fehler.code} fuer {url}", url=url, status=fehler.code
                ) from fehler
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as fehler:
            letzter = fehler
        except BotErkennung:
            raise
        except json.JSONDecodeError as fehler:
            letzter = fehler
    status = getattr(letzter, "code", None)
    raise AbrufFehler(
        f"{konf.VERSUCHE} Versuche fehlgeschlagen fuer {url}: {letzter}",
        url=url,
        status=status,
    ) from letzter


def _entpacken(antwort: Any, rohdaten: bytes) -> bytes:
    if antwort.headers.get("Content-Encoding", "").lower() == "gzip":
        return gzip.decompress(rohdaten)
    return rohdaten


def json_holen(url: str) -> dict[str, Any]:
    """Holt eine JSON-Antwort. Eine Nicht-JSON-Antwort gilt als Bot-Abwehr."""

    def tun() -> dict[str, Any]:
        with urllib.request.urlopen(_anfrage(url), timeout=konf.TIMEOUT_S, context=_KONTEXT) as antwort:
            rohdaten = _entpacken(antwort, antwort.read())
            typ = antwort.headers.get("Content-Type", "")
        if "json" not in typ.lower() and not rohdaten.lstrip()[:1] in (b"{", b"["):
            raise BotErkennung(
                f"Antwort ist kein JSON ({typ}) fuer {url}", url=url, status=None
            )
        return json.loads(rohdaten.decode("utf-8", errors="replace"))

    return _mit_wiederholung(url, tun)


def ckan(url: str) -> Any:
    """Ruft eine CKAN-Aktion auf und gibt ``result`` zurueck."""
    antwort = json_holen(url)
    if not antwort.get("success", False):
        raise AbrufFehler(f"CKAN meldet Misserfolg fuer {url}", url=url)
    return antwort.get("result")


def ersatzvarianten(url: str) -> list[str]:
    """Mechanische Schreibvarianten **desselben** Dateinamens.

    Warum es das braucht: Ein Katalogeintrag auf opendata.swiss veraltet, ohne
    dass jemand ihn nachfuehrt. Beim Staatssekretariat fuer Migration SEM
    zeigen alle 80 Eintraege auf 404 — die Dateien sind aber da. Das SEM hat
    seine Dateinamen kleingeschrieben und das Sprachkuerzel entfernt:

        Katalog:  .../2019/csv/2-30-Best-Flu-d-2019.csv
        wirklich: .../2019/csv/2-30-best-flu-2019.csv

    Pfad und Host bleiben gleich, nur der Name aendert sich. Gemessen am
    22. September 2026: 10 von 10 geprueften Eintraegen lassen sich so finden.

    Die Varianten werden **aus dem katalogisierten Namen abgeleitet** und
    koennen darum nie auf eine andere Datensammlung zeigen. Der franzoesische
    Eintrag ``2-30-effectif-refu-f-2019.csv`` findet nichts — das SEM hat die
    franzoesische Fassung eingestellt — und wird korrekt als entfallen
    vermerkt, statt still die deutsche zu bekommen.
    """
    teile = urlsplit(url)
    name = teile.path.rsplit("/", 1)[-1]
    if not name or "." not in name:
        return []
    stamm, endung = name.rsplit(".", 1)
    kandidaten: list[str] = [name.lower()]
    marken = stamm.split("-")
    for nummer, marke in enumerate(marken):
        # Nur kurze **Buchstaben**-Marker wie d/f/j/a. Zwei Bedingungen, beide
        # noetig:
        #   - kurz, weil ein ganzes Wort wegzulassen kein Schreibfehler mehr
        #     waere, sondern eine andere Datei;
        #   - Buchstaben, weil die Ziffern die Tabellennummer sind. Ohne diese
        #     Bedingung wird aus `2-30-best-flu-d-2019` auch `30-best-flu-...`
        #     und `2-best-flu-...` — Namen, die auf eine andere Tabelle der
        #     Reihe zeigen koennten. Genau das soll nie passieren.
        if len(marke) <= 2 and marke.isalpha():
            kandidaten.append(
                ("-".join(marken[:nummer] + marken[nummer + 1 :]) + "." + endung).lower()
            )
    gesehen: set[str] = {name}
    ergebnis: list[str] = []
    for kandidat in kandidaten:
        if kandidat in gesehen:
            continue
        gesehen.add(kandidat)
        # Der Name steht in DAM-URLs zweimal drin (…/x.csv.download.csv/x.csv).
        ergebnis.append(url.replace(name, kandidat))
    return ergebnis


def datei_holen_mit_ersatz(
    url: str, ziel: Path, *, max_bytes: int = 0
) -> tuple[int, str]:
    """Wie ``datei_holen``, versucht bei 404/410 aber Schreibvarianten.

    Gibt (Bytes, tatsaechlich verwendete URL). Weicht die zurueckgegebene URL
    von der uebergebenen ab, muss der Aufrufer das festhalten — eine Zahl
    traegt die Herkunft, aus der sie wirklich stammt, nicht die, die im
    Katalog steht.
    """
    try:
        return datei_holen(url, ziel, max_bytes=max_bytes), url
    except AbrufFehler as fehler:
        if fehler.status not in (404, 410):
            raise
    for kandidat in ersatzvarianten(url):
        try:
            groesse = datei_holen(kandidat, ziel, max_bytes=max_bytes)
        except AbrufFehler:
            continue
        log.info("Ersatz-URL gefunden: %s -> %s", url, kandidat)
        return groesse, kandidat
    raise AbrufFehler(f"HTTP 404 fuer {url}, auch keine Schreibvariante", url=url, status=404)


def datei_holen(url: str, ziel: Path, *, max_bytes: int = 0) -> int:
    """Laedt ``url`` stroemend nach ``ziel`` und gibt die Groesse zurueck.

    Stroemend, weil eine einzelne Datensammlung auf opendata.swiss mehrere
    Gigabyte gross sein kann; sie darf nie ganz im Arbeitsspeicher liegen.
    ``max_bytes`` = 0 bedeutet: keine Grenze.
    """
    ziel.parent.mkdir(parents=True, exist_ok=True)

    def tun() -> int:
        geschrieben = 0
        with urllib.request.urlopen(_anfrage(url), timeout=konf.TIMEOUT_S, context=_KONTEXT) as antwort:
            gepackt = antwort.headers.get("Content-Encoding", "").lower() == "gzip"
            roh = ziel.open("wb")
            strom = gzip.GzipFile(fileobj=antwort) if gepackt else antwort
            try:
                while True:
                    block = strom.read(1 << 20)
                    if not block:
                        break
                    geschrieben += len(block)
                    if max_bytes and geschrieben > max_bytes:
                        raise AbrufFehler(
                            f"Datei ueberschreitet {max_bytes} Bytes", url=url
                        )
                    roh.write(block)
            finally:
                roh.close()
                if gepackt:
                    strom.close()
        return geschrieben

    return _mit_wiederholung(url, tun)
