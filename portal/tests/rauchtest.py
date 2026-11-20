"""Rauchtest gegen ein laufendes Portal — lokal, im Container oder auf dem Server.

    PORTAL_URL=https://linkeddata.sim-research.ch PORTAL_BENUTZER=... PORTAL_PASSWORT=...         python tests/rauchtest.py --ki

Ohne Umgebungsvariablen: http://127.0.0.1:8040 und Login aus portal/.env.
--ki prueft zusaetzlich die beiden Funktionen, die Minimind (Gemma) aufrufen.
Die Beispielknoten stammen aus dem Probelauf (200 Datensaetze) und bleiben im
Vollausbau erhalten. Exit 0 = alles gruen.
"""
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import os
from pathlib import Path


def _env(name):
    if os.environ.get(name):
        return os.environ[name]
    datei = Path(__file__).resolve().parent.parent / ".env"
    if datei.exists():
        for z in datei.read_text(encoding="utf-8").split(chr(10)):
            if z.startswith(name + "="):
                return z.split("=", 1)[1].strip()
    return ""


BASIS = os.environ.get("PORTAL_URL", "http://127.0.0.1:8040").rstrip("/")
AUTH = "Basic " + base64.b64encode(f"{_env('PORTAL_BENUTZER')}:{_env('PORTAL_PASSWORT')}".encode()).decode()
fehler = 0


def hole(pfad, daten=None, auth=True, accept=None):
    kopf = {"Content-Type": "application/json"}
    if auth:
        kopf["Authorization"] = AUTH
    if accept:
        kopf["Accept"] = accept
    req = urllib.request.Request(BASIS + pfad, data=json.dumps(daten).encode() if daten else None, headers=kopf)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read().decode("utf-8"), time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t


def pruefe(name, bedingung, info=""):
    global fehler
    print(("OK   " if bedingung else "FEHL ") + name + (f"  — {info}" if info else ""))
    if not bedingung:
        fehler += 1


s, _, _ = hole("/api/uebersicht", auth=False)
pruefe("ohne Login 401", s == 401, str(s))
s, t, _ = hole("/", auth=True)
pruefe("Startseite", s == 200 and "Swiss Open Linked Data" in t)
s, t, _ = hole("/api/uebersicht")
u = json.loads(t)
pruefe("Uebersicht", s == 200 and u["graph"]["knoten"].get("datensatz") == u["bestand"]["datensaetze"], json.dumps(u["bestand"]))
s, t, _ = hole("/api/suche?q=" + urllib.parse.quote("Luftqualität"))
pruefe("Suche Luftqualitaet", s == 200 and len(json.loads(t)) > 0, str([x["label"] for x in json.loads(t)[:4]]))
for kid in ["begriff/wohnung", "ort/gemeinde/230", "begriff/erneuerbare-energie", "schluessel/gemeinde"]:
    s, t, _ = hole("/api/knoten?id=" + urllib.parse.quote(kid))
    pruefe(f"Knoten {kid}", s == 200, f"{len(json.loads(t).get('kanten', []))} Kanten" if s == 200 else t[:100])
