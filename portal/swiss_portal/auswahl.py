"""Waehlt die Datensaetze fuer einen Verknuepfungslauf und legt ihre Angaben ab.

    python -m swiss_portal.auswahl --anzahl 200

Die Auswahl ist fuer den Probelauf **bewusst gebuendelt**: Zufaellige 200 aus
15'934 haetten kaum gemeinsame Themen, und es entstuenden kaum Verbindungen.
Darum stammen zwei Drittel aus wenigen Themenfeldern, quer ueber Anbieter, und
ein Drittel ist zufaellig. Bevorzugt werden Datensaetze, zu denen mindestens
eine Tabelle geladen ist — sie lassen sich im Portal auch abfragen.

Ausgabe: portal/daten/auswahl.jsonl, eine Zeile je Datensatz mit allem, was
der Extraktion als Quelle dient (Titel, Beschreibung, Schlagworte, Thema,
Organisation, Spaltennamen). Genau dieser Text ist spaeter die Grundlage der
Belegpruefung: Eine Textstelle, die hier nicht steht, ist kein Beleg.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from pathlib import Path

from . import konfiguration as k

THEMEN = {
    "Wohnen": ["leerwohnung", "wohnung", "logement", "mietpreis", "wohnbau"],
    "Luft und Klima": ["luftqualit", "stickstoffdioxid", "feinstaub", "ozon", "klima", "temperatur"],
    "Energie": ["solar", "photovoltaik", "energie", "strom", "elektriz"],
    # nicht «tier» allein: das trifft auch «Quartier» (gefunden im Probelauf 17.11.2026)
    "Tiere": ["hund", "tiere", "tierhalt", "nutztier", "haustier", "wildtier", "vogel", "fisch"],
    "Mobilitaet": ["velo", "verkehr", "ladestation", "parkpl", "fahrzeug", "personenwagen", "bahn"],
    "Bevoelkerung": ["bevoelkerung", "bevölkerung", "vorname", "geburt", "einwohner", "population"],
    "Steuern und Finanzen": ["steuerfuss", "steuer", "finanz", "budget", "rechnung"],
    "Politik": ["abstimmung", "wahl", "votation", "landsgemeinde"],
    "Wasser": ["gewaesser", "gewässer", "grundwasser", "wasser", "see ", "fluss"],
    "Wald und Landwirtschaft": ["wald", "landwirtschaft", "boden", "agrar"],
    "Gesundheit": ["gesundheit", "spital", "covid", "krankheit"],
    "Bildung": ["schule", "bildung", "lernende", "hochschule"],
}

ZIEL = k.PORTAL / "daten" / "auswahl.jsonl"


def _verbinden(datei: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{datei.as_posix()}?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _kandidaten() -> list[dict]:
    alle: list[dict] = []
    for datei in sorted(k.DATENBANKEN.glob("*.sqlite")):
        c = _verbinden(datei)
        geladen = {r[0]: r[1] for r in c.execute("select datensatz_id, count(*) from daten_tabelle group by 1")}
        for r in c.execute(
            "select id, titel_de, beschreibung_de, organisation, schlagworte, thema, "
            "zeitraum_von, zeitraum_bis, raum from dim_datensatz"
        ):
            alle.append({**dict(r), "datei": datei.stem, "tabellen": geladen.get(r["id"], 0)})
        c.close()
    return alle


def _spalten(datei: str, datensatz_id: str, hoechstens: int = 40) -> list[str]:
    c = _verbinden(k.DATENBANKEN / f"{datei}.sqlite")
    namen = [
        r[0]
        for r in c.execute(
            "select distinct s.name_original from daten_spalte s join daten_tabelle t on t.tabelle = s.tabelle "
            "where t.datensatz_id = ? and s.name_original not in ('datensammlung_id') limit ?",
            (datensatz_id, hoechstens),
        )
    ]
    c.close()
    return namen


def waehlen(anzahl: int, saat: int = 17) -> list[dict]:
    zufall = random.Random(saat)
    alle = _kandidaten()
    mit_daten = [d for d in alle if d["tabellen"] > 0]
    gewaehlt: dict[str, dict] = {}

    je_thema = max(1, (anzahl * 2 // 3) // len(THEMEN))
    for thema, woerter in THEMEN.items():
        treffer = [
            d for d in mit_daten
            if any(w in (d["titel_de"] or "").lower() for w in woerter) and d["id"] not in gewaehlt
        ]
        zufall.shuffle(treffer)
        # quer ueber Anbieter: hoechstens zwei je Datei und Thema
        je_datei: dict[str, int] = {}
        n = 0
        for d in treffer:
            if n >= je_thema:
                break
            if je_datei.get(d["datei"], 0) >= 2:
                continue
            je_datei[d["datei"]] = je_datei.get(d["datei"], 0) + 1
            gewaehlt[d["id"]] = {**d, "grund": f"Thema: {thema}"}
            n += 1

    rest = [d for d in mit_daten if d["id"] not in gewaehlt]
    zufall.shuffle(rest)
    for d in rest[: anzahl - len(gewaehlt)]:
        gewaehlt[d["id"]] = {**d, "grund": "zufaellig"}
    return list(gewaehlt.values())[:anzahl]


def _eintrag(d: dict) -> dict:
    return {
        "datensatz_id": d["id"],
        "datei": d["datei"],
        "grund": d["grund"],
        "organisation": d["organisation"],
        "titel": d["titel_de"],
        "beschreibung": (d["beschreibung_de"] or "")[:2000],
        "schlagworte": json.loads(d["schlagworte"]) if d["schlagworte"] else [],
        "thema": json.loads(d["thema"]) if d["thema"] else [],
        "zeitraum": [d["zeitraum_von"], d["zeitraum_bis"]],
        "spalten": _spalten(d["datei"], d["id"]) if d["tabellen"] else [],
    }


def _schon_extrahiert() -> set[str]:
    fertig: set[str] = set()
    for datei in (k.PORTAL / "daten" / "extraktion").glob("claude_*.jsonl"):
        for z in datei.read_text(encoding="utf-8").split("\n"):
            if z.strip():
                fertig.add(json.loads(z)["datensatz_id"])
    return fertig


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--anzahl", type=int, default=200)
    p.add_argument("--alle", action="store_true",
                   help="alle Datensaetze, auch ohne Tabelle; schreibt dazu Pakete fuer die Extraktion")
    p.add_argument("--paketgroesse", type=int, default=50)
    a = p.parse_args()
    if a.alle:
        auswahl = [{**d, "grund": "Vollausbau"} for d in _kandidaten()]
    else:
        auswahl = waehlen(a.anzahl)
    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    eintraege = [_eintrag(d) for d in auswahl]
    with ZIEL.open("w", encoding="utf-8") as f:
        for e in eintraege:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    if a.alle:
        # Pakete nur fuer, was noch keine Claude-Extraktion hat. Die Pakete des
        # Probelaufs (eingabe_teil_NN / claude_teil_NN) bleiben, wie sie sind.
        fertig = _schon_extrahiert()
        offen = [e for e in eintraege if e["datensatz_id"] not in fertig]
        ordner = k.PORTAL / "daten" / "extraktion"
        for alt in ordner.glob("eingabe_voll_*.jsonl"):
            alt.unlink()
        for i in range(0, len(offen), a.paketgroesse):
            nr = i // a.paketgroesse
            with (ordner / f"eingabe_voll_{nr:04d}.jsonl").open("w", encoding="utf-8") as f:
                for e in offen[i : i + a.paketgroesse]:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"{len(fertig)} schon extrahiert, {len(offen)} offen -> "
              f"{(len(offen) + a.paketgroesse - 1) // a.paketgroesse} Pakete eingabe_voll_NNNN.jsonl")
    gruende: dict[str, int] = {}
    for d in auswahl:
        gruende[d["grund"]] = gruende.get(d["grund"], 0) + 1
    print(f"{len(auswahl)} Datensaetze aus {len({d['datei'] for d in auswahl})} Organisationen -> {ZIEL}")
    for g, n in sorted(gruende.items()):
        print(f"  {n:4d}  {g}")


if __name__ == "__main__":
    main()
