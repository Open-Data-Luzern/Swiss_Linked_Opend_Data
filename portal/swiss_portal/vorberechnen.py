"""Vorberechnete Antworten fuer Cockpit, Entdecken und «Weg des Tages».

    python -m swiss_portal.vorberechnen        # ohne den Graphen neu zu bauen

Laeuft am Ende jedes Graphenbaus. Schreibt neben den Graphen:

    cockpit.json       Kennzahlen, Kantenklassen, Laeufe, breiteste Begriffe
    karte.json         verknuepfte Datensaetze je Gemeinde (BFS-Nummer)
    entdeckungen.json  Begriffe, Bruecken, Kennzahl-Matrix, Schluessel-Netz, Wege
    zufallswege.json   die 50 ueberraschendsten Wege (siehe _zufallswege)

Das Portal liefert diese Dateien unveraendert aus: keine Rechnung pro Aufruf.
"""

from __future__ import annotations

import difflib
import json
import random
import sqlite3
import time
from pathlib import Path

from . import konfiguration as k
from .netz import HUB_GRAD, Netz

EINBETTUNGEN = k.PORTAL / "daten" / "einbettungen.sqlite"

# Ebene eines Anbieters, nach dem Dateinamen seiner Datenbank. Gesetzt von Hand
# am 18.11.2026 fuer die 85 Anbieter; was nicht passt, ist «Andere».
BUND = {
    "agroscope", "bkb", "bibliothek-am-guisanplatz-big", "dienst-ueberwachung-post-und-fernmeldeverkehr-uepf",
    "direktion-fur-entwicklung-und-zusammenarbeit-deza", "elcom", "efk", "eidgenossische-finanzverwaltung-efv",
    "eidgenoessische_zollverwaltung_ezv", "digitale_medien_der_armee_dma", "parlamentsdienste-pd",
    "schweizerisches-bundesarchiv-bar", "schweizerisches-nationalmuseum-snm", "sbfi",
    "staatssekretariat-fuer-migration-sem", "swissmedic", "bundesamt_fuer_justiz",
    "unabhangige-expertenkommission-uek-administrative-versorgungen",
}


def ebene(datei: str) -> str:
    if datei in BUND or datei.startswith("bundesamt"):
        return "Bund"
    if datei in ("ag", "ti") or datei.startswith(("kanton", "canton")):
        return "Kanton"
    if datei.startswith(("stadt", "gemeinde")) or datei in ("biel-bienne", "lausanne", "morges"):
        return "Gemeinde"
    return "Andere"


