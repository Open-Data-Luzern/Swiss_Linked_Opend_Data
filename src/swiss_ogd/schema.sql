-- ===========================================================================
-- Swiss Open Linked Data — Schema einer Organisationsdatenbank (SQLite)
--
-- Je Oberorganisation auf opendata.swiss eine Datei. Das Schema ist fuer alle
-- 85 Dateien identisch; eine Auswertung, die gegen eine laeuft, laeuft gegen
-- alle.
--
-- Zwei Ebenen, konsequent getrennt:
--   datensatz     = der Katalogeintrag einer Dienststelle (DCAT Dataset)
--   datensammlung = die einzelne Datei darin              (DCAT Distribution)
-- Nie "Ressource", nie "Dataset" im deutschen Text.
--
-- "Keine Zahl ohne Herkunft" ist hier physisch verankert: jede generisch
-- geladene Datentabelle traegt eine Spalte datensammlung_id NOT NULL. Eine
-- Datenzeile ohne Herkunft kann nicht existieren, nicht bloss nicht
-- ausgeliefert werden.
--
-- Was hier NICHT steht: Faktentabellen mit fachlichem Modell. Die gibt es im
-- LU Datenportal, und sie sind dort von Hand modelliert — je Datensammlung
-- ein Normalisierer. Fuer 16'039 Datensaetze ist das nicht zu haben. Die
-- Tabellen daten_* halten die Daten so, wie die Quelle sie liefert; die
-- Modellierung bleibt der Auswertung ueberlassen.
-- ===========================================================================

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- ---------------------------------------------------------------------------
-- Katalog
-- ---------------------------------------------------------------------------

