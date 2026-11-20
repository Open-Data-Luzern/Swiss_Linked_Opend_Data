# Swiss Open Linked Data

Je Oberorganisation auf [opendata.swiss](https://opendata.swiss/de/organization) eine
SQLite-Datenbank: der vollständige Katalog der Organisation und, wo das Format es
hergibt, die Daten selbst.

Gemessen am 22. September 2026: **85 Oberorganisationen**, 176 Organisationen
insgesamt, **16'039 Datensätze**, rund 56'000 Datensammlungen.

## Die beiden Ebenen

Konsequent getrennt, wie im LU Datenportal:

| Begriff | Bedeutung | DCAT |
|---|---|---|
| **Datensatz** | der Katalogeintrag einer Dienststelle | Dataset |
| **Datensammlung** | die einzelne Datei darin | Distribution |

Nie „Ressource", nie „Dataset" im deutschen Text.

## Eine Datei je Oberorganisation

Wo opendata.swiss eine Hierarchie führt, zählt nur die oberste Ebene:

```
Bundesamt für Gesundheit BAG            -> bundesamt-fur-gesundheit-bag.sqlite
├─ Abteilung Übertragbare Krankheiten      (steht als Zeile in dim_organisation)
└─ Direktionsbereich Kranken- und           (dito)
   Unfallversicherung
```

Die Datensätze der Unterorganisationen landen in der Datei der
Oberorganisation — sonst fände man unter „BAG" nicht, was das BAG publiziert.
Welche Dienststelle einen Datensatz hält, steht in
`dim_datensatz.organisation_name`.

## Was in einer Datenbank steht

| Tabelle | Inhalt |
|---|---|
| `dim_organisation` | die Oberorganisation und ihre Unterorganisationen |
| `dim_datensatz` | alle Katalogeinträge, mit Lizenz, Kontakt, Zeitraum, Intervall |
| `dim_datensammlung` | alle Dateien, mit Format, URL, Grösse, Ladezustand |
| `dim_thema` | die DCAT-Themen mit ihrer Häufigkeit |
| `daten_*` | je geladener Datei eine Tabelle, Spalten wie die Quelle sie liefert |
| `daten_tabelle` | Verzeichnis der Datentabellen: Zeilen, Spalten, Kodierung, Trennzeichen |
| `daten_spalte` | je Spalte der bereinigte Name, der Originalname und der erkannte Typ |
| `quality_check` | was nicht geklappt hat, und warum |
| `aufbau_lauf` | wann gebaut, wie viel gekommen ist |

Dazu drei Sichten: `v_herkunft` (Tabelle → Datensammlung → Datensatz →
Organisation → Lizenz), `v_nicht_geladen` (was fehlt und weshalb) und
`v_bestand` (Zahlen auf einen Blick).

### Keine Zahl ohne Herkunft

Jede `daten_*`-Tabelle trägt als erste Spalte

```sql
datensammlung_id TEXT NOT NULL REFERENCES dim_datensammlung(id)
```

Eine Datenzeile ohne Herkunft **kann nicht existieren** — nicht bloss nicht
ausgeliefert werden. Wer zitieren will, joint über `v_herkunft` und hat Titel,
Organisation, Lizenztext und die Quell-URL.

### Was hier bewusst fehlt

Faktentabellen mit fachlichem Modell — `fact_gemeindefinanzen` und
Verwandtes. Eine solche Tabelle ist ein **Entscheid**: was die Entität ist,
welche Spalte Dimension und welche Kennzahl, wie Codes aufeinander abgebildet
werden. Im LU Datenportal steckt in elf Faktentabellen Wochen Handarbeit. Für
16'039 Datensätze von 85 Stellen in drei Sprachen ist das keine Frage des
Aufwands: Es gibt keine belastbare automatische Abbildung. Was dabei
herauskäme, sähe autoritativ aus und wäre still falsch — der schlechteste
Ausgang, den dieses Projekt kennt.

Die `daten_*`-Tabellen halten die Daten darum so, wie die Quelle sie liefert.

**Das heisst nicht, dass die Auswahl ungelöst bleibt.** Welche Tabelle zu einer
Frage passt, beantworten nicht Faktentabellen, sondern die Suchschicht aus
Profil, Datenkarte und Volltextindex — siehe
[Wie man die richtige Tabelle findet](#wie-man-die-richtige-tabelle-findet).

## Welche Formate geladen werden

Geladen wird, woraus Zeilen und Spalten werden können:

**CSV · TSV · TXT · XLSX · Parquet · JSON · GeoJSON · NDJSON · XML · ZIP**
(Archive werden geöffnet, ihre tabellarischen Einträge einzeln geladen.)

Nicht geladen, aber vollständig katalogisiert: PDF, HTML, GeoTIFF, WMS/WMTS,
SPARQL, RDF und alles andere ohne Zeilen und Spalten. Sie stehen in
`dim_datensammlung` mit `ladbar = 0` und erscheinen in `v_nicht_geladen` mit
dem Grund. Heruntergeladen werden sie nicht: Eine Datei zu holen, um sie
danach ungenutzt zu löschen, wäre reine Netzlast.

**Rohdateien werden nach dem Laden gelöscht.** Die Datenbank bleibt, die
heruntergeladene Datei nicht. Ein erneuter Lauf holt sie wieder; was schon
geladen ist, wird übersprungen.

### Gemessen statt geraten

Kodierung und Trennzeichen werden an der Datei gemessen und stehen nachher in
`daten_tabelle`. Spaltentypen entstehen aus einer Stichprobe von 500 Zeilen:
Nur wenn **jeder** nicht leere Wert passt, bekommt eine Spalte `INTEGER` oder
`REAL`, sonst `TEXT`. Das Schweizer Dezimalkomma (`1,5`) wird als solches
erkannt und in eine echte Zahl gewandelt. Im Zweifel `TEXT` — eine Zahl, die
als Text ankommt, ist ein Schönheitsfehler; ein stillschweigend verworfener
Wert wäre Datenverlust.

## Bedienung

```bash
python -m swiss_ogd organisationen          # die 85 Oberorganisationen auflisten
python -m swiss_ogd aufbauen                # alle bauen, eine nach der anderen
python -m swiss_ogd aufbauen --jobs 3       # drei gleichzeitig
python -m swiss_ogd aufbauen --nur swissmedic elcom
python -m swiss_ogd aufbauen --ohne-daten   # nur der Katalog, keine Downloads
pytest                                      # 60 Tests, ohne Netz
```

Ein Lauf ist **fortsetzbar**: Abbruch, Neustart, und es geht dort weiter, wo es
aufgehört hat. Jede Organisation ist unabhängig — ein Fehler bei einer kostet
die anderen nichts.

## Verzeichnisse

```
datenbanken/   <organisation>.sqlite — das Ergebnis
kataloge/      <organisation>.json   — die Rohernte, unabhängig vom Laden
protokolle/    Laufprotokolle
arbeit/        heruntergeladene Dateien, werden nach dem Laden gelöscht
src/swiss_ogd/ der Code
werkzeuge/     bestand.py, profilieren.py, nachholen.py
tests/         die Tests
```

## Abhängigkeiten

Dev-Bedingung „Limit Libraries": Der Kern läuft auf der **Standardbibliothek** —
`urllib`, `sqlite3`, `csv`, `zipfile`, `xml.etree`. Zwei optionale Zusätze:

| Paket | wofür | fehlt es |
|---|---|---|
| `openpyxl` | XLSX-Arbeitsmappen | Befund statt Absturz |
| `pyarrow` | Parquet | Befund statt Absturz |

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[formate,entwicklung]"
```

## Grenzen — lieber unvollständig als kaputt

Die Daten sind weit grösser, als der Katalog vermuten lässt. Die
Eidgenössische Zollverwaltung publiziert ihre Aussenhandelsstatistik mit
**29,7 Millionen Zeilen je Datei und je Sprache**; 40 von 85 Organisationen
belegten 75 GB, davon 51 GB nur diese eine. Am 22. September 2026 lief die
Platte voll, und danach scheiterte jede weitere Organisation an
`No space left on device`.

Ein lauffähiges System mit vollständigem Katalog und den Dateien, die
hineinpassen, ist mehr wert als ein vollständiges System, das die Platte füllt
und abbricht. Darum drei Grenzen, jede einzeln abschaltbar (`0` = keine):

| Variable | Standard | Wirkung |
|---|---|---|
| `SWISS_OGD_MAX_BYTES` | 300 MB | Datei grösser → nicht geladen. Geprüft **vor** dem Download an der im Katalog gemeldeten Grösse, und beim Laden noch einmal |
| `SWISS_OGD_MAX_DATENBANK_BYTES` | 2 GB | Datenbank grösser → Katalog bleibt vollständig, es kommen keine Daten mehr dazu |
| `SWISS_OGD_MIN_FREI_BYTES` | 5 GB | weniger frei auf dem Zielträger → Laden stoppt sofort |

Was an einer Grenze scheitert, bleibt im Katalog und steht mit Grund in
`v_nicht_geladen`; dazu ein Befund `zu_gross` oder `grenze_erreicht`.
Weggelassen wird nie stillschweigend.

So bleibt auch die Zollverwaltung im Bestand — mit vollständigem Katalog, ihren
kleineren Dateien und einem Vermerk bei jeder ausgelassenen. „Die Riesen
überspringen" heisst nicht, die Organisation wegzulassen.

## Wo die Daten liegen

Datenbanken müssen nicht beim Quellcode liegen. `SWISS_OGD_WURZEL` verlegt
`datenbanken/`, `kataloge/`, `protokolle/` und `arbeit/` auf einen anderen
Träger — nötig, wenn die Systemplatte klein ist:

```bash
export SWISS_OGD_WURZEL="D:\Swiss_Open_Linked_Data"
python -m swiss_ogd aufbauen --jobs 3
python werkzeuge/bestand.py          # die Werkzeuge folgen derselben Variable
```

## Höflichkeit gegenüber der Quelle

Eine Anfrage pro Sekunde **und Host**, aussagekräftiger User-Agent,
Wiederholung mit exponentiellem Backoff bei 429, 5xx und Transportfehlern. Ein
Lauf über 85 Organisationen berührt ebenso viele Server; eine globale Drossel
würde jeden davon unnötig bremsen, eine fehlende keinen davon schonen.

## Wie man die richtige Tabelle findet

Das ist die eigentliche Frage einer Datenbank mit zehntausenden Tabellen — und
sie wird **nicht** von Faktentabellen beantwortet, sondern von einer
Suchschicht. Auch im LU Datenportal lösen das nicht die `fact_*`-Tabellen,
sondern die Datenkarten und der Qdrant-Index; die Faktentabellen sagen, wie man
abfragt, nachdem man gewählt hat.

`werkzeuge/profilieren.py` baut diese Schicht in drei Stufen, alle
deterministisch aus den Daten und ohne Sprachmodell:

1. **`daten_profil`** — je Spalte Typ, Zahl verschiedener Werte, Anteil leer,
   Minimum, Maximum und, bei kleiner Kardinalität, **die Werte selbst**. Dass
   eine Spalte `Bewilligung` heisst, sagt wenig; dass darin
   „FZA/VEP Bewilligung" steht, entscheidet.
2. **`datenkarte`** — je Tabelle ein Fliesstext aus Titel, Organisation,
   Beschreibung, Schlagworten, Zeitraum, Spalten und Vokabular.
3. **`datenkarte_fts`** — ein FTS5-Volltextindex über die Karten, in derselben
   Datei. FTS5 gehört zu SQLite: kein zweiter Dienst, keine neue Bibliothek.

```bash
python werkzeuge/profilieren.py
python werkzeuge/profilieren.py --suche "Betaeubungsmittel Diebstahl Kanton"
```

So sieht eine Karte aus — man beachte, dass die kryptische Spalte
`z2geschlecht` ihr Vokabular mitführt:

```
Jugendbefragung 2021 der Stadt Uster — Antworten
Organisation: Stadt Uster
Beschreibung: Befragung von Jugendlichen mit Wohnsitz in Uster zu den
  Schwerpunktthemen Social Media, Sicherheitsempfinden und Jugendgewalt.
Tabelle daten_stadt_uster_jugendbefragung_2021...: 213 Zeilen, 76 Spalten
  z1alter (Z1Alter) [INTEGER]: 14 bis 20
  z2geschlecht (Z2Geschlecht) [TEXT]: weiblich, männlich, non-binär
  a1socialmedia_tiktok (A1Socialmedia_TikTok) [TEXT]: mehrmals täglich,
    keinen Account, einmal pro Tag, selten, jede Woche
```

Eine grosse Tabelle wird an einer Stichprobe profiliert; `daten_profil`
vermerkt das in `vollstaendig = 0`, damit niemand eine Stichprobe für eine
Zählung hält.

## Wenn der Katalogeintrag veraltet ist

Ein Eintrag auf opendata.swiss veraltet, ohne dass jemand ihn nachführt. Beim
SEM zeigen alle 80 Einträge auf HTTP 404 — die Dateien sind aber da, das SEM
hat nur die Namen kleingeschrieben und das Sprachkürzel entfernt:

```
Katalog:  .../2019/csv/2-30-Best-Flu-d-2019.csv     404
wirklich: .../2019/csv/2-30-best-flu-2019.csv       200
```

Bei 404 oder 410 probiert `netz.ersatzvarianten` darum mechanische
Schreibvarianten **desselben** Namens: kleingeschrieben, und ohne einen kurzen
**Buchstaben**-Marker (`d`, `f`, `j`). Ziffern werden nie weggelassen — sie
sind die Tabellennummer, und `2-30` ohne die `30` könnte auf eine andere
Tabelle der Reihe zeigen.

Weil jede Variante aus dem katalogisierten Namen abgeleitet ist, kann sie nie
auf eine **andere** Datensammlung zeigen. Der französische Eintrag
`2-30-effectif-refu-f-2019.csv` findet nichts — das SEM hat die französische
Fassung eingestellt — und wird als entfallen vermerkt, statt still die deutsche
zu bekommen.

Wird eine Variante verwendet, steht sie in `dim_datensammlung.bezogen_von_url`,
`v_herkunft.url` zeigt sie statt der katalogisierten, und ein Befund
`ersatz_url` hält beide fest. Eine Zahl trägt die Herkunft, aus der sie
stammt — nicht die, die im Katalog steht.

## Was die Quelle schuldig bleibt

Widersprüche werden nicht stillschweigend korrigiert, sondern in
`quality_check` erfasst. Beispiel vom 22. September 2026: Beim SEM führen alle
80 katalogisierten Links auf HTTP 404. Die deutschen Dateien sind da und werden
über eine Schreibvariante geladen (siehe oben); die französischen hat das SEM
eingestellt und bleiben als Befund stehen. Beides ist ein Befund über den
Katalog des SEM, kein Fehler dieses Werkzeugs.

```sql
SELECT typ, schweregrad, COUNT(*) FROM quality_check GROUP BY 1, 2;
SELECT * FROM v_nicht_geladen;
```