def _schreiben(pfad: Path, daten) -> None:
    neu = pfad.with_suffix(".json.neu")
    neu.write_text(json.dumps(daten, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    neu.replace(pfad)


def _bestand() -> dict:
    gesamt = {"organisationen": 0, "datensaetze": 0, "datensammlungen": 0, "tabellen": 0, "zeilen": 0}
    for pfad in sorted(k.DATENBANKEN.glob("*.sqlite")):
        try:
            c = sqlite3.connect(f"file:{pfad.as_posix()}?mode=ro&immutable=1", uri=True)
            gesamt["organisationen"] += 1
            gesamt["datensaetze"] += c.execute("select count(*) from dim_datensatz").fetchone()[0]
            gesamt["datensammlungen"] += c.execute("select count(*) from dim_datensammlung").fetchone()[0]
            t, z = c.execute("select count(*), coalesce(sum(zeilen), 0) from daten_tabelle").fetchone()
            gesamt["tabellen"] += t
            gesamt["zeilen"] += z
            c.close()
        except sqlite3.Error:
            continue
    return gesamt


def _datei_von(c: sqlite3.Connection) -> dict[str, str]:
    return {i: json.loads(x)["datei"] for i, x in c.execute("select id, extra from knoten where typ = 'datensatz'")}


def _gemeinsame_begriffe(c: sqlite3.Connection, anzahl: int) -> list[dict]:
    return [dict(zip(("id", "label", "datensaetze", "anbieter"), z)) for z in c.execute(
        "select b.id, b.label, count(distinct d.id), count(distinct json_extract(d.extra, '$.datei')) as anbieter "
        "from kante e join knoten b on b.id = e.nach and b.typ = 'begriff' "
        "join knoten d on d.id = e.von and d.typ = 'datensatz' "
        "group by b.id having anbieter >= 3 order by anbieter desc, 3 desc limit ?", (anzahl,))]


def _cockpit(c: sqlite3.Connection, graph_pfad: Path) -> dict:
    lauf = {r[0]: r[1] for r in c.execute("select schritt, wert from lauf")}
    knoten = {r[0]: r[1] for r in c.execute("select typ, count(*) from knoten group by 1")}
    klassen = {r[0]: r[1] for r in c.execute("select klasse, count(*) from kante group by 1")}
    laeufe = []
    datei = graph_pfad.parent / "laeufe.jsonl"
    if datei.exists():
        laeufe = [json.loads(z) for z in datei.read_text(encoding="utf-8").split("\n") if z.strip()]
    if not laeufe or laeufe[-1].get("gebaut_am") != lauf.get("gebaut_am"):
        laeufe.append({**lauf, "klassen": klassen, "datensaetze": knoten.get("datensatz", 0)})
    return {
        "stand": lauf.get("gebaut_am"),
        "bestand": _bestand(),
        "knoten": knoten,
        "klassen": klassen,
        "laeufe": [{"gebaut_am": l.get("gebaut_am"), "knoten": int(l.get("knoten", 0)), "kanten": int(l.get("kanten", 0)),
                    "datensaetze": int(l.get("datensaetze", 0))} for l in laeufe],
        "begriffe": _gemeinsame_begriffe(c, 16),
    }


def _karte(c: sqlite3.Connection) -> dict:
    from .graph import Verzeichnis
    vz = Verzeichnis(k.GEMEINDEVERZEICHNIS)
    zahl = {int(n.rsplit("/", 1)[1]): z for n, z in c.execute(
        "select nach, count(distinct von) from kante where art = 'ort' and nach like 'ort/gemeinde/%' group by 1")}
    return {"mass": "datensaetze",
            "titel": "Verknüpfte Datensätze, die die Gemeinde nennen",
            "gemeinden": sorted(({"bfs": int(g["BfsCode"]), "name": g["Name"], "kanton": vz.kanton_von_gemeinde.get(g["BfsCode"]),
                                  "wert": zahl.get(int(g["BfsCode"]), 0)} for g in vz.gemeinden), key=lambda x: x["name"])}


def _bruecken(c: sqlite3.Connection, datei_von: dict, anzahl: int = 30) -> list[dict]:
    """Verwandte, aber nicht gleichbedeutende Begriffe, die Daten verschiedener
    Anbieter verbinden. Ueber 0.95 Aehnlichkeit stehen fast nur Synonyme
    (Elektrizitaetsverbrauch/Stromverbrauch, gesehen am 18.11.2026) — die sind
    keine Entdeckung. Geordnet nach der Zahl der verbundenen Anbieter."""
    def anbieter(b: str) -> set:
        return {datei_von[d] for (d,) in c.execute("select von from kante where nach = ? and von like 'datensatz/%'", (b,))}

    aus = []
    for a, al, b, bl, w in c.execute(
            "select a.id, a.label, b.id, b.label, e.gewicht from kante e join knoten a on a.id = e.von "
            "join knoten b on b.id = e.nach where e.art = 'aehnlich' and e.gewicht < 0.95 order by e.gewicht desc"):
        x, y = al.lower(), bl.lower()
        if x in y or y in x or difflib.SequenceMatcher(None, x, y).ratio() >= 0.75:
            continue
        pa, pb = anbieter(a), anbieter(b)
        if not pa or not pb or not (pa - pb or pb - pa) or pa == pb:
            continue
        aus.append({"a_id": a, "a_label": al, "b_id": b, "b_label": bl, "gewicht": w, "anbieter": len(pa | pb)})
    return sorted(aus, key=lambda x: (-x["anbieter"], -x["gewicht"]))[:anzahl]


def _kennzahl_matrix(c: sqlite3.Connection, datei_von: dict, anzahl: int = 18) -> dict:
    zaehler: dict[str, dict[str, set]] = {}
    label = {}
    for b, bl, d in c.execute(
            "select b.id, b.label, e.von from kante e join knoten b on b.id = e.nach where e.art = 'kennzahl'"):
        label[b] = bl
        zaehler.setdefault(b, {}).setdefault(ebene(datei_von[d]), set()).add(datei_von[d])
    wahl = sorted(zaehler, key=lambda b: (-sum(len(v) for v in zaehler[b].values()), label[b]))[:anzahl]
    ebenen = ["Bund", "Kanton", "Gemeinde", "Andere"]
    return {"ebenen": ebenen,
            "zeilen": [{"id": b, "label": label[b], "werte": [len(zaehler[b].get(e, ())) for e in ebenen]} for b in wahl],
            "einheit": "Anbieter"}


def _schluessel_netz(c: sqlite3.Connection) -> list[dict]:
    aus = []
    for d, dl, s, beleg in c.execute(
            "select d.id, d.label, e.nach, e.beleg from kante e join knoten d on d.id = e.von where e.art = 'enthaelt_schluessel'"):
        thema = c.execute("select t.label from kante e join knoten t on t.id = e.nach where e.von = ? and e.art = 'thema' limit 1", (d,)).fetchone()
        aus.append({"id": d, "label": dl, "schluessel": s, "thema": thema[0] if thema else "Ohne Thema", "beleg": beleg})
    return aus


# Wege aus dem Brief (Testpaare 18.11.2026) — sie stehen als kuratierte Wege vorn.
KURATIERT = [
    ("begriff/hund", "begriff/steuer"), ("begriff/biber", "begriff/kirche"), ("begriff/kuh", "begriff/glucksspiel"),
    ("begriff/wolf", "begriff/schaf"), ("ort/gemeinde/1311", "begriff/wolf"), ("ort/gemeinde/1703", "begriff/rind"),
]


def _vektoren(labels: dict[str, str]):
    import numpy as np
    if not EINBETTUNGEN.exists():
        return {}
    c = sqlite3.connect(f"file:{EINBETTUNGEN.as_posix()}?mode=ro", uri=True)
    aus = {}
    for i, l in labels.items():
        z = c.execute("select v from vektor where text = ?",
                      (f"Instruct: Gib den Fachbegriff aus der Verwaltungsstatistik wieder\nQuery: {l}",)).fetchone()
        if z:
            v = np.frombuffer(z[0], dtype=np.float32)
            aus[i] = v / (np.linalg.norm(v) + 1e-12)
    c.close()
    return aus


def _zufallswege(netz: Netz, ziel: int = 50, kandidaten: int = 500) -> dict:
    """Ein Weg ist ueberraschend, wenn Start und Ziel inhaltlich weit auseinander
    liegen (Einbettungen wenig aehnlich) und der Weg trotzdem kurz ist:
    4 bis 6 Stationen, hoechstens ein Hub, wenn moeglich mindestens eine belegte
    oder gemessene Kante. Aus 500 Kandidaten werden die besten 50 behalten."""
    rnd = random.Random(20261118)
    begriffe = [i for i, t in netz.typ.items() if t == "begriff" and 5 <= netz.grad.get(i, 0) <= HUB_GRAD]
    vek = _vektoren({i: netz.label[i] for i in begriffe})
    begriffe = [i for i in begriffe if i in vek]
    paare = set()
    while len(paare) < kandidaten * 8 and len(begriffe) > 2:
        a, b = rnd.sample(begriffe, 2)
        paare.add((min(a, b), max(a, b)))
    entfernt = sorted(((float(vek[a] @ vek[b]), a, b) for a, b in paare))[:kandidaten]
    gute, ersatz = [], []
    for cos, a, b in entfernt:
        w = netz.weg(a, b)
        if not w or not 3 <= len(w) <= 5:
            continue
        stationen = [w[0][0]] + [y for _, y, _ in w]
        if sum(1 for s in stationen if netz.hub(s)) > 1:
            continue
        j = netz.als_json(w)
        j["distanz"] = round(1 - cos, 3)
        (gute if any(e[3] in ("belegt", "gemessen") for _, _, e in w) else ersatz).append(j)
    gewaehlt, gesehen = [], set()
    for j in sorted(gute, key=lambda x: -x["distanz"]) + sorted(ersatz, key=lambda x: -x["distanz"]):
        a, b = j["knoten"][0]["id"], j["knoten"][-1]["id"]
        if a in gesehen or b in gesehen:
            continue
        gesehen.update((a, b))
        gewaehlt.append(j)
        if len(gewaehlt) >= ziel:
            break
    return {"regel": "4–6 Stationen, höchstens ein Hub, Start und Ziel inhaltlich weit auseinander",
            "mit_beleg": sum(1 for j in gewaehlt if any(s["klasse"] != "abgeleitet" for s in j["schritte"])),
            "wege": gewaehlt}


def alles(graph_pfad: Path | None = None) -> None:
    beginn = time.time()
    graph_pfad = graph_pfad or k.GRAPH
    c = sqlite3.connect(f"file:{graph_pfad.as_posix()}?mode=ro", uri=True)
    ordner = graph_pfad.parent
    netz = Netz(c)
    datei_von = _datei_von(c)

    _schreiben(ordner / "cockpit.json", _cockpit(c, graph_pfad))
    _schreiben(ordner / "karte.json", _karte(c))
    zufall = _zufallswege(netz)
    _schreiben(ordner / "zufallswege.json", zufall)

    kuratiert = []
    for a, b in KURATIERT:
        if a in netz.typ and b in netz.typ:
            w = netz.weg(a, b)
            if w:
                kuratiert.append({**netz.als_json(w), "kuratiert": True})
    wege = kuratiert + [w for w in zufall["wege"] if w["knoten"][0]["id"] not in {x["knoten"][0]["id"] for x in kuratiert}]
    _schreiben(ordner / "entdeckungen.json", {
        "gemeinsame_begriffe": _gemeinsame_begriffe(c, 24),
        "bruecken": _bruecken(c, datei_von),
        "kennzahlen": _kennzahl_matrix(c, datei_von),
        "schluessel": _schluessel_netz(c),
        "wege": wege[:12],
    })
    c.close()
    print(f"Vorberechnet in {time.time() - beginn:.0f} s: cockpit, karte, entdeckungen, "
          f"zufallswege ({len(zufall['wege'])} Wege, {zufall['mit_beleg']} mit belegter oder gemessener Kante)")


if __name__ == "__main__":
    alles()
