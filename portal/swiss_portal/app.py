"""Die Web-API des Prototyps.

    python -m uvicorn swiss_portal.app:app --port 8040

Liest den Graphen (verknuepfung.sqlite) und die 85 Datenbanken nur lesend.
Zugang mit einem gemeinsamen Login (PORTAL_BENUTZER / PORTAL_PASSWORT aus
.env); sind beide leer, ist das Portal offen — nur fuer die lokale Entwicklung.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from collections import OrderedDict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ki, rdf
from .netz import Netz
from . import konfiguration as k

app = FastAPI(title="Swiss Open Linked Data", docs_url=None, redoc_url=None)

# --- Zugang -----------------------------------------------------------------------


@app.middleware("http")
async def zugang(request: Request, call_next):
    if k.PORTAL_BENUTZER and k.PORTAL_PASSWORT and request.url.path != "/gesund":
        kopf = request.headers.get("authorization", "")
        ok = False
        if kopf.lower().startswith("basic "):
            try:
                benutzer, _, passwort = base64.b64decode(kopf[6:]).decode("utf-8").partition(":")
                ok = secrets.compare_digest(benutzer, k.PORTAL_BENUTZER) and secrets.compare_digest(passwort, k.PORTAL_PASSWORT)
            except (ValueError, UnicodeDecodeError):
                ok = False
        if not ok:
            return Response("Anmeldung erforderlich", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Swiss Open Linked Data", charset="UTF-8"'})
    return await call_next(request)


_anfragen: dict[str, deque] = {}
_sperre = threading.Lock()


def _begrenzen(request: Request) -> None:
    """Schuetzt die GPU: hoechstens KI_ANFRAGEN_PRO_STUNDE KI-Anfragen je Adresse."""
    adresse = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    jetzt = time.time()
    with _sperre:
        q = _anfragen.setdefault(adresse, deque())
        while q and q[0] < jetzt - 3600:
            q.popleft()
        if len(q) >= k.KI_ANFRAGEN_PRO_STUNDE:
            raise HTTPException(429, "Zu viele KI-Anfragen in der letzten Stunde. Bitte spaeter wieder.")
        q.append(jetzt)


# --- Datenzugriff -----------------------------------------------------------------


def graph() -> sqlite3.Connection:
    if not k.GRAPH.exists():
        raise HTTPException(503, "Der Graph ist noch nicht gebaut (python -m swiss_portal.graph).")
    c = sqlite3.connect(f"file:{k.GRAPH.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def org_db(datei: str) -> sqlite3.Connection:
    if not re.fullmatch(r"[a-z0-9_\-]+", datei):
        raise HTTPException(400, "Ungueltiger Dateiname")
    pfad = k.DATENBANKEN / f"{datei}.sqlite"
    if not pfad.exists():
        raise HTTPException(404, "Datenbank nicht gefunden")
    c = sqlite3.connect(f"file:{pfad.as_posix()}?mode=ro&immutable=1", uri=True, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _extra(zeile) -> dict:
    return json.loads(zeile["extra"]) if zeile["extra"] else {}


def _knoten_kurz(z) -> dict:
    return {"id": z["id"], "typ": z["typ"], "label": z["label"], **_extra(z)}


_BESTAND: dict = {}


def _bestand_zaehlen() -> None:
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
    _BESTAND.update(gesamt)


threading.Thread(target=_bestand_zaehlen, daemon=True).start()


# --- Uebersicht und Suche ---------------------------------------------------------


@app.get("/gesund")
def gesund():
    return {"ok": True}


@app.get("/api/uebersicht")
def uebersicht():
    c = graph()
    lauf = {r["schritt"]: r["wert"] for r in c.execute("select * from lauf")}
    typen = {r[0]: r[1] for r in c.execute("select typ, count(*) from knoten group by 1")}
    klassen = {r[0]: r[1] for r in c.execute("select klasse, count(*) from kante group by 1")}
    bestand = _BESTAND
    if not bestand and (k.GRAPH.parent / "cockpit.json").exists():
        bestand = _json_datei("cockpit.json").get("bestand", {})
    return {"bestand": bestand, "graph": {"knoten": typen, "kanten": klassen, "lauf": lauf}}


def _fts_anfrage(q: str) -> str:
    woerter = re.findall(r"\w+", q, flags=re.UNICODE)
    return " OR ".join(f'"{w}"*' for w in woerter if len(w) > 1)


def _ohne_akzent(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


TYP_RANG = {"begriff": 0, "ort": 1, "datensatz": 2, "schluessel": 3, "organisation": 4, "thema": 5, "raumebene": 6}


def _rang(z, qn: str) -> int:
    """Kleiner ist besser. Exakter Name vor Alias vor Wortanfang im Namen
    (Begriff vor Ort vor Datensatz) vor Treffern nur im Beschreibungstext:
    «Schaf» liefert zuerst den Begriff Schaf, dann Schaffhausen."""
    label = _ohne_akzent(z["label"])
    if label == qn:
        return 0
    aliase = [_ohne_akzent(a) for a in (_extra(z).get("aliase") or [])]
    if qn in aliase:
        return 1
    woerter = re.findall(r"\w+", label)
    if label.startswith(qn) or any(w.startswith(qn) for w in woerter):
        return 2 + min(TYP_RANG.get(z["typ"], 6), 3)
    return 7


@app.get("/api/suche")
def suche(q: str, typ: str | None = None, anzahl: int = 25, gruppiert: bool = False):
    c = graph()
    anfrage = _fts_anfrage(q)
    if not anfrage:
        return {} if gruppiert else []
    sql = "select k.id, k.typ, k.label, k.extra from knoten_fts f join knoten k on k.id = f.id where knoten_fts match ? "
    werte: list = [anfrage]
    if typ:
        sql += "and k.typ in (%s) " % ",".join("?" * len(typ.split(",")))
        werte += typ.split(",")
    sql += "order by bm25(knoten_fts, 0, 5.0, 1.0) limit 400"
    netz = _netz(c)
    qn = _ohne_akzent(q)
    treffer = sorted(c.execute(sql, werte).fetchall(),
                     key=lambda z: (_rang(z, qn), TYP_RANG.get(z["typ"], 6), -netz.grad.get(z["id"], 0), z["label"]))
    liste = [{**_knoten_kurz(z), "grad": netz.grad.get(z["id"], 0)} for z in treffer if z["typ"] not in ("raumebene", "thema")]
    if not gruppiert:
        return liste[:anzahl]
    gruppen: dict[str, list] = {"begriff": [], "ort": [], "datensatz": []}
    for t in liste:
        g = gruppen.get(t["typ"])
        if g is not None and len(g) < 4:
            g.append({"id": t["id"], "typ": t["typ"], "label": t["label"], "grad": t["grad"]})
    return gruppen


# --- Knoten ----------------------------------------------------------------------


def _katalog(datei: str, datensatz_id: str) -> dict:
    c = org_db(datei)
    z = c.execute(
        "select titel_de, beschreibung_de, organisation, lizenz, lizenz_text, landingpage, opendata_url, "
        "zeitraum_von, zeitraum_bis, aktualisiert, aktualisierungsintervall, schlagworte "
        "from dim_datensatz where id = ?", (datensatz_id,)).fetchone()
    tabellen = [dict(t) for t in c.execute(
        "select t.tabelle, t.zeilen, t.spalten, t.format, s.titel_de as datensammlung, s.url "
        "from daten_tabelle t join dim_datensammlung s on s.id = t.datensammlung_id "
        "where t.datensatz_id = ? order by t.zeilen desc", (datensatz_id,))]
    sammlungen = c.execute("select count(*) from dim_datensammlung where datensatz_id = ?", (datensatz_id,)).fetchone()[0]
    c.close()
    return {**(dict(z) if z else {}), "tabellen": tabellen, "datensammlungen": sammlungen}


def _alias(c: sqlite3.Connection, id: str) -> str:
    """Zusammengefuehrte Synonyme: alte IDs fuehren auf den verbleibenden Knoten."""
    if c.execute("select 1 from knoten where id = ?", (id,)).fetchone():
        return id
    try:
        z = c.execute("select ziel from alias where id = ?", (id,)).fetchone()
    except sqlite3.OperationalError:
        return id
    return z[0] if z else id


@app.get("/api/knoten")
def knoten(id: str):
    c = graph()
    id = _alias(c, id)
    n = c.execute("select * from knoten where id = ?", (id,)).fetchone()
    if not n:
        raise HTTPException(404, "Knoten nicht gefunden")
    kanten = []
    for e in c.execute(
        "select e.*, k.typ as n_typ, k.label as n_label, k.extra as n_extra, "
        "case when e.von = ? then 'aus' else 'ein' end as richtung "
        "from kante e join knoten k on k.id = case when e.von = ? then e.nach else e.von end "
        "where e.von = ? or e.nach = ? order by e.art, k.label", (id, id, id, id)):
        kanten.append({
            "art": e["art"], "klasse": e["klasse"], "urheber": e["urheber"], "beleg": e["beleg"],
            "beleg_ok": e["beleg_ok"], "gewicht": e["gewicht"], "richtung": e["richtung"],
            "nachbar": {"id": e["von"] if e["richtung"] == "ein" else e["nach"], "typ": e["n_typ"],
                        "label": e["n_label"], **(json.loads(e["n_extra"]) if e["n_extra"] else {})},
        })
    antwort = {**_knoten_kurz(n), "kanten": kanten, "uri": f"{k.URI_BASIS}{n['id']}"}
    if n["typ"] == "datensatz":
        x = _extra(n)
        antwort["katalog"] = _katalog(x["datei"], x["datensatz_id"])
    return antwort


# Knoten, ueber die fast alles verbunden ist. Fuer Graph und Pfad sind sie
# Laerm: Dass zwei Datensaetze beide «Gemeinde» als Raumebene haben, ist keine
# Entdeckung.
# Anbieter erscheinen nur im Steckbrief eines Datensatzes, nicht in Grafiken (Brief 18.11.2026).
NABEN = ("raumebene", "thema", "organisation")


@app.get("/api/graph")
def teilgraph(id: str, tiefe: int = 2, max_knoten: int = 120, naben: bool = False):
    c = graph()
    id = _alias(c, id)
    if not c.execute("select 1 from knoten where id = ?", (id,)).fetchone():
        raise HTTPException(404, "Knoten nicht gefunden")
    gesehen = {id: 0}
    rand = [id]
    kanten: dict[tuple, dict] = {}
    for stufe in range(1, tiefe + 1):
        neu = []
        for kn in rand:
            for e in c.execute(
                "select e.*, k1.typ t1, k2.typ t2 from kante e join knoten k1 on k1.id = e.von "
                "join knoten k2 on k2.id = e.nach where e.von = ? or e.nach = ?", (kn, kn)):
                anderer = e["nach"] if e["von"] == kn else e["von"]
                anderer_typ = e["t2"] if e["von"] == kn else e["t1"]
                if not naben and anderer_typ in NABEN and anderer != id:
                    continue
                if anderer == "ort/schweiz" and id != "ort/schweiz":
                    continue
                if anderer not in gesehen:
                    if len(gesehen) >= max_knoten:
                        continue
                    gesehen[anderer] = stufe
                    neu.append(anderer)
                kanten[(e["von"], e["nach"], e["art"])] = {
                    "von": e["von"], "nach": e["nach"], "art": e["art"], "klasse": e["klasse"],
                    "urheber": e["urheber"], "beleg": e["beleg"], "beleg_ok": e["beleg_ok"]}
        rand = neu
    platz = ",".join("?" * len(gesehen))
    knoten_liste = [{**_knoten_kurz(z), "stufe": gesehen[z["id"]]}
                    for z in c.execute(f"select * from knoten where id in ({platz})", list(gesehen))]
    return {"zentrum": id, "knoten": knoten_liste,
            "kanten": [v for v in kanten.values() if v["von"] in gesehen and v["nach"] in gesehen]}


_NETZ: dict = {}
_WEGE: OrderedDict = OrderedDict()


def _stand() -> tuple:
    st = k.GRAPH.stat()
    return (st.st_mtime_ns, st.st_size)


def _netz(c: sqlite3.Connection) -> Netz:
    """Der ganze Graph im Speicher — neu geladen nur, wenn die Graph-Datei sich geaendert hat."""
    stand = _stand()
    with _sperre:
        if _NETZ.get("stand") != stand:
            _NETZ.update(stand=stand, netz=Netz(c))
            _WEGE.clear()
        return _NETZ["netz"]


@app.get("/api/pfad")
def pfad(von: str, nach: str, k: int = 1, hubs: str = "an"):
    """Kuerzester Weg ohne Umweg ueber Naben; mit k > 1 bis zu k Wege mit
    verschiedenen Zwischenstationen; hubs=aus meidet Knoten mit sehr vielen
    Verbindungen (Gemeinde, Abstimmung, Kantone)."""
    c = graph()
    netz = _netz(c)
    von, nach = _alias(c, von), _alias(c, nach)
    if von not in netz.typ or nach not in netz.typ:
        raise HTTPException(404, "Knoten nicht gefunden")
    k_ = max(1, min(k, 4))
    schluessel = (_NETZ["stand"], von, nach, k_, hubs)
    with _sperre:
        if schluessel in _WEGE:
            _WEGE.move_to_end(schluessel)
            return _WEGE[schluessel]
    wege = netz.wege(von, nach, k=k_, hubs=hubs != "aus")
    antwort = {"gefunden": False, "knoten": [], "schritte": [], "wege": []} if not wege else \
        {"gefunden": True, **netz.als_json(wege[0]), "wege": [netz.als_json(w) for w in wege]}
    with _sperre:
        _WEGE[schluessel] = antwort
        while len(_WEGE) > 512:
            _WEGE.popitem(last=False)
    return antwort


@app.get("/api/aehnliche")
def aehnliche(id: str, anzahl: int = 8):
    """Knoten gleichen Typs, die die meisten Nachbarn teilen (ueber Datensaetze
    bzw. Begriffe, ohne Hubs). Aehnlichkeit aus der Einbettung kommt zuerst."""
    c = graph()
    netz = _netz(c)
    id = _alias(c, id)
    if id not in netz.typ:
        raise HTTPException(404, "Knoten nicht gefunden")
    typ = netz.typ[id]
    zaehler: dict[str, int] = {}
    eingebettet = set()
    for m, e in netz.nachbarn.get(id, ()):
        if e[2] == "aehnlich":
            eingebettet.add(m)
            continue
        if netz.nabe(m) or netz.hub(m):
            continue
        for x, _ in netz.nachbarn.get(m, ()):
            if x != id and netz.typ.get(x) == typ:
                zaehler[x] = zaehler.get(x, 0) + 1
    rang = sorted(set(zaehler) | eingebettet, key=lambda x: (x not in eingebettet, -zaehler.get(x, 0), netz.label[x]))
    return [{"id": x, "typ": netz.typ[x], "label": netz.label[x], "gemeinsam": zaehler.get(x, 0),
             "aehnlich": x in eingebettet} for x in rang[:anzahl]]


# --- Vorberechnet beim Graphenbau (swiss_portal.vorberechnen) ---------------------

_DATEIEN: dict = {}


def _vorberechnet(name: str):
    pfad = k.GRAPH.parent / name
    if not pfad.exists():
        raise HTTPException(503, f"{name} fehlt — python -m swiss_portal.vorberechnen")
    return pfad


def _json_datei(name: str):
    pfad = _vorberechnet(name)
    st = pfad.stat()
    with _sperre:
        if _DATEIEN.get(name, (None,))[0] != st.st_mtime_ns:
            _DATEIEN[name] = (st.st_mtime_ns, json.loads(pfad.read_text(encoding="utf-8")))
        return _DATEIEN[name][1]


ZWISCHENSPEICHER = {"Cache-Control": "max-age=3600"}


@app.get("/api/cockpit")
def cockpit():
    return FileResponse(_vorberechnet("cockpit.json"), media_type="application/json", headers=ZWISCHENSPEICHER)


@app.get("/api/karte")
def karte(mass: str = "datensaetze"):
    if mass != "datensaetze":
        raise HTTPException(400, "Bisher gibt es nur mass=datensaetze")
    return FileResponse(_vorberechnet("karte.json"), media_type="application/json", headers=ZWISCHENSPEICHER)


@app.get("/api/zufallsweg")
def zufallsweg(ohne: str = ""):
    """Ein ueberraschender Weg aus den 50 vorberechneten. «ohne» nennt die
    Nummern, die der Besucher schon gesehen hat — so wiederholt sich nichts."""
    wege = _json_datei("zufallswege.json")["wege"]
    if not wege:
        raise HTTPException(503, "Keine Wege vorberechnet")
    gesehen = {int(x) for x in ohne.split(",") if x.strip().isdigit()}
    frei = [i for i in range(len(wege)) if i not in gesehen] or list(range(len(wege)))
    nr = secrets.choice(frei)
    return {**wege[nr], "nr": nr, "anzahl": len(wege)}


# ---------- Diagramme und Vergleich (Rückmeldung Sprintplanung 19.11.2026) ----
# Jede Zahl kommt per Abfrage aus der Tabelle; Spalten- und Tabellennamen werden
# gegen das Schema geprüft, Werte nur als Parameter übergeben.

AGGREGATE = {"anzahl": "count(*)", "summe": "sum({s})", "mittel": "avg({s})", "max": "max({s})", "min": "min({s})"}
AGG_NAME = {"anzahl": "Anzahl Zeilen", "summe": "Summe", "mittel": "Mittelwert", "max": "Maximum", "min": "Minimum"}


def _spalten_von(c: sqlite3.Connection, tabelle: str) -> list[str]:
    return [r[1] for r in c.execute(f'pragma table_info("{tabelle}")')]


def _spalte_pruefen(spalten: list[str], s: str, wofuer: str) -> str:
    if s not in spalten:
        raise HTTPException(400, f"Unbekannte Spalte für {wofuer}: {s}")
    return s


def _herkunft(c: sqlite3.Connection, tabelle: str) -> dict | None:
    h = c.execute(
        "select s.titel_de, s.url, d.titel_de as datensatz, d.organisation, d.lizenz, d.opendata_url "
        "from daten_tabelle t join dim_datensammlung s on s.id = t.datensammlung_id "
        "join dim_datensatz d on d.id = t.datensatz_id where t.tabelle = ?", (tabelle,)).fetchone()
    return dict(h) if h else None


def _mit_zeitlimit(c: sqlite3.Connection, sql: str, parameter: tuple) -> list:
    beginn = time.time()
    c.set_progress_handler(lambda: 1 if time.time() - beginn > 20 else 0, 10000)
    try:
        return c.execute(sql, parameter).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(504 if "interrupt" in str(e) else 400, f"Abfrage abgebrochen: {e}")
    finally:
        c.set_progress_handler(None, 0)


def _ausdruck(agg: str, spalte: str) -> str:
    if agg not in AGGREGATE:
        raise HTTPException(400, "Unbekannte Zusammenfassung")
    return AGGREGATE[agg].format(s=f'cast("{spalte}" as real)') if agg != "anzahl" else AGGREGATE[agg]


def _filter(spalten: list[str], filter_spalte: str, filter_wert: str) -> tuple[str, tuple]:
    if not filter_spalte:
        return "", ()
    _spalte_pruefen(spalten, filter_spalte, "Filter")
    return f' where cast("{filter_spalte}" as text) = ?', (filter_wert,)


@app.get("/api/werte")
def werte(datei: str, tabelle: str, spalte: str):
    """Verschiedene Werte einer Spalte — für die Filterauswahl."""
    c = org_db(datei)
    _tabelle_pruefen(c, tabelle)
    _spalte_pruefen(_spalten_von(c, tabelle), spalte, "Werte")
    z = _mit_zeitlimit(c, f'select "{spalte}", count(*) from "{tabelle}" group by 1 order by 1 desc limit 300', ())
    return [{"wert": r[0], "anzahl": r[1]} for r in z]


@app.get("/api/diagramm")
def diagramm(datei: str, tabelle: str, x: str, y: str = "", agg: str = "anzahl",
             filter_spalte: str = "", filter_wert: str = ""):
    """Eine Spalte gruppiert, eine zweite zusammengefasst — die Grundlage für Balken und Linien."""
    c = org_db(datei)
    _tabelle_pruefen(c, tabelle)
    spalten = _spalten_von(c, tabelle)
    _spalte_pruefen(spalten, x, "Achse")
    if agg != "anzahl":
        _spalte_pruefen(spalten, y, "Wert")
    wo, par = _filter(spalten, filter_spalte, filter_wert)
    sql = f'select "{x}" as x, {_ausdruck(agg, y)} as y from "{tabelle}"{wo} group by "{x}" order by "{x}" limit 400'
    zeilen = _mit_zeitlimit(c, sql, par)
    gruppen = _mit_zeitlimit(c, f'select count(distinct "{x}") from "{tabelle}"{wo}', par)[0][0]
    return {"x": x, "y": y if agg != "anzahl" else "", "agg": agg, "agg_name": AGG_NAME[agg],
            "filter": {"spalte": filter_spalte, "wert": filter_wert} if filter_spalte else None,
            "punkte": [[r[0], r[1]] for r in zeilen], "gruppen": gruppen, "gekuerzt": gruppen > len(zeilen),
            "sql": sql.replace("?", repr(filter_wert)) if par else sql, "herkunft": _herkunft(c, tabelle)}


_VZ = None


def _verzeichnis():
    global _VZ
    if _VZ is None:
        from .graph import Verzeichnis
        _VZ = Verzeichnis(k.GEMEINDEVERZEICHNIS)
        _VZ.name_von = {int(g["BfsCode"]): g["Name"] for g in _VZ.gemeinden}
    return _VZ


def _bfs_spalte(c: sqlite3.Connection, tabelle: str) -> str | None:
    """Die Spalte mit gültigen BFS-Gemeindenummern — gleiche Regel wie beim Graphenbau."""
    from .graph import BFS_SPALTE
    vz = _verzeichnis()
    for s in _spalten_von(c, tabelle):
        n = s.lower()
        if not BFS_SPALTE.search(n) or re.search(r"kreis|quartier|bezirk|zone", n):
            continue
        w = [r[0] for r in c.execute(f'select distinct "{s}" from "{tabelle}" where "{s}" is not null limit 500')]
        zahlen = [int(str(v).strip()) for v in w if str(v).strip().isdigit()]
        if w and sum(1 for z in zahlen if z in vz.bfs_nummern) / len(w) >= 0.8:
            return s
    return None


@app.get("/api/vergleichbar")
def vergleichbar():
    """Tabellen, die eine Spalte mit BFS-Gemeindenummern haben (gemessen beim Graphenbau)."""
    c = graph()
    aus = []
    for z in c.execute(
            "select d.id, d.label, json_extract(d.extra, '$.organisation') as organisation, "
            "json_extract(d.extra, '$.datei') as datei, e.beleg from kante e join knoten d on d.id = e.von "
            "where e.nach = 'schluessel/gemeinde' order by organisation, d.label"):
        aus.append(dict(z))
    return aus


@app.get("/api/schluesselspalte")
def schluesselspalte(datei: str, tabelle: str):
    c = org_db(datei)
    _tabelle_pruefen(c, tabelle)
    return {"spalte": _bfs_spalte(c, tabelle)}


def _je_gemeinde(datei, tabelle, wert, agg, filter_spalte, filter_wert) -> dict:
    c = org_db(datei)
    _tabelle_pruefen(c, tabelle)
    spalten = _spalten_von(c, tabelle)
    bfs = _bfs_spalte(c, tabelle)
    if not bfs:
        raise HTTPException(400, f"Keine Spalte mit BFS-Gemeindenummern in {tabelle}")
    if agg != "anzahl":
        _spalte_pruefen(spalten, wert, "Wert")
    wo, par = _filter(spalten, filter_spalte, filter_wert)
    sql = f'select cast("{bfs}" as integer) as bfs, {_ausdruck(agg, wert)} as wert from "{tabelle}"{wo} group by 1'
    werte = {r[0]: r[1] for r in _mit_zeitlimit(c, sql, par) if r[0] is not None}
    return {"werte": werte, "bfs_spalte": bfs, "sql": sql.replace("?", repr(filter_wert)) if par else sql,
            "wert": wert if agg != "anzahl" else "", "agg": agg, "agg_name": AGG_NAME[agg],
            "filter": {"spalte": filter_spalte, "wert": filter_wert} if filter_spalte else None,
            "herkunft": _herkunft(c, tabelle)}


@app.get("/api/je_gemeinde")
def je_gemeinde(datei: str, tabelle: str, wert: str = "", agg: str = "anzahl", filter_spalte: str = "", filter_wert: str = ""):
    """Ein Wert je Gemeinde — fuer die Karte."""
    d = _je_gemeinde(datei, tabelle, wert, agg, filter_spalte, filter_wert)
    vz = _verzeichnis()
    d["punkte"] = [{"bfs": n, "gemeinde": vz.name_von[n], "wert": w} for n, w in sorted(d.pop("werte").items())
                   if n in vz.bfs_nummern and w is not None]
    return d


@app.get("/api/vergleich")
def vergleich(a_datei: str, a_tabelle: str, b_datei: str, b_tabelle: str,
              a_wert: str = "", a_agg: str = "anzahl", a_filter_spalte: str = "", a_filter_wert: str = "",
              b_wert: str = "", b_agg: str = "anzahl", b_filter_spalte: str = "", b_filter_wert: str = ""):
    """Zwei Tabellen über die BFS-Gemeindenummer nebeneinander — nur Gemeinden, die in beiden vorkommen."""
    a = _je_gemeinde(a_datei, a_tabelle, a_wert, a_agg, a_filter_spalte, a_filter_wert)
    b = _je_gemeinde(b_datei, b_tabelle, b_wert, b_agg, b_filter_spalte, b_filter_wert)
    vz = _verzeichnis()
    gemeinsam = sorted(set(a["werte"]) & set(b["werte"]) & vz.bfs_nummern)
    punkte = [{"bfs": n, "gemeinde": vz.name_von.get(n, str(n)), "a": a["werte"][n], "b": b["werte"][n]}
              for n in gemeinsam if a["werte"][n] is not None and b["werte"][n] is not None]
    for s in (a, b):
        s["gemeinden"] = len(s.pop("werte"))
    return {"a": a, "b": b, "punkte": punkte}


@app.get("/api/entdeckungen")
def entdeckungen():
    return FileResponse(_vorberechnet("entdeckungen.json"), media_type="application/json", headers=ZWISCHENSPEICHER)


@app.get("/api/organisationen")
def organisationen():
    c = graph()
    return [dict(z) for z in c.execute(
        "select o.id, o.label, count(e.von) as datensaetze from knoten o "
        "left join kante e on e.nach = o.id and e.art = 'publiziert_von' "
        "where o.typ = 'organisation' group by o.id order by datensaetze desc, o.label")]


# --- Tabellen --------------------------------------------------------------------


def _tabelle_pruefen(c: sqlite3.Connection, tabelle: str) -> None:
    if not c.execute("select 1 from daten_tabelle where tabelle = ?", (tabelle,)).fetchone():
        raise HTTPException(404, "Tabelle nicht gefunden")


@app.get("/api/tabelle")
def tabelle(datei: str, tabelle: str, anzahl: int = 25):
    c = org_db(datei)
    _tabelle_pruefen(c, tabelle)
    cur = c.execute(f'select * from "{tabelle}" limit ?', (min(anzahl, 200),))
    spalten = [d[0] for d in cur.description]
    zeilen = [list(r) for r in cur.fetchall()]
    herkunft = c.execute(
        "select s.titel_de, s.url, d.titel_de as datensatz, d.organisation, d.lizenz, d.opendata_url "
        "from daten_tabelle t join dim_datensammlung s on s.id = t.datensammlung_id "
        "join dim_datensatz d on d.id = t.datensatz_id where t.tabelle = ?", (tabelle,)).fetchone()
    profil = [dict(p) for p in c.execute(
        "select spalte, typ, anzahl_verschieden, anteil_null, min_wert, max_wert, vollstaendig "
        "from daten_profil where tabelle = ? order by rowid",
        (tabelle,))] if c.execute("select 1 from sqlite_master where name = 'daten_profil'").fetchone() else []
    return {"spalten": spalten, "zeilen": zeilen, "herkunft": dict(herkunft) if herkunft else None, "profil": profil}


class TabellenFrage(BaseModel):
    datei: str
    tabelle: str
    frage: str


VERBOTEN = re.compile(r"\b(attach|detach|pragma|insert|update|delete|drop|create|alter|replace|vacuum|reindex|analyze)\b", re.I)


def _sql_pruefen(sql: str) -> str:
    """Der Guard: eine einzige lesende Anweisung."""
    s = sql.strip().rstrip(";").strip()
    if ";" in s:
        raise ValueError("mehr als eine Anweisung")
    if not re.match(r"^(select|with)\b", s, re.I):
        raise ValueError("nur SELECT ist erlaubt")
    if VERBOTEN.search(s):
        raise ValueError("unzulaessiges Schluesselwort")
    return s


def _ausfuehren(c: sqlite3.Connection, tabelle: str, sql: str) -> tuple[list, list]:
    erlaubt = {tabelle}

    def wache(aktion, a1, a2, db, ausloeser):
        if aktion == sqlite3.SQLITE_READ and a1 not in erlaubt:
            return sqlite3.SQLITE_DENY
        if aktion in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    beginn = time.time()
    c.set_authorizer(wache)
    c.set_progress_handler(lambda: 1 if time.time() - beginn > 15 else 0, 10000)
    try:
        cur = c.execute(f"select * from ({sql}) limit 500")
        return [d[0] for d in cur.description], [list(r) for r in cur.fetchall()]
    finally:
        c.set_authorizer(None)
        c.set_progress_handler(None, 0)


@app.post("/api/frage_tabelle")
def frage_tabelle(f: TabellenFrage, request: Request):
    _begrenzen(request)
    c = org_db(f.datei)
    _tabelle_pruefen(c, f.tabelle)
    spalten = c.execute("select name, name_original, typ from daten_spalte where tabelle = ? order by position", (f.tabelle,)).fetchall()
    beispiel = c.execute(f'select * from "{f.tabelle}" limit 3').fetchall()
    titel = c.execute("select d.titel_de from daten_tabelle t join dim_datensatz d on d.id = t.datensatz_id where t.tabelle = ?", (f.tabelle,)).fetchone()[0]
    system = (
        # Prompts mit echten Umlauten: Das Modell uebernimmt den Stil, sonst
        # schreibt es «Datensaetze» (beobachtet am 17.11.2026).
        "Du schreibst genau eine SQLite-Abfrage (nur SELECT) über genau eine Tabelle. "
        "Antworte nur mit JSON: {\"sql\": \"...\", \"erklaerung\": \"ein Satz auf Deutsch (Schweizer Rechtschreibung, "
        "ss statt ß), was die Abfrage tut\"}. "
        "Spaltennamen immer in doppelten Anführungszeichen. Keine Zahlen erfinden; die Werte kommen aus der Abfrage. "
        "Die erste Spalte datensammlung_id nicht ausgeben, ausser die Frage verlangt es. Höchstens 200 Zeilen."
    )
    nutzer = (
        f'Tabelle: "{f.tabelle}" (Datensatz: {titel})\n'
        f"Spalten: " + ", ".join(f'"{s["name"]}" ({s["typ"]}, Quelle: {s["name_original"]})' for s in spalten) + "\n"
        f"Beispielzeilen: {json.dumps([list(b) for b in beispiel], ensure_ascii=False, default=str)[:1500]}\n"
        f"Frage: {f.frage}"
    )
    try:
        text, verbrauch = ki.chat(system, nutzer, max_tokens=500)
        antwort = ki.json_aus(text)
        sql = _sql_pruefen(antwort["sql"])
        spalten_aus, zeilen = _ausfuehren(c, f.tabelle, sql)
    except (ki.KiFehler, ValueError, KeyError, sqlite3.Error) as fehler:
        return JSONResponse({"fehler": str(fehler)}, status_code=422)
    herkunft = c.execute(
        "select s.titel_de, s.url, d.titel_de as datensatz, d.organisation, d.lizenz, d.opendata_url "
        "from daten_tabelle t join dim_datensammlung s on s.id = t.datensammlung_id "
        "join dim_datensatz d on d.id = t.datensatz_id where t.tabelle = ?", (f.tabelle,)).fetchone()
    return {"sql": sql, "erklaerung": antwort.get("erklaerung", ""), "spalten": spalten_aus, "zeilen": zeilen,
            "herkunft": dict(herkunft), "modell": k.LLM_MODELL, "verbrauch": verbrauch}


# --- Frage an den Graphen --------------------------------------------------------


class GraphFrage(BaseModel):
    frage: str


@app.post("/api/frage")
def frage(f: GraphFrage, request: Request):
    """Die KI waehlt Suchbegriffe; der Graph liefert, was dazu verknuepft ist;
    die KI erzaehlt nur ueber das, was der Graph geliefert hat — ohne Zahlen."""
    _begrenzen(request)
    c = graph()
    try:
        text, _ = ki.chat(
            "Du hilfst, in einem Katalog offener Schweizer Behördendaten zu suchen. "
            "Antworte nur mit JSON: {\"begriffe\": [3 bis 8 deutsche Suchbegriffe in der Grundform, "
            "auch Ober- und Nachbarbegriffe], \"orte\": [genannte Orte]}.",
            f.frage, max_tokens=200)
        wahl = ki.json_aus(text)
    except (ki.KiFehler, ValueError) as fehler:
        return JSONResponse({"fehler": f"Die KI hat nicht geantwortet: {fehler}"}, status_code=502)

    begriffe = [b for b in wahl.get("begriffe", []) if isinstance(b, str)][:8]
    orte = [o for o in wahl.get("orte", []) if isinstance(o, str)][:4]
    treffer: dict[str, dict] = {}
    for wort in begriffe + orte:
        for z in suche(wort, anzahl=6):
            if z["typ"] in ("begriff", "ort", "datensatz"):
                treffer.setdefault(z["id"], {**z, "suchwort": wort})
    datensaetze: dict[str, dict] = {}
    for t in treffer.values():
        if t["typ"] == "datensatz":
            datensaetze.setdefault(t["id"], {"id": t["id"], "label": t["label"], "ueber": []})["ueber"].append(t["label"])
            continue
        for e in c.execute(
            "select d.id, d.label, d.extra from kante e join knoten d on d.id = e.von "
            "where e.nach = ? and d.typ = 'datensatz' limit 30", (t["id"],)):
            ds = datensaetze.setdefault(e["id"], {"id": e["id"], "label": e["label"], "ueber": []})
            ds["ueber"].append(t["label"])
            ds["organisation"] = json.loads(e["extra"]).get("organisation")
    for ds_id, ds in datensaetze.items():
        if "organisation" not in ds:
            z = c.execute("select extra from knoten where id = ?", (ds_id,)).fetchone()
            ds["organisation"] = json.loads(z["extra"]).get("organisation") if z and z["extra"] else None
    rangliste = sorted(datensaetze.values(), key=lambda d: -len(set(d["ueber"])))[:15]

    erzaehlung = ""
    if rangliste:
        liste = "\n".join(f"- {d['label']} ({d['organisation']}) — verbunden über: {', '.join(sorted(set(d['ueber'])))}" for d in rangliste)
        try:
            erzaehlung, _ = ki.chat(
                "Du erklärst in 3 bis 5 Sätzen auf Deutsch (Schweizer Rechtschreibung, ss statt ß), welche "
                "Datensätze zur Frage passen und welche überraschenden Verbindungen zwischen Anbietern bestehen. "
                "Nenne nur Datensätze aus der Liste. Nenne keine Zahlenwerte — du kennst die Daten nicht, nur ihre "
                "Beschreibung. Keine Aufzählungszeichen, Fliesstext.",
                f"Frage: {f.frage}\n\nGefundene Datensätze:\n{liste}", max_tokens=400, temperatur=0.2)
        except ki.KiFehler:
            erzaehlung = ""
    return {"begriffe": begriffe, "orte": orte, "treffer": list(treffer.values()), "datensaetze": rangliste,
            "erzaehlung": erzaehlung.strip(), "modell": k.LLM_MODELL}


# --- URIs: HTML oder RDF je nach Anfrage -----------------------------------------


@app.get("/id/{pfad:path}")
def aufloesen(pfad: str, request: Request, format: str | None = None):
    c = graph()
    ziel = _alias(c, pfad)
    if ziel != pfad:
        return RedirectResponse(f"/id/{ziel}" + (f"?format={format}" if format else ""), status_code=301)
    n = c.execute("select * from knoten where id = ?", (pfad,)).fetchone()
    if not n:
        raise HTTPException(404, "Diese URI ist nicht vergeben.")
    katalog = None
    if n["typ"] == "datensatz":
        x = _extra(n)
        katalog = _katalog(x["datei"], x["datensatz_id"])
    annahme = request.headers.get("accept", "")
    if format == "ttl" or "text/turtle" in annahme:
        return PlainTextResponse(rdf.turtle(c, pfad, katalog), media_type="text/turtle; charset=utf-8")
    if format == "jsonld" or "application/ld+json" in annahme:
        return JSONResponse(rdf.jsonld(c, pfad, katalog), media_type="application/ld+json")
    return RedirectResponse(f"/#/knoten/{pfad}", status_code=303)


# --- Weboberflaeche --------------------------------------------------------------


@app.get("/")
def startseite():
    return FileResponse(k.WEB / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=k.WEB), name="web")