s, t, _ = hole("/api/pfad?von=begriff/wildtier&nach=begriff/abstimmung")
d = json.loads(t)
pruefe("Pfad Wildtier->Abstimmung", s == 200 and d.get("gefunden"), " -> ".join(k["label"] for k in d.get("knoten", [])))
s, t, _ = hole("/api/graph?id=begriff/erneuerbare-energie&tiefe=2")
d = json.loads(t)
pruefe("Graph", s == 200 and len(d["knoten"]) > 3, f"{len(d['knoten'])} Knoten {len(d['kanten'])} Kanten")
s, t, _ = hole("/api/entdeckungen")
d = json.loads(t)
pruefe("Entdeckungen", s == 200 and d["gemeinsame_begriffe"], f"{len(d['gemeinsame_begriffe'])} Begriffe / {len(d['bruecken'])} Brücken / {len(d['schluessel'])} Schlüssel / {len(d['wege'])} Wege")
# Abnahmekriterien Cockpit-Brief 18.11.2026
s, t, _ = hole("/api/cockpit")
pruefe("Cockpit", s == 200 and json.loads(t).get("klassen"), f"{len(t)} Bytes")
s, t, _ = hole("/api/suche?q=Schaf&anzahl=5")
pruefe("Suche Schaf: Begriff zuerst", s == 200 and json.loads(t)[0]["id"] == "begriff/schaf", str([x["label"] for x in json.loads(t)[:3]]))
s, t, _ = hole("/api/suche?q=Bier&anzahl=5")
pruefe("Suche Bier: mindestens ein Treffer", s == 200 and len(json.loads(t)) >= 1, str([x["label"][:40] for x in json.loads(t)[:2]]))
gesehen, laengen = [], []
for _ in range(10):
    s, t, _ = hole("/api/zufallsweg?ohne=" + ",".join(map(str, gesehen)))
    w = json.loads(t)
    gesehen.append(w["nr"])
    laengen.append(len(w["knoten"]))
pruefe("Zufallsweg 10x verschieden, 4-6 Stationen", len(set(gesehen)) == 10 and all(4 <= n <= 6 for n in laengen), str(laengen))
s, t, _ = hole("/api/pfad?von=begriff/hund&nach=begriff/steuer&k=3&hubs=aus")
d = json.loads(t)
pruefe("Pfad Hund->Steuer, 3 Wege ohne Hubs", s == 200 and d.get("gefunden"), f"{len(d.get('wege', []))} Wege: " + " | ".join(" -> ".join(k["label"][:20] for k in w["knoten"]) for w in d.get("wege", [])))
s, t, _ = hole("/id/begriff/wohnung?format=ttl")
pruefe("Turtle", s == 200 and "skos:Concept" in t and "@prefix" in t, t.splitlines()[12] if s == 200 else t[:80])
s, t, _ = hole("/id/begriff/wohnung", accept="application/ld+json")
pruefe("JSON-LD per Accept", s == 200 and json.loads(t).get("@id", "").endswith("begriff/wohnung"))
s, t, _ = hole("/api/knoten?id=" + urllib.parse.quote("datensatz/kanton-zug-wohnungen-nach-zimmerzahl"))
d = json.loads(t)
pruefe("Datensatz mit Katalog", s == 200 and d.get("katalog", {}).get("tabellen"), f"{len(d['katalog']['tabellen'])} Tabellen")
tab = d["katalog"]["tabellen"][0]
s, t, _ = hole(f"/api/tabelle?datei=kanton-zug&tabelle={tab['tabelle']}&anzahl=5")
pruefe("Tabellenvorschau", s == 200 and json.loads(t)["zeilen"], str(json.loads(t)["spalten"][:6]))
if "--ki" in sys.argv:
    s, t, dauer = hole("/api/frage_tabelle", {"datei": "kanton-zug", "tabelle": tab["tabelle"], "frage": "Welche Gemeinde hat im neusten Jahr am meisten Wohnungen?"})
    d = json.loads(t)
    pruefe("Frage an Tabelle (Gemma)", s == 200 and d.get("zeilen"), f"{dauer:.1f}s  {d.get('sql', d)}  -> {d.get('zeilen', [])[:3]}")
    s, t, dauer = hole("/api/frage", {"frage": "Wo wird die Luftqualität gemessen?"})
    d = json.loads(t)
    pruefe("Frage an Graph (Gemma)", s == 200 and d.get("datensaetze"), f"{dauer:.1f}s  Begriffe {d.get('begriffe')}  {len(d.get('datensaetze', []))} Datensaetze")
    print("   Erzaehlung:", (d.get("erzaehlung") or "")[:600])
print(f"\n{fehler} Fehler")
sys.exit(1 if fehler else 0)