-- Die Oberorganisation und ihre Unterorganisationen. Genau eine Zeile hat
-- ist_oberorganisation = 1; sie bestimmt den Namen dieser Datei.
CREATE TABLE IF NOT EXISTS dim_organisation (
    name                 TEXT PRIMARY KEY,
    titel_de             TEXT NOT NULL,
    beschreibung_de      TEXT,
    ist_oberorganisation INTEGER NOT NULL,
    eltern_name          TEXT,
    opendata_url         TEXT,
    anzahl_datensaetze   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dim_datensatz (
    id                       TEXT PRIMARY KEY,
    slug                     TEXT NOT NULL,
    titel_de                 TEXT NOT NULL,
    beschreibung_de          TEXT,
    organisation             TEXT NOT NULL,   -- Anzeigename der Dienststelle
    organisation_name        TEXT NOT NULL REFERENCES dim_organisation(name),
    herausgeber              TEXT,
    thema                    TEXT,            -- JSON-Liste
    schlagworte              TEXT,            -- JSON-Liste
    lizenz                   TEXT,
    lizenz_text              TEXT,            -- muss in jedem Bericht erscheinen
    kontakt                  TEXT,
    veroeffentlicht          TEXT,
    aktualisiert             TEXT,
    aktualisierungsintervall TEXT,
    zeitraum_von             TEXT,
    zeitraum_bis             TEXT,
    raum                     TEXT,
    landingpage              TEXT,
    opendata_url             TEXT,
    identifier               TEXT,
    dokumentation            TEXT,            -- JSON-Liste
    i14y_uri                 TEXT
);

CREATE TABLE IF NOT EXISTS dim_datensammlung (
    id                   TEXT PRIMARY KEY,
    datensatz_id         TEXT NOT NULL REFERENCES dim_datensatz(id),
    titel_de             TEXT NOT NULL,
    beschreibung_de      TEXT,
    format               TEXT,
    url                  TEXT NOT NULL,
    byte_size            INTEGER,
    lizenz               TEXT,
    zeitliche_aufloesung TEXT,
    feldbeschreibung_url TEXT,
    zugang               TEXT NOT NULL DEFAULT 'direkt',
    verfuegbar           INTEGER NOT NULL DEFAULT 1,
    md5                  TEXT,
    stand                TEXT,
    herkunft_art         TEXT NOT NULL DEFAULT 'automatisch',
    -- Ladezustand. ladbar = das Format kann eine Tabelle werden; geladen =
    -- es ist tatsaechlich eine daraus geworden. Ein zweiter Lauf ueberspringt,
    -- was geladen = 1 hat.
    ladbar               INTEGER NOT NULL DEFAULT 0,
    geladen              INTEGER NOT NULL DEFAULT 0,
    zeilen               INTEGER,
    bytes_geladen        INTEGER,
    geladen_am           TEXT,
    -- Die URL, aus der die Daten wirklich stammen. NULL heisst: die aus
    -- `url`. Gesetzt wird sie, wenn der Katalogeintrag veraltet war und eine
    -- Schreibvariante geholt hat (siehe netz.ersatzvarianten). Eine Zahl
    -- traegt die Herkunft, aus der sie stammt, nicht die, die im Katalog
    -- steht.
    bezogen_von_url      TEXT,
    CHECK (zugang IN ('direkt', 'geodatenshop', 'handbezug')),
    CHECK (herkunft_art IN ('automatisch', 'handbezug', 'geodatenshop'))
);

CREATE INDEX IF NOT EXISTS ix_datensammlung_datensatz
    ON dim_datensammlung (datensatz_id);
CREATE INDEX IF NOT EXISTS ix_datensatz_organisation
    ON dim_datensatz (organisation_name);

-- DCAT-Themen, wie opendata.swiss sie fuehrt.
CREATE TABLE IF NOT EXISTS dim_thema (
    code               TEXT PRIMARY KEY,
    bezeichnung        TEXT NOT NULL,
    anzahl_datensaetze INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Verzeichnis der geladenen Daten
--
-- Je geladener Datei eine Zeile. Der Tabellenname ist der Schluessel; die
-- Tabelle selbst heisst genauso und traegt dieselbe datensammlung_id in
-- jeder Zeile.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS daten_tabelle (
    tabelle          TEXT PRIMARY KEY,
    datensammlung_id TEXT NOT NULL REFERENCES dim_datensammlung(id),
    datensatz_id     TEXT NOT NULL REFERENCES dim_datensatz(id),
    quelle_datei     TEXT,          -- Dateiname, bei ZIP der Eintrag im Archiv
    format           TEXT,
    zeilen           INTEGER NOT NULL,
    spalten          INTEGER NOT NULL,
    kodierung        TEXT,
    trennzeichen     TEXT,
    geladen_am       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daten_spalte (
    tabelle       TEXT NOT NULL REFERENCES daten_tabelle(tabelle),
    position      INTEGER NOT NULL,
    name          TEXT NOT NULL,   -- bereinigter Spaltenname in der Tabelle
    name_original TEXT NOT NULL,   -- so, wie die Quelle ihn schreibt
    typ           TEXT NOT NULL,   -- INTEGER | REAL | TEXT, aus den Werten erkannt
    PRIMARY KEY (tabelle, position)
);

-- ---------------------------------------------------------------------------
-- Betrieb
-- ---------------------------------------------------------------------------

-- Widersprueche an der Quelle werden nicht stillschweigend korrigiert,
-- sondern hier erfasst.
CREATE TABLE IF NOT EXISTS quality_check (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    datensammlung_id TEXT,          -- NULL = Befund betrifft keine einzelne Datei
    typ              TEXT NOT NULL,
    schweregrad      TEXT NOT NULL DEFAULT 'warnung',
    meldung          TEXT NOT NULL,
    details_json     TEXT,
    geprueft_am      TEXT NOT NULL,
    CHECK (schweregrad IN ('info', 'warnung', 'fehler'))
);

CREATE INDEX IF NOT EXISTS ix_quality_typ ON quality_check (typ, schweregrad);

CREATE TABLE IF NOT EXISTS aufbau_lauf (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    organisation     TEXT NOT NULL,
    version          TEXT NOT NULL,
    begonnen_am      TEXT NOT NULL,
    beendet_am       TEXT,
    datensaetze      INTEGER,
    datensammlungen  INTEGER,
    tabellen         INTEGER,
    zeilen           INTEGER,
    bytes_geladen    INTEGER,
    befunde          INTEGER,
    abgeschlossen    INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Sichten
-- ---------------------------------------------------------------------------

-- Die Herkunftssicht: zu jeder geladenen Tabelle die vollstaendige Kette
-- Tabelle -> Datensammlung -> Datensatz -> Organisation -> Lizenz.
-- Sie ist der Ansatzpunkt fuer jede Zitation.
DROP VIEW IF EXISTS v_herkunft;
CREATE VIEW v_herkunft AS
SELECT
    t.tabelle,
    t.zeilen,
    t.spalten,
    t.geladen_am,
    s.id            AS datensammlung_id,
    s.titel_de      AS datensammlung,
    s.format,
    COALESCE(s.bezogen_von_url, s.url) AS url,
    s.url            AS url_katalog,
    s.stand,
    d.id            AS datensatz_id,
    d.titel_de      AS datensatz,
    d.organisation,
    d.lizenz,
    d.lizenz_text,
    d.opendata_url,
    d.aktualisiert
FROM daten_tabelle t
JOIN dim_datensammlung s ON s.id = t.datensammlung_id
JOIN dim_datensatz     d ON d.id = t.datensatz_id;

-- Was der Katalog kennt, aber nicht geladen ist, und warum.
DROP VIEW IF EXISTS v_nicht_geladen;
CREATE VIEW v_nicht_geladen AS
SELECT
    s.id AS datensammlung_id,
    s.titel_de,
    s.format,
    s.url,
    d.titel_de AS datensatz,
    d.organisation,
    CASE
        WHEN s.zugang = 'geodatenshop' THEN 'nur als Verweis publiziert'
        WHEN s.ladbar = 0              THEN 'Format ist nicht tabellarisch'
        WHEN q.typ = 'zu_gross'        THEN 'ueber der Groessengrenze'
        WHEN q.typ IS NOT NULL         THEN 'Laden fehlgeschlagen: ' || q.typ
        ELSE 'noch nicht geladen'
    END AS grund
FROM dim_datensammlung s
JOIN dim_datensatz d ON d.id = s.datensatz_id
LEFT JOIN (
    SELECT datensammlung_id, MIN(typ) AS typ
      FROM quality_check
     WHERE datensammlung_id IS NOT NULL
     GROUP BY datensammlung_id
) q ON q.datensammlung_id = s.id
WHERE s.geladen = 0;

-- Bestand auf einen Blick.
DROP VIEW IF EXISTS v_bestand;
CREATE VIEW v_bestand AS
SELECT
    (SELECT titel_de FROM dim_organisation WHERE ist_oberorganisation = 1
      ORDER BY name LIMIT 1)                     AS organisation,
    (SELECT COUNT(*) FROM dim_organisation)      AS organisationen,
    (SELECT COUNT(*) FROM dim_datensatz)         AS datensaetze,
    (SELECT COUNT(*) FROM dim_datensammlung)     AS datensammlungen,
    (SELECT COUNT(*) FROM dim_datensammlung WHERE ladbar = 1)  AS ladbar,
    (SELECT COUNT(*) FROM dim_datensammlung WHERE geladen = 1) AS geladen,
    (SELECT COUNT(*) FROM daten_tabelle)         AS datentabellen,
    (SELECT COALESCE(SUM(zeilen), 0) FROM daten_tabelle) AS datenzeilen,
    (SELECT COUNT(*) FROM quality_check WHERE schweregrad = 'fehler') AS fehler;

-- ---------------------------------------------------------------------------
-- Auffindbarkeit: Profil, Datenkarte, Volltextindex
--
-- Diese drei Tabellen beantworten die Frage, die der Katalog allein nicht
-- beantwortet: **welche** der zehntausenden Tabellen die richtige ist.
--
-- Ein Spaltenname sagt, dass es eine Spalte `Bewilligung` gibt. Er sagt
-- nicht, dass darin "FZA/VEP Bewilligung" steht. Genau dieses Vokabular
-- entscheidet aber, ob eine Frage wie "wie viele Bulgaren in Zuerich" auf
-- diese Tabelle passt. Darum wird es gemessen und mitgefuehrt.
--
-- Gefuellt von werkzeuge/profilieren.py, nicht vom Aufbau — Profilieren ist
-- ein eigener Gang ueber die fertige Datei und darf das Laden nicht bremsen.
-- Alles darin ist deterministisch aus den Daten gerechnet; kein
-- Sprachmodell ist beteiligt.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS daten_profil (
    tabelle            TEXT NOT NULL,
    spalte             TEXT NOT NULL,
    typ                TEXT NOT NULL,
    zeilen_geprueft    INTEGER NOT NULL,
    vollstaendig       INTEGER NOT NULL,  -- 0 = nur eine Stichprobe geprueft
    anzahl_verschieden INTEGER,
    anteil_null        REAL,
    min_wert           TEXT,
    max_wert           TEXT,
    -- JSON [[Wert, Anzahl], ...]; nur bei kleiner Kardinalitaet gefuellt.
    -- Das ist das Vokabular, an dem eine Frage eine Tabelle findet.
    top_werte          TEXT,
    profiliert_am      TEXT NOT NULL,
    PRIMARY KEY (tabelle, spalte)
);

-- Je Tabelle ein Fliesstext: Titel, Organisation, Beschreibung, Spalten und
-- deren Vokabular. Das ist die Einheit, die ein Suchindex aufnimmt — das
-- Gegenstueck zu den Datenkarten des LU Datenportals.
CREATE TABLE IF NOT EXISTS datenkarte (
    tabelle    TEXT PRIMARY KEY,
    karte      TEXT NOT NULL,
    erzeugt_am TEXT NOT NULL
);

-- Der Suchindex liegt in derselben Datei. FTS5 gehoert zu SQLite; es braucht
-- keinen zweiten Dienst und keine zusaetzliche Bibliothek.
CREATE VIRTUAL TABLE IF NOT EXISTS datenkarte_fts USING fts5(
    tabelle UNINDEXED,
    karte,
    tokenize = 'unicode61 remove_diacritics 2'
);

DROP VIEW IF EXISTS v_datenkarte;
CREATE VIEW v_datenkarte AS
SELECT
    k.tabelle,
    h.datensatz,
    h.organisation,
    h.datensammlung,
    h.zeilen,
    h.spalten,
    h.lizenz_text,
    h.url,
    h.opendata_url,
    k.karte
FROM datenkarte k
JOIN v_herkunft h ON h.tabelle = k.tabelle;
