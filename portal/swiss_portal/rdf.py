"""Projektion des Graphen nach RDF (Turtle und JSON-LD).

Der Graph in SQLite ist die Quelle; RDF ist, wie er sich nach aussen zeigt.
Was die Projektion verliert, steht im Theorieteil (Kap. 5).

Abgeleitete und gemessene Kanten werden zusaetzlich als rdf:Statement
ausgegeben, damit Urheber und Beleg an der einzelnen Aussage haengen —
PROV-O fuer die Urheberschaft, sold: fuer Klasse und Beleg.
"""

from __future__ import annotations

import json
import sqlite3

from . import konfiguration as k

PRAEFIXE = {
    "dcat": "http://www.w3.org/ns/dcat#",
    "dct": "http://purl.org/dc/terms/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "prov": "http://www.w3.org/ns/prov#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "sold": "https://linkeddata.sim-research.ch/def/",
}

PRAEDIKAT = {
    "publiziert_von": "dct:publisher",
    "thema": "dcat:theme",
    "ort": "dct:spatial",
    "objekt": "sold:beobachtetObjekt",
    "kennzahl": "sold:misst",
    "konzept": "dct:subject",
    "raumebene": "sold:raumebene",
    "liegt_in": "sold:liegtIn",
    "aehnlich": "skos:related",
    "enthaelt_schluessel": "sold:enthaeltSchluessel",
}

KLASSE = {
    "datensatz": "dcat:Dataset",
    "organisation": "foaf:Organization",
    "thema": "skos:Concept",
    "begriff": "skos:Concept",
    "ort": "dct:Location",
    "raumebene": "skos:Concept",
    "schluessel": "sold:Schluessel",
}

URHEBER = {
    "katalog": "Katalog opendata.swiss",
    "gemeindeverzeichnis": "Amtliches Gemeindeverzeichnis BFS, Stand 1.1.2026",
    "regel": "Regel im Portalcode (Spaltenwerte gegen Verzeichnis)",
    "claude": "Sprachmodell Claude (Anthropic), Probelauf 17.11.2026",
    "gemma": "Sprachmodell Gemma 4 31B (Minimind)",
    "qwen3-embedding": "Einbettungsmodell qwen3-embedding 8B (Minimind)",
}


def uri(knoten_id: str) -> str:
    return f"<{k.URI_BASIS}{knoten_id}>"


def _lit(text: str, sprache: str | None = "de") -> str:
    t = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
    return f'"{t}"@{sprache}' if sprache else f'"{t}"'


def turtle(c: sqlite3.Connection, knoten_id: str, katalog: dict | None = None) -> str:
    n = c.execute("select id, typ, label, extra from knoten where id = ?", (knoten_id,)).fetchone()
    if not n:
        raise KeyError(knoten_id)
    extra = json.loads(n[3]) if n[3] else {}
    z = [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE.items()]
    z.append("")
    s = uri(n[0])
    aussagen = [f"a {KLASSE.get(n[1], 'rdfs:Resource')}"]
    aussagen.append(("dct:title " if n[1] == "datensatz" else "skos:prefLabel " if n[1] in ("begriff", "thema", "raumebene") else "rdfs:label ") + _lit(n[2]))
    if extra.get("bfs"):
        aussagen.append(f'sold:bfsNummer "{extra["bfs"]}"^^xsd:integer')
    if katalog:
        if katalog.get("opendata_url"):
            aussagen.append(f"prov:wasDerivedFrom <{katalog['opendata_url']}>")
        if katalog.get("landingpage"):
            aussagen.append(f"dcat:landingPage <{katalog['landingpage']}>")
        if katalog.get("lizenz"):
            aussagen.append(f"dct:license {_lit(katalog['lizenz'], None)}")
    kanten = c.execute(
        "select von, nach, art, klasse, urheber, beleg, beleg_ok, gewicht from kante where von = ? or nach = ?",
        (knoten_id, knoten_id),
    ).fetchall()
    for von, nach, art, *_ in kanten:
        if von == knoten_id:
            aussagen.append(f"{PRAEDIKAT.get(art, 'sold:' + art)} {uri(nach)}")
    z.append(s + "\n    " + " ;\n    ".join(aussagen) + " .")

    eingehend = [kk for kk in kanten if kk[1] == knoten_id]
    for von, nach, art, *_ in eingehend:
        z.append(f"{uri(von)} {PRAEDIKAT.get(art, 'sold:' + art)} {s} .")

    for von, nach, art, klasse, urheber, beleg, beleg_ok, gewicht in kanten:
        if klasse == "belegt":
            continue
        teile = [
            "a rdf:Statement",
            f"rdf:subject {uri(von)}",
            f"rdf:predicate {PRAEDIKAT.get(art, 'sold:' + art)}",
            f"rdf:object {uri(nach)}",
            f"sold:kantenklasse {_lit(klasse, None)}",
            f"prov:wasAttributedTo [ rdfs:label {_lit(URHEBER.get(urheber, urheber))} ]",
        ]
        if beleg:
            teile.append(f"sold:beleg {_lit(beleg, None)}")
        if beleg_ok is not None:
            teile.append(f'sold:belegGeprueft "{bool(beleg_ok)}"^^xsd:boolean'.replace('"True"', '"true"').replace('"False"', '"false"'))
        if gewicht is not None:
            teile.append(f'sold:gewicht "{gewicht}"^^xsd:decimal')
        z.append("[] " + " ;\n   ".join(teile) + " .")
    return "\n".join(z) + "\n"


def jsonld(c: sqlite3.Connection, knoten_id: str, katalog: dict | None = None) -> dict:
    n = c.execute("select id, typ, label from knoten where id = ?", (knoten_id,)).fetchone()
    if not n:
        raise KeyError(knoten_id)
    dok: dict = {
        "@context": {**PRAEFIXE},
        "@id": f"{k.URI_BASIS}{n[0]}",
        "@type": KLASSE.get(n[1], "rdfs:Resource"),
        "rdfs:label": {"@value": n[2], "@language": "de"},
    }
    if katalog and katalog.get("opendata_url"):
        dok["prov:wasDerivedFrom"] = {"@id": katalog["opendata_url"]}
    for nach, art, klasse, urheber, beleg in c.execute(
        "select nach, art, klasse, urheber, beleg from kante where von = ?", (knoten_id,)
    ):
        dok.setdefault(PRAEDIKAT.get(art, "sold:" + art), []).append(
            {"@id": f"{k.URI_BASIS}{nach}", "sold:kantenklasse": klasse,
             "prov:wasAttributedTo": URHEBER.get(urheber, urheber), **({"sold:beleg": beleg} if beleg else {})}
        )
    return dok
