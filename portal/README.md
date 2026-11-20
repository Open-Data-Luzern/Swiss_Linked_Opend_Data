# Portal «Swiss Open Linked Data» (Prototyp)

Ein Portal über die 85 SQLite-Datenbanken des Projekts: Es verknüpft Datensätze
verschiedener Anbieter über gemeinsame Orte, Kennzahlen, Objekte und Begriffe,
zeigt die Verbindungen als Cockpit, Karte und Graph und beantwortet Fragen mit
Minimind (Gemma).

Die 85 Datenbanken bleiben unberührt und werden nur gelesen. Das Portal baut
daneben eine eigene Datei, `graph/verknuepfung.sqlite` — den Graphen. Er lässt
sich jederzeit neu bauen.

Stand 18.11.2026: 15'934 Datensätze extrahiert, Graph mit 25'553 Knoten und
139'044 Kanten.

## Starten auf dem Server (Docker)

Alle Befehle aus `/srv/swiss_ogd/portal`. Die Abkürzung spart Tipparbeit:

```bash
alias dc='docker compose --env-file .env -f deploy/compose.yaml -f deploy/compose.hinter-caddy.yaml'
dc build portal && dc up -d portal                         # Portal neu bauen und starten
dc run --rm werkzeug python -m swiss_portal.graph          # Graph neu bauen (~80 s)
dc run --rm werkzeug python -m swiss_portal.vorberechnen   # nur die Cockpit-Dateien (~40 s)
```

Zwei Betriebsarten:

- **Mit eigenem Caddy** (`deploy/compose.yaml` allein, `up -d portal caddy`):
  Caddy holt das Let's-Encrypt-Zertifikat und braucht die Ports 80 und 443.
- **Hinter einem bestehenden Caddy** (zusätzlich `deploy/compose.hinter-caddy.yaml`,
  so läuft es heute): Das Portal öffnet nur `172.17.0.1:8040`; der vorhandene
  Caddy des Servers leitet die Domain dorthin.

Ist in `.env` ein Login gesetzt (`PORTAL_BENUTZER`, `PORTAL_PASSWORT`), fragt
der Browser danach.

Lokal ohne Docker geht auch:
`python -m uvicorn swiss_portal.app:app --port 8040`, dann <http://127.0.0.1:8040>.

## Die drei Schritte zum Graphen

| Schritt | Befehl | Was er tut |
|---|---|---|
| 1. Auswahl | `python -m swiss_portal.auswahl --alle` | wählt Datensätze, schreibt `daten/auswahl.jsonl` und Eingabepakete |
| 2. Extraktion | Claude Code bzw. `python -m swiss_portal.extraktion` (Gemma) | schreibt `daten/extraktion/<urheber>_teil_NN.jsonl` nach `daten/extraktion/SCHEMA.md` |
| 3. Graph | `python -m swiss_portal.graph` | baut `verknuepfung.sqlite` aus Katalog, Daten, Extraktion und Einbettungen, danach die Cockpit-Dateien |

Der Graph prüft jeden Beleg der Extraktion wörtlich gegen den Quelltext, gleicht
Orte exakt gegen das amtliche Gemeindeverzeichnis ab
(`daten/gemeindeverzeichnis_2026-01-01.csv`) und führt Synonyme
(Ähnlichkeit ≥ 0.99) zu einem Knoten zusammen; alte Adressen leiten weiter.

Jede Verbindung trägt eine von drei Klassen, überall in denselben Farben:
**belegt** (steht im Katalog oder Verzeichnis), **gemessen** (aus den Daten
geprüft), **abgeleitet** (KI aus dem Text, mit wörtlichem Beleg).

Nach dem Bau schreibt `vorberechnen.py` vier Dateien neben den Graphen:
`cockpit.json`, `karte.json`, `entdeckungen.json`, `zufallswege.json`. Dazu kommt
je Bau eine Zeile in `laeufe.jsonl` (Verlauf für die Kacheln im Cockpit).

## Die Oberfläche

| Seite | Inhalt |
|---|---|
| Cockpit (`#/`) | Kennzahlen, Herkunft, Weg des Tages, häufigste Begriffe, Gemeindekarte |
| Entdecken | überraschende Wege, Heatmap Ebene × Kennzahl, Netz der Schlüsselspalten, Vergleich |
| Verbinden | kürzester Weg zwischen zwei Knoten, Alternativen, «Überrasch mich», Bild teilen |
| Fragen | Frage in Alltagssprache → Antwort mit Quellen und Grafik |
| Methode | die Theorie in drei Bildern, dann `web/inhalt/theorie.md` |
| Steckbrief (`#/knoten/…`) | Netz um den Knoten, Kennzahlen, Datenvorschau, ähnliche Knoten |

