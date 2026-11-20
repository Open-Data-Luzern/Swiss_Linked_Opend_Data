# Portal «Swiss Open Linked Data» (Prototyp)

Ein Portal über die 85 SQLite-Datenbanken des Projekts: Es verknüpft Datensätze
verschiedener Anbieter über gemeinsame Orte, Kennzahlen, Objekte und Begriffe,
zeigt die Verbindungen als Graph und beantwortet Fragen mit Minimind (Gemma).

Die 85 Datenbanken bleiben unberührt und werden nur gelesen. Das Portal baut
daneben eine eigene Datei, `Swiss_Open_Linked_Data/verknuepfung.sqlite` — den
Graphen. Er lässt sich jederzeit neu bauen.

## Starten (lokal)

```bash
cd D:\Swiss_Open_Linked_Data\portal
..\.venv\Scripts\python.exe -m uvicorn swiss_portal.app:app --port 8040
```

Dann <http://127.0.0.1:8040>. Ist in `.env` ein Login gesetzt
(`PORTAL_BENUTZER`, `PORTAL_PASSWORT`), fragt der Browser danach.

## Die drei Schritte

| Schritt | Befehl | Was er tut | Dauer |
|---|---|---|---|
| 1. Auswahl | `python -m swiss_portal.auswahl --anzahl 200` | wählt Datensätze, schreibt `daten/auswahl.jsonl` | 1 min |
| 2. Extraktion | (Probelauf: Claude; Server: Gemma, noch zu bauen) | schreibt `daten/extraktion/<urheber>_teil_NN.jsonl` nach `daten/extraktion/SCHEMA.md` | — |
| 3. Graph | `python -m swiss_portal.graph` | baut `verknuepfung.sqlite` aus Katalog, Daten, Extraktion und Einbettungen | 1 min (mit Zwischenspeicher), sonst ~7 min je 700 Begriffe |

Der Graph prüft jeden Beleg der Extraktion wörtlich gegen den Quelltext und
gleicht Orte exakt gegen das amtliche Gemeindeverzeichnis ab
(`daten/gemeindeverzeichnis_2026-01-01.csv`).

## Konfiguration (`.env`)

| Variable | Wozu |
|---|---|
| `SIM_AI_KEY` | Schlüssel für LiteLLM auf Minimind (Gemma) |
| `SPARK5_CLIENT_ID`, `SPARK5_CLIENT_SECRET` | Cloudflare-Access für die Einbettung auf spark5 |
| `PORTAL_BENUTZER`, `PORTAL_PASSWORT` | gemeinsamer Login; beide leer = offen (nur lokal!) |
| `SWISS_OGD_DATEN` | Verzeichnis der 85 Datenbanken, falls nicht am Standardort |
| `SWISS_OGD_GRAPH` | Pfad des Graphen, falls nicht am Standardort |
| `KI_ANFRAGEN_PRO_STUNDE` | Begrenzung je Adresse, Standard 60 |

`.env` nie weitergeben; sie enthält Schlüssel.

## Verzeichnisse

```
swiss_portal/   konfiguration, ki (Gemma, Einbettung), auswahl, graph, rdf, app (FastAPI)
web/            index.html, app.js, stil.css, markdown.js, kreuz.svg, lib/d3, inhalt/theorie.md
daten/          Gemeindeverzeichnis, Auswahl, Extraktion, Einbettungs-Zwischenspeicher
```

## Abhängigkeiten

Der Kern läuft auf der Standardbibliothek. Für die Web-API: `fastapi`, `uvicorn`.
D3 7.9.0 liegt als Datei in `web/lib/` — kein Build-Schritt, kein Node.

## URIs

Jeder Knoten hat eine URI unter `https://linkeddata.sim-research.ch/id/…`.
`/id/<pfad>` liefert je nach `Accept`-Kopf Turtle, JSON-LD oder leitet auf die
HTML-Seite weiter; `?format=ttl` bzw. `?format=jsonld` erzwingt das Format.
Die URIs sind **nicht persistent** — es ist ein Prototyp.

## Werkzeuge

| Befehl | Zweck |
|---|---|
| `python -m swiss_portal.auswahl --alle` | alle 15'934 Datensätze; schreibt Pakete `eingabe_voll_NNNN.jsonl` für die noch nicht extrahierten |
| `python -m swiss_portal.pruefen --alle` | prüft jede Extraktion gegen ihre Eingabe: JSON, Vollständigkeit, wörtliche Belege (Exit 0 = ok) |
| `python -m swiss_portal.extraktion --eingabe …` | Extraktion mit Gemma (Vergleich; für den Vollausbau zu langsam: ~4.8 s je Datensatz) |
| `python -m swiss_portal.graph [--urheber claude\|gemma]` | Graph bauen; tauscht die Datei erst am Ende aus |
| `python tests/rauchtest.py [--ki]` | prüft ein laufendes Portal (`PORTAL_URL`, Login aus Umgebung oder `.env`) |
| `pytest tests` | Tests des SQL-Guards |

## Server

`deploy/` enthält Dockerfile, `compose.yaml` (portal, caddy, werkzeug) und das
Caddyfile — HTTPS mit Let's Encrypt, **kein Cloudflare**. Lokal getestet am
17.11.2026: Abbild gebaut, Graph im Werkzeug-Container gebaut, Rauchtest gegen den
Container grün, Caddyfile gültig.

`anleitungen/` enthält die drei Aufträge für den Umzug:

1. `1_claude_browser_hostpoint.md` — DNS-Eintrag `linkeddata` bei Hostpoint
2. `2_claude_browser_firewall.md` — Ports 80 und 443 zum Server
3. `3_claude_code_server.md` — Datentransfer, Bau, Metadaten-Extraktion durch Claude Code, Vollausbau
