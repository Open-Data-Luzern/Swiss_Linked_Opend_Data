"""Baut den Verknuepfungsgraphen aus Katalog, Daten und Extraktion.

    python -m swiss_portal.graph                 # Graph neu bauen
    python -m swiss_portal.graph --ohne-einbettung

Der Graph liegt in einer eigenen Datei (verknuepfung.sqlite). Die 85
Datenbanken werden nur gelesen — sie bleiben das Substrat, der Graph ist eine
Sicht darauf, die jederzeit neu gebaut werden kann.

Jede Kante traegt ihre **Klasse**:

    belegt      steht so im Katalog oder im amtlichen Gemeindeverzeichnis
    gemessen    aus den Daten selbst bestimmt (Spaltenwerte gegen ein Verzeichnis geprueft)
    abgeleitet  von einem Sprachmodell aus dem Text gezogen, mit woertlichem Beleg

und ihren **Urheber** (katalog, gemeindeverzeichnis, regel, claude, gemma,
qwen3-embedding). Ein Beleg, der nicht woertlich im Quelltext steht, wird
nicht verworfen, sondern mit beleg_ok = 0 markiert und im Portal so gezeigt.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

from . import ki
from . import konfiguration as k

EXTRAKTION = k.PORTAL / "daten" / "extraktion"
AUSWAHL = k.PORTAL / "daten" / "auswahl.jsonl"

SCHEMA = """
CREATE TABLE knoten (
    id     TEXT PRIMARY KEY,      -- zugleich der Pfad der URI unter URI_BASIS
    typ    TEXT NOT NULL,         -- datensatz | organisation | thema | ort | begriff | raumebene | schluessel
    label  TEXT NOT NULL,
    extra  TEXT                   -- JSON
);
CREATE TABLE kante (
    von       TEXT NOT NULL REFERENCES knoten(id),
    nach      TEXT NOT NULL REFERENCES knoten(id),
    art       TEXT NOT NULL,      -- publiziert_von | thema | ort | objekt | kennzahl | konzept | raumebene | liegt_in | aehnlich | enthaelt_schluessel
    klasse    TEXT NOT NULL CHECK (klasse IN ('belegt', 'gemessen', 'abgeleitet')),
    urheber   TEXT NOT NULL,
    beleg     TEXT,
    beleg_ok  INTEGER,            -- 1 woertlich gefunden, 0 nicht gefunden, NULL nicht anwendbar
    gewicht   REAL,
    PRIMARY KEY (von, nach, art)
);
CREATE INDEX kante_nach ON kante(nach);
CREATE TABLE befund (art TEXT, gegenstand TEXT, text TEXT);
CREATE TABLE lauf (schritt TEXT, wert TEXT);
CREATE TABLE alias (id TEXT PRIMARY KEY, ziel TEXT NOT NULL);  -- zusammengefuehrte Synonyme: alte ID -> Knoten
CREATE VIRTUAL TABLE knoten_fts USING fts5(id UNINDEXED, label, text, tokenize = 'unicode61 remove_diacritics 2');
"""

KANTON_NAMEN_EXTRA = {
    "genf": "GE", "waadt": "VD", "tessin": "TI", "wallis": "VS", "freiburg": "FR", "neuenburg": "NE",
    "graubuenden": "GR", "grisons": "GR", "berne": "BE", "zurich": "ZH", "lucerne": "LU",
    "argovie": "AG", "thurgovie": "TG", "soleure": "SO", "bale-ville": "BS", "bale-campagne": "BL",
    "basel-land": "BL", "baselland": "BL", "st.gallen": "SG", "sankt gallen": "SG", "geneve": "GE",
}


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80] or "x"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def schluessel_ort(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = t.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    return re.sub(r"\s+", " ", t).strip()


class Graph:
    """Wird in <ziel>.neu gebaut und erst am Ende ausgetauscht (fertig()).

    So liest ein laufendes Portal bis zur letzten Sekunde den alten Graphen,
    und ein abgebrochener Bau laesst den alten unberuehrt.
    """

    def __init__(self, pfad: Path):
        self.ziel = pfad
        self.neu = pfad.with_suffix(pfad.suffix + ".neu")
        if self.neu.exists():
            self.neu.unlink()
        self.c = sqlite3.connect(self.neu)
        self.c.executescript(SCHEMA)

    def fertig(self) -> None:
        self.c.commit()
        self.c.close()
        os.replace(self.neu, self.ziel)

    def knoten(self, id_: str, typ: str, label: str, **extra) -> str:
        self.c.execute(
            "insert or ignore into knoten values (?, ?, ?, ?)",
            (id_, typ, label, json.dumps(extra, ensure_ascii=False) if extra else None),
        )
        return id_

    def kante(self, von, nach, art, klasse, urheber, beleg=None, beleg_ok=None, gewicht=None):
        self.c.execute(
            "insert or ignore into kante values (?, ?, ?, ?, ?, ?, ?, ?)",
            (von, nach, art, klasse, urheber, beleg, beleg_ok, gewicht),
        )

    def befund(self, art, gegenstand, text):
        self.c.execute("insert into befund values (?, ?, ?)", (art, gegenstand, text))


# --- Gemeindeverzeichnis --------------------------------------------------------

class Verzeichnis:
    def __init__(self, pfad: Path):
        zeilen = list(csv.DictReader(pfad.open(encoding="utf-8")))
        self.kantone = {z["BfsCode"]: z for z in zeilen if z["Level"] == "1"}
        bezirke = {z["HistoricalCode"]: z for z in zeilen if z["Level"] == "2"}
        self.gemeinden = [z for z in zeilen if z["Level"] == "3" and not z["ValidTo"]]
        self.bfs_nummern = {int(z["BfsCode"]) for z in self.gemeinden}
        self.kanton_von_gemeinde = {}
        for g in self.gemeinden:
            b = bezirke.get(g["Parent"])
            self.kanton_von_gemeinde[g["BfsCode"]] = self.kantone[b["Parent"]]["ShortName"] if b else None

        self.kanton_index: dict[str, str] = {}
        for z in self.kantone.values():
            kz = z["ShortName"]
            self.kanton_index[schluessel_ort(kz)] = kz
            for teil in z["Name"].split("/"):
                self.kanton_index[schluessel_ort(teil)] = kz
        for n, kz in KANTON_NAMEN_EXTRA.items():
            self.kanton_index[schluessel_ort(n)] = kz

        voll: dict[str, list[dict]] = {}
        basis: dict[str, list[dict]] = {}
        for g in self.gemeinden:
            voll.setdefault(schluessel_ort(g["Name"]), []).append(g)
            ohne_klammer = re.sub(r"\s*\(.*\)$", "", g["Name"])
            basis.setdefault(schluessel_ort(ohne_klammer), []).append(g)
            # Zweisprachige Namen: «Biel/Bienne» soll auch unter «Biel» gefunden werden.
            if "/" in ohne_klammer:
                for teil in ohne_klammer.split("/"):
                    basis.setdefault(schluessel_ort(teil), []).append(g)
        self.gemeinde_voll, self.gemeinde_basis = voll, basis

    def kanton_name(self, kz: str) -> str:
        for z in self.kantone.values():
            if z["ShortName"] == kz:
                return z["Name"]
        return kz

    def finde(self, name: str, art: str) -> tuple[str, str | None]:
        """('kanton', 'ZH') | ('gemeinde', '261') | ('schweiz', None) | ('unbekannt', None)"""
        s = schluessel_ort(re.sub(r"^(stadt|gemeinde|kanton|canton|ville de|commune de|citta di)\s+", "", name.strip(), flags=re.I))
        if s in ("schweiz", "suisse", "svizzera", "switzerland", "ch"):
            return "schweiz", None
        if art == "kanton" and s in self.kanton_index:
            return "kanton", self.kanton_index[s]
        if art in ("gemeinde", "andere", "region", "bezirk") or art not in ("kanton",):
            for index in (self.gemeinde_voll, self.gemeinde_basis):
                treffer = index.get(s)
                if treffer and len(treffer) == 1:
                    return "gemeinde", treffer[0]["BfsCode"]
                if treffer and len(treffer) > 1:
                    return "mehrdeutig", None
        if s in self.kanton_index:
            return "kanton", self.kanton_index[s]
        return "unbekannt", None


# --- Bau ------------------------------------------------------------------------

def _org_db(datei: str) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{(k.DATENBANKEN / f'{datei}.sqlite').as_posix()}?mode=ro&immutable=1", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _quelltext(e: dict) -> str:
    teile = [e["titel"], e["beschreibung"], " ".join(e["schlagworte"]), " ".join(e["thema"]), " ".join(e["spalten"])]
    return norm(" ".join(t for t in teile if t))


def _extraktionen(urheber: str) -> tuple[dict[str, dict], str]:
    """Liest die Extraktion genau eines Urhebers — nie gemischt."""
    ergebnisse: dict[str, dict] = {}
    # claude_teil_NN (Probelauf) und claude_voll_NNNN (Vollausbau)
    for datei in sorted(EXTRAKTION.glob(f"{urheber}_*.jsonl")):
        if datei.name.endswith(".fehler.jsonl"):
            continue
        for zeile in datei.read_text(encoding="utf-8").split("\n"):
            if zeile.strip():
                d = json.loads(zeile)
                ergebnisse[d["datensatz_id"]] = d
    return ergebnisse, urheber


BFS_SPALTE = re.compile(r"(bfs|gem|gde|gmd|commune|comune).*(nr|nummer|num|code|id|no)$|^bfs$|^gdenr|^bfs_?nr|^gemeindenummer$")
KANTON_SPALTE = re.compile(r"^(kanton|kt|canton|cantone|kantonskuerzel|kanton_kurz|kanton_id)$")


def _gemessene_schluessel(g: Graph, vz: Verzeichnis, e: dict, ds_id: str) -> None:
    """Prueft Spalten mit Gemeinde- oder Kantonsschluessel an ihren Werten."""
    c = _org_db(e["datei"])
    spalten = c.execute(
        "select s.tabelle, s.name, s.name_original from daten_spalte s join daten_tabelle t on t.tabelle = s.tabelle "
        "where t.datensatz_id = ?",
        (e["datensatz_id"],),
    ).fetchall()
    kantone = set(vz.kanton_index.values())
    for sp in spalten:
        name = sp["name"].lower()
        art = "gemeinde" if BFS_SPALTE.search(name) else "kanton" if KANTON_SPALTE.search(name) else None
        if not art:
            continue
        # Stadtkreise und Quartiere tragen oft Nummern 1..n — die sind zufaellig
        # auch gueltige BFS-Nummern (Zuercher Gemeinden). Gemessen am 17.11.2026
        # an «stadtkreis_bfs_nr» in Winterthur.
        if art == "gemeinde" and re.search(r"kreis|quartier|bezirk|zone", name):
            continue
        try:
            werte = [r[0] for r in c.execute(f'select distinct "{sp["name"]}" from "{sp["tabelle"]}" where "{sp["name"]}" is not null limit 500')]
        except sqlite3.Error:
            continue
        if not werte:
            continue
        if art == "gemeinde":
            zahlen = sorted({int(str(w).strip()) for w in werte if str(w).strip().isdigit()})
            if zahlen and zahlen == list(range(1, len(zahlen) + 1)):
                continue  # eine Aufzaehlung 1..n ist kein Gemeindeschluessel
            gueltig = sum(1 for w in werte if str(w).strip().isdigit() and int(str(w).strip()) in vz.bfs_nummern)
        else:
            gueltig = sum(1 for w in werte if str(w).strip().upper() in kantone or schluessel_ort(str(w)) in vz.kanton_index)
        anteil = gueltig / len(werte)
        if anteil >= 0.8:
            ziel = g.knoten(
                f"schluessel/{art}",
                "schluessel",
                "Gemeinde (BFS-Nummer)" if art == "gemeinde" else "Kanton",
            )
            g.kante(ds_id, ziel, "enthaelt_schluessel", "gemessen", "regel",
                    beleg=f'Spalte «{sp["name_original"]}»: {gueltig} von {len(werte)} Werten im Verzeichnis',
                    beleg_ok=1, gewicht=round(anteil, 3))
            break
    c.close()


def bauen(mit_einbettung: bool = True, urheber: str = "claude", ziel: Path | None = None) -> None:
    start = time.time()
    g = Graph(ziel or k.GRAPH)
    vz = Verzeichnis(k.GEMEINDEVERZEICHNIS)
    # split("\n") statt splitlines(): Beschreibungen enthalten U+2028 und
    # aehnliche Trenner, an denen splitlines() mitten im JSON trennen wuerde.
    auswahl = [json.loads(z) for z in AUSWAHL.read_text(encoding="utf-8").split("\n") if z.strip()]
    extraktion, urheber = _extraktionen(urheber)
    g.c.execute("insert into lauf values ('urheber_extraktion', ?)", (urheber,))

    ort_knoten: dict[str, str] = {}

    def ort(art: str, schl: str | None, roh: str) -> str:
        if art == "schweiz":
            return g.knoten("ort/schweiz", "ort", "Schweiz", ebene="schweiz", amtlich=True)
        if art == "kanton":
            id_ = g.knoten(f"ort/kanton/{schl}", "ort", f"Kanton {vz.kanton_name(schl)}", ebene="kanton", kuerzel=schl, amtlich=True)
            g.kante(id_, ort("schweiz", None, ""), "liegt_in", "belegt", "gemeindeverzeichnis")
            return id_
        if art == "gemeinde":
            name = next(z["Name"] for z in vz.gemeinden if z["BfsCode"] == schl)
            id_ = g.knoten(f"ort/gemeinde/{schl}", "ort", name, ebene="gemeinde", bfs=int(schl), amtlich=True)
            kz = vz.kanton_von_gemeinde.get(schl)
            if kz:
                g.kante(id_, ort("kanton", kz, ""), "liegt_in", "belegt", "gemeindeverzeichnis")
            return id_
        return g.knoten(f"ort/frei/{slug(roh)}", "ort", roh, ebene="frei", amtlich=False)

    for e in auswahl:
        ds = g.knoten(f"datensatz/{e['datensatz_id']}", "datensatz", e["titel"],
                      datei=e["datei"], datensatz_id=e["datensatz_id"], organisation=e["organisation"],
                      grund=e["grund"])
        org = g.knoten(f"organisation/{e['datei']}", "organisation", e["organisation"], datei=e["datei"])
        g.kante(ds, org, "publiziert_von", "belegt", "katalog")
        for t in e["thema"]:
            g.kante(ds, g.knoten(f"thema/{slug(t)}", "thema", t), "thema", "belegt", "katalog")

        try:
            _gemessene_schluessel(g, vz, e, ds)
        except sqlite3.Error as fehler:
            g.befund("schluessel_nicht_pruefbar", e["datensatz_id"], str(fehler))

        x = extraktion.get(e["datensatz_id"])
        if not x:
            g.befund("keine_extraktion", e["datensatz_id"], "Fuer diesen Datensatz liegt keine Extraktion vor.")
            continue
        quelle = _quelltext(e)

        def ok(beleg: str | None) -> int | None:
            if not beleg:
                return 0
            if beleg == "zeitraum":
                return 1
            return 1 if norm(beleg) in quelle else 0

        for o in x.get("orte", []):
            art, schl = vz.finde(o["name"], o.get("art", "andere"))
            if art in ("mehrdeutig", "unbekannt") and o.get("art") in ("gemeinde", "kanton"):
                g.befund(f"ort_{art}", e["datensatz_id"], o["name"])
            ziel = ort(art if art not in ("mehrdeutig", "unbekannt") else "frei", schl, o["name"])
            g.kante(ds, ziel, "ort", "abgeleitet", urheber, o.get("beleg"), ok(o.get("beleg")))
        for ebene in x.get("raumebene", []):
            g.kante(ds, g.knoten(f"raumebene/{slug(ebene)}", "raumebene", ebene.capitalize()), "raumebene", "abgeleitet", urheber)
        for feld, art in (("objekte", "objekt"), ("kennzahlen", "kennzahl"), ("konzepte", "konzept")):
            for b in x.get(feld, []):
                begriff = b["begriff"].strip()
                if not begriff:
                    continue
                ziel = g.knoten(f"begriff/{slug(begriff)}", "begriff", begriff)
                g.kante(ds, ziel, art, "abgeleitet", urheber, b.get("beleg"), ok(b.get("beleg")))
        zeit = x.get("zeit") or {}
        g.c.execute(
            "update knoten set extra = json_set(coalesce(extra, '{}'), '$.zeit', json(?)) where id = ?",
            (json.dumps(zeit, ensure_ascii=False), ds),
        )

    if mit_einbettung:
        _aehnlichkeit(g)
        _synonyme(g)
    _volltext(g, auswahl)

    for schritt, wert in (
        ("knoten", g.c.execute("select count(*) from knoten").fetchone()[0]),
        ("kanten", g.c.execute("select count(*) from kante").fetchone()[0]),
        ("dauer_s", round(time.time() - start, 1)),
        ("gebaut_am", time.strftime("%Y-%m-%d %H:%M")),
    ):
        g.c.execute("insert into lauf values (?, ?)", (schritt, str(wert)))
    g.c.commit()
    print(f"Graph: {g.ziel}")
    for r in g.c.execute("select typ, count(*) from knoten group by 1 order by 2 desc"):
        print(f"  Knoten {r[0]:<14} {r[1]:6d}")
    for r in g.c.execute("select art, klasse, count(*), sum(beleg_ok = 0) from kante group by 1, 2 order by 3 desc"):
        print(f"  Kante  {r[0]:<20} {r[1]:<10} {r[2]:6d}  Beleg nicht gefunden: {r[3] or 0}")
    for r in g.c.execute("select art, count(*) from befund group by 1"):
        print(f"  Befund {r[0]:<26} {r[1]:6d}")
    lauf = {r[0]: r[1] for r in g.c.execute("select schritt, wert from lauf")}
    lauf["klassen"] = {r[0]: r[1] for r in g.c.execute("select klasse, count(*) from kante group by 1")}
    lauf["datensaetze"] = g.c.execute("select count(*) from knoten where typ = 'datensatz'").fetchone()[0]
    _laeufe_seit_vorher(g.ziel)
    g.fertig()
    with (g.ziel.parent / "laeufe.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(lauf, ensure_ascii=False) + "\n")
    from . import vorberechnen
    vorberechnen.alles(g.ziel)


def _laeufe_seit_vorher(ziel: Path) -> None:
    """Beim ersten Bau mit Laufprotokoll: den bisherigen Graphen als ersten Eintrag uebernehmen."""
    datei = ziel.parent / "laeufe.jsonl"
    if datei.exists() or not ziel.exists():
        return
    c = sqlite3.connect(f"file:{ziel.as_posix()}?mode=ro", uri=True)
    lauf = {r[0]: r[1] for r in c.execute("select schritt, wert from lauf")}
    lauf["klassen"] = {r[0]: r[1] for r in c.execute("select klasse, count(*) from kante group by 1")}
    lauf["datensaetze"] = c.execute("select count(*) from knoten where typ = 'datensatz'").fetchone()[0]
    c.close()
    datei.write_text(json.dumps(lauf, ensure_ascii=False) + "\n", encoding="utf-8")


def _synonyme(g: Graph, schwelle: float = 0.99) -> None:
    """Fuehrt Begriffe zusammen, die die Einbettung als praktisch gleich erkennt
    (Kartografie/Kartographie, Bruttoinlandprodukt/Bruttoinlandsprodukt).

    Der Knoten mit den meisten Verbindungen bleibt; die anderen werden zu Aliassen.
    Ihre Kanten wandern auf ihn, ihre IDs leiten weiter (Tabelle alias).
    """
    paare = g.c.execute("select von, nach from kante where art = 'aehnlich' and gewicht >= ?", (schwelle,)).fetchall()
    eltern: dict[str, str] = {}

    def wurzel(x: str) -> str:
        while eltern.get(x, x) != x:
            x = eltern[x]
        return x

    for a, b in paare:
        eltern.setdefault(a, a)
        eltern.setdefault(b, b)
        eltern[wurzel(a)] = wurzel(b)
    gruppen: dict[str, list[str]] = {}
    for x in eltern:
        gruppen.setdefault(wurzel(x), []).append(x)
    grad = dict(g.c.execute("select id, (select count(*) from kante where von = id or nach = id) from knoten where id in (%s)"
                            % ",".join("?" * len(eltern)), list(eltern)).fetchall()) if eltern else {}
    label = dict(g.c.execute("select id, label from knoten where id in (%s)" % ",".join("?" * len(eltern)), list(eltern)).fetchall()) if eltern else {}
    n = 0
    for mitglieder in gruppen.values():
        kanon = max(mitglieder, key=lambda m: (grad.get(m, 0), -len(label.get(m, "")), m))
        aliase = []
        for alias in mitglieder:
            if alias == kanon:
                continue
            for z in g.c.execute("select * from kante where von = ? or nach = ?", (alias, alias)).fetchall():
                von = kanon if z[0] == alias else z[0]
                nach = kanon if z[1] == alias else z[1]
                if von != nach:
                    g.c.execute("insert or ignore into kante values (?, ?, ?, ?, ?, ?, ?, ?)", (von, nach, *z[2:]))
            g.c.execute("delete from kante where von = ? or nach = ?", (alias, alias))
            g.c.execute("delete from knoten where id = ?", (alias,))
            g.c.execute("insert or replace into alias values (?, ?)", (alias, kanon))
            g.c.execute("update alias set ziel = ? where ziel = ?", (kanon, alias))
            aliase.append(label.get(alias, alias))
            n += 1
        g.c.execute("update knoten set extra = json_set(coalesce(extra, '{}'), '$.aliase', json(?)) where id = ?",
                    (json.dumps(aliase, ensure_ascii=False), kanon))
    g.c.execute("insert into lauf values ('synonyme', ?)", (str(n),))
    print(f"  Synonyme: {n} Begriffe in {len(gruppen)} Gruppen zusammengefuehrt (Aehnlichkeit >= {schwelle})")


def _aehnlichkeit(g: Graph, nachbarn: int = 3) -> None:
    """Verbindet Begriffe, deren Einbettungen sich gegenseitig unter den naechsten sind.

    Kein fester Schwellenwert allein: qwen3-embedding drueckt die Kosinuswerte
    zusammen (gemessen: «Leerwohnungsziffer»/«logements vacants» 0.61,
    «Leerwohnungsziffer»/«Hundekotbehaelter» 0.51). Verbunden wird darum nur,
    wer sich **gegenseitig** unter den drei naechsten Nachbarn hat und ueber
    einer Mindestaehnlichkeit liegt — als skos:related, nicht als Gleichsetzung.
    """
    import numpy as np  # nur hier gebraucht; 20'000 Begriffe sind in reinem Python nicht zu rechnen

    begriffe = g.c.execute("select id, label from knoten where typ = 'begriff' order by id").fetchall()
    if len(begriffe) < 3:
        return
    texte = [f"Instruct: Gib den Fachbegriff aus der Verwaltungsstatistik wieder\nQuery: {b[1]}" for b in begriffe]
    vektoren = _einbettungen(texte)
    m = np.asarray(vektoren, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-12

    # Naechste Nachbarn blockweise: 20'000 x 20'000 auf einmal waeren 1.6 GB.
    naechste: list[dict[int, float]] = []
    for start in range(0, len(m), 1024):
        block = m[start : start + 1024] @ m.T
        for zeile, i in enumerate(range(start, min(start + 1024, len(m)))):
            block[zeile, i] = -1.0
        top = np.argpartition(-block, nachbarn, axis=1)[:, :nachbarn]
        for zeile in range(block.shape[0]):
            naechste.append({int(j): float(block[zeile, j]) for j in top[zeile]})
    werte = sorted(s for nb in naechste for s in nb.values())
    schwelle = werte[len(werte) // 2] if werte else 1.0  # Median der Nachbarschaften
    n = 0
    for i, (id_i, _) in enumerate(begriffe):
        for j, s in naechste[i].items():
            if i < j and i in naechste[j] and s >= schwelle:
                g.kante(id_i, begriffe[j][0], "aehnlich", "abgeleitet", "qwen3-embedding", gewicht=round(s, 3))
                n += 1
    g.c.execute("insert into lauf values ('aehnlich_schwelle', ?)", (f"{schwelle:.3f}",))
    print(f"  Aehnlichkeit: {len(begriffe)} Begriffe, {n} Kanten, Schwelle {schwelle:.3f}")


EINBETTUNGEN = k.PORTAL / "daten" / "einbettungen.sqlite"


def _einbettungen(texte: list[str], stapel: int = 32) -> list[list[float]]:
    """Vektoren mit Zwischenspeicher in SQLite, nach jedem Stapel geschrieben.

    690 Begriffe kosten auf spark5 rund 7 Minuten; beim Vollausbau sind es
    zehntausende. Ein Abbruch kostet so hoechstens einen Stapel. Einen alten
    JSON-Zwischenspeicher (Probelauf) uebernimmt die Funktion einmalig.
    """
    import numpy as np

    c = sqlite3.connect(EINBETTUNGEN)
    c.execute("create table if not exists vektor (text text primary key, modell text, v blob)")
    alt = k.PORTAL / "daten" / "einbettungen_cache.json"
    if alt.exists():
        for t, v in json.loads(alt.read_text(encoding="utf-8")).items():
            c.execute("insert or ignore into vektor values (?, ?, ?)", (t, k.EMB_MODELL, np.asarray(v, dtype=np.float32).tobytes()))
        c.commit()
        alt.rename(alt.with_suffix(".json.uebernommen"))
    vorhanden = {t for (t,) in c.execute("select text from vektor")}
    fehlend = [t for t in dict.fromkeys(texte) if t not in vorhanden]
    if fehlend:
        print(f"  Einbettung: {len(fehlend)} neue Begriffe (spark5, ~1.6 je Sekunde)", flush=True)
    for i in range(0, len(fehlend), stapel):
        teil = fehlend[i : i + stapel]
        for t, v in zip(teil, ki.einbetten(teil, stapel=stapel)):
            c.execute("insert or replace into vektor values (?, ?, ?)", (t, k.EMB_MODELL, np.asarray(v, dtype=np.float32).tobytes()))
        c.commit()
        if (i // stapel) % 20 == 0:
            print(f"    {min(i + stapel, len(fehlend))}/{len(fehlend)}", flush=True)
    werte = {t: np.frombuffer(v, dtype=np.float32) for t, v in c.execute("select text, v from vektor")}
    c.close()
    return [werte[t] for t in texte]


def _volltext(g: Graph, auswahl: list[dict]) -> None:
    texte = {f"datensatz/{e['datensatz_id']}": f"{e['titel']} {e['beschreibung']} {' '.join(e['schlagworte'])} {' '.join(e['spalten'])}"
             for e in auswahl}
    for id_, label, extra in g.c.execute("select id, label, extra from knoten").fetchall():
        aliase = " ".join(json.loads(extra).get("aliase", [])) if extra else ""
        g.c.execute("insert into knoten_fts values (?, ?, ?)", (id_, label, f"{aliase} {texte.get(id_, '')}".strip()))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ohne-einbettung", action="store_true")
    p.add_argument("--urheber", default="claude", help="wessen Extraktion: claude | gemma")
    p.add_argument("--ziel", type=Path, help="anderer Pfad fuer den Graphen (z. B. zum Vergleich)")
    a = p.parse_args()
    bauen(mit_einbettung=not a.ohne_einbettung, urheber=a.urheber, ziel=a.ziel)


if __name__ == "__main__":
    main()