Jede Grafik hat eine Tabellenansicht. Kein Build-Schritt, kein Node: D3 7.9.0 und
topojson-client liegen als Dateien in `web/lib/`, die Seitenteile in `web/teile/`
werden erst bei Bedarf geladen.

## Konfiguration (`.env`)

Vorlage: `.env.example`. Kopieren nach `.env` und ausfüllen.

| Variable | Wozu |
|---|---|
| `SIM_AI_KEY` | Schlüssel für LiteLLM auf Minimind (Gemma) |
| `SPARK5_CLIENT_ID`, `SPARK5_CLIENT_SECRET` | Cloudflare-Access für die Einbettung auf spark5 |
| `PORTAL_BENUTZER`, `PORTAL_PASSWORT` | gemeinsamer Login; beide leer = offen (nur lokal!) |
| `KI_ANFRAGEN_PRO_STUNDE` | Begrenzung je Adresse, Standard 60 |
| `DOMAIN`, `PROJEKT`, `UID_GID` | nur für Docker Compose: Domain, Projektwurzel, Kennung des Werkzeug-Containers |
| `SWISS_OGD_DATEN`, `SWISS_OGD_GRAPH` | Orte der Datenbanken und des Graphen, falls nicht Standard |

`.env` nie in Git und nie weitergeben; sie enthält Schlüssel.

## Verzeichnisse

```
swiss_portal/   app (FastAPI), graph, netz (Wege), vorberechnen (Cockpit),
                auswahl, extraktion, pruefen, ki (Gemma, Einbettung), rdf, konfiguration
web/            index.html, app.js, stil.css, teile/ (diagramm, karte, entdecken, methode),
                karten/ (Gemeindegrenzen), lib/ (d3, topojson-client), inhalt/theorie.md
deploy/         Dockerfile, compose.yaml, compose.hinter-caddy.yaml, Caddyfile
tests/          rauchtest.py (gegen ein laufendes Portal), test_guard.py (SQL-Guard)
daten/          NICHT im Repository: Gemeindeverzeichnis, Auswahl, Extraktion, Einbettungen
```

## Schnittstellen

Alle unter `/api/…`, JSON. Die wichtigsten:

| Endpunkt | Zweck |
|---|---|
| `suche?q=…&gruppiert=1` | Suche, gruppiert nach Begriff, Ort, Datensatz |
| `knoten?id=…`, `graph?id=…&tiefe=1` | ein Knoten, sein Netz |
| `pfad?von=…&nach=…&k=3&hubs=aus` | kürzester Weg und Alternativen, wahlweise ohne Hubs |
| `cockpit`, `karte`, `entdeckungen`, `zufallsweg` | vorberechnete Cockpit-Daten |
| `tabelle`, `diagramm`, `vergleich`, `je_gemeinde` | Daten aus den 85 Datenbanken |
| `frage` (POST) | Frage an Gemma, Antwort mit Quellen |

`/gesund` meldet, ob das Portal läuft.

## URIs

Jeder Knoten hat eine URI unter `https://linkeddata.sim-research.ch/id/…`.
`/id/<pfad>` liefert je nach `Accept`-Kopf Turtle, JSON-LD oder leitet auf die
HTML-Seite weiter; `?format=ttl` bzw. `?format=jsonld` erzwingt das Format.
Die URIs sind **nicht persistent** — es ist ein Prototyp.

## Prüfen

```bash
PORTAL_URL=https://linkeddata.sim-research.ch python tests/rauchtest.py --ki   # Login aus Umgebung oder .env
pytest tests
```

Der Rauchtest prüft Suche («Schaf», «Bier»), Wege, Zufallswege, Cockpit und mit
`--ki` die Fragen. Erwartet: 0 Fehler.

## Abhängigkeiten

Der Kern läuft auf der Standardbibliothek. Für die Web-API: `fastapi`, `uvicorn`;
für den Graphenbau `numpy` (siehe `requirements.txt`).

Die Gemeindegrenzen in `web/karten/` stammen aus swisstopo swissBOUNDARIES3D
(Stand 1.1.2026); der Hinweis «Grenzen © swisstopo» unter jeder Karte ist
Lizenzbedingung und muss bleiben.
