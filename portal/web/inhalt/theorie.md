# Theorie: Wie aus offenen Daten verknüpfte Daten werden

## Logik, Datenmodell und Grenzen von Linked Data am Beispiel des Schweizer OGD-Katalogs

*Arbeitspapier zum Prototyp — Stand November 2026*

---

## Überblick

Die Schweizer Verwaltung publiziert viele offene Daten, aber sie verbindet sie kaum. Dieselbe Kennzahl liegt bei mehreren Anbietern, in verschiedenen Formaten, unter verschiedenen Spaltennamen, ohne dass irgendwo festgehalten wäre, dass es dieselbe ist. Linked Data ist die Antwort auf genau diese Lücke: ein Satz von Gestaltungsprinzipien, nach denen Daten Namen tragen, die man nachschlagen kann, und Verweise, denen man folgen kann.

Dieses Papier legt in acht Kapiteln die Logik dar, auf der der Prototyp aufbaut. Es beschreibt das Datenmodell, unterscheidet drei Klassen von Verbindungen nach ihrer Verlässlichkeit, ordnet die technische Umsetzung in die Unterscheidung von Substrat, Protokoll und Sicht ein und benennt, was der Prototyp nicht leistet. Es ist bewusst knapp gehalten und auf das Diskussionspapier «Information Governance Doctrine» v2.0 abgestimmt, dessen Begriffe es dort übernimmt, wo sie passen.

---

## 1. Ausgangslage

### 1.1 Viele Daten, wenig Verbindung

Auf opendata.swiss publizieren heute **85 Oberorganisationen**: Bundesämter, Kantone, Städte, Gemeinden und öffentliche Unternehmen. Der Prototyp hält ihren Katalog und, wo das Format es zulässt, ihre Daten in je einer Datenbank pro Oberorganisation:

| Grösse | Anzahl |
| --- | --- |
| Oberorganisationen | 85 |
| Datensätze (Katalogeinträge) | 15'934 |
| Datensammlungen (einzelne Dateien) | 79'392 |
| davon als Tabelle geladen | 12'768 |

Jeder dieser Datensätze ist für sich offen: frei zugänglich, mit Lizenz, meist maschinenlesbar. Was fehlt, ist die Verbindung **zwischen** ihnen.

### 1.2 Ein Beispiel: die Leerwohnungsziffer

Die Leerwohnungsziffer, der Anteil leerstehender Wohnungen am Gesamtbestand, wird in der Schweiz an mehreren Stellen publiziert. Im Katalog finden sich unter anderem:

- beim **Kanton Basel-Landschaft** die Leerwohnungsziffer nach Zimmerzahl, Gemeinde und Jahr seit 2002,
- beim **Kanton Zug** die Leerwohnungsziffer des Kantons und nach Gemeinde,
- beim **Bundesamt für Statistik** im Bereich Bau- und Wohnungswesen.

Drei Anbieter, eine Kennzahl, kein Verweis. Nichts im Katalog sagt, dass diese drei Einträge dasselbe messen. Nichts sagt, dass «Gemeinde» in der Tabelle aus Liestal und «Gemeinde» in der Tabelle aus Zug dieselbe Art von Ding meint. Wer die Zahlen vergleichen will, muss das selbst herausfinden, jedes Mal von vorn.

### 1.3 Was dieses Papier will

Dieses Papier will zeigen, was sich ändert, wenn man diese Verbindungen ausdrücklich macht, und was dabei an Genauigkeit verloren geht. Es ist kein Plädoyer für eine bestimmte Technologie, sondern eine Begriffsklärung als Grundlage für den Prototyp.

> **Kernsatz.** Offene Daten sind heute vorhanden. Was fehlt, ist nicht der Zugang zu ihnen, sondern das Wissen, welche von ihnen zusammengehören.

---

## 2. Die Logik von Linked Data

### 2.1 Open Data ist nicht Linked Data

Die beiden Begriffe werden oft gleichgesetzt. Sie bezeichnen aber zwei unabhängige Eigenschaften:

| | Open Data | Linked Data |
| --- | --- | --- |
| **Frage** | Darf ich die Daten nutzen? | Kann ich den Daten folgen? |
| **Kriterium** | offene Lizenz, freier Zugang | Namen als URIs, Verweise auf andere URIs |
| **Möglich ohne das andere** | ja: offene Tabelle ohne Verweise | ja: verknüpfte Daten unter geschlossener Lizenz |

Das EU-Trainingsmodul zu Linked Data hält diese Unterscheidung ausdrücklich fest: Offene Daten können unter einer offenen Lizenz veröffentlicht werden, ohne mit anderen Datenquellen verknüpft zu sein; verknüpfte Daten können mit offenen Standards auf andere Quellen verweisen, ohne offen lizenziert zu sein. Der Schweizer OGD-Katalog ist weitgehend das Erste. Der Prototyp untersucht, wie weit er sich zum Zweiten bringen lässt.

### 2.2 Die vier Prinzipien

Tim Berners-Lee hat 2006 vier Gestaltungsprinzipien formuliert, die bis heute die Definition von Linked Data tragen:

1. **URIs als Namen für Dinge.** Nicht nur Dokumente bekommen eine Adresse, sondern die Dinge selbst: eine Gemeinde, eine Organisation, eine Kennzahl.
2. **HTTP-URIs**, damit man diese Namen nachschlagen kann.
3. **Beim Nachschlagen nützliche Information liefern**, in Standardformaten (RDF) und abfragbar (SPARQL).
4. **Verweise auf andere URIs**, damit man weitere Dinge entdecken kann.

Die ersten drei Prinzipien machen Daten **adressierbar**. Erst das vierte macht sie **verknüpft**. Ein RDF-Export, der nur auf sich selbst verweist, erfüllt das Format, aber nicht die Idee.

### 2.3 Das Tripel

RDF gliedert jede Aussage in drei Teile: **Subjekt**, **Prädikat** und **Objekt**. Das EU-Modul illustriert das mit Brüssel als Hauptstadt Belgiens. Übertragen auf den Schweizer Katalog:

```
Subjekt                       Prädikat              Objekt
<datensatz/leerwohnungen-bl>  dct:publisher         <organisation/kanton-basel-landschaft>
<datensatz/leerwohnungen-bl>  misst                 <begriff/leerwohnungsziffer>
<datensatz/leerwohnungen-zg>  misst                 <begriff/leerwohnungsziffer>
```

Die dritte und vierte Zeile verbinden zwei Datensätze, ohne dass einer vom anderen weiss. Die Verbindung entsteht dadurch, dass beide auf **dasselbe Objekt** verweisen. Das ist der ganze Mechanismus.

### 2.4 Der Graph, formal

Das Modell ist bewusst elementar gehalten. Seien

- U = Menge aller **URIs** (benannte Dinge),
- L = Menge aller **Literale** (Zeichenketten, Zahlen, Daten).

Ein **Tripel** ist ein Element t ∈ U × U × (U ∪ L): Subjekt und Prädikat sind immer benannte Dinge, das Objekt kann ein Ding oder ein Wert sein.

Ein **Graph** ist eine Menge von Tripeln:

G ⊆ U × U × (U ∪ L)

Zwei Graphen G₁ und G₂ zweier Anbieter lassen sich ohne jede Abstimmung vereinigen: G₁ ∪ G₂ ist wieder ein Graph. Verknüpft sind sie genau dann, wenn sie gemeinsame URIs verwenden:

verknüpft(G₁, G₂) ⟺ knoten(G₁) ∩ knoten(G₂) ∩ U ≠ ∅

Daraus folgt die wichtigste praktische Einsicht dieses Papiers: **Verknüpfung entsteht nicht durch das Format, sondern durch geteilte Namen.** Zwei Anbieter, die beide RDF publizieren, aber jeder seine eigenen URIs für «Gemeinde Liestal» prägt, haben zwei unverbundene Graphen.

> **Kernsatz.** RDF ist ein Format. Linked Data entsteht erst, wenn verschiedene Anbieter für dasselbe Ding denselben Namen verwenden.

---

## 3. Das Datenmodell

### 3.1 Die Begriffshierarchie

Das Modell übernimmt die Ebenen des Katalogstandards DCAT und ergänzt sie um die Ebene der geladenen Daten:

```
KATALOG                    (opendata.swiss)
  └── ORGANISATION         (Oberorganisation mit Unterorganisationen)
        └── DATENSATZ      (Katalogeintrag; DCAT Dataset)
              └── DATENSAMMLUNG   (einzelne Datei; DCAT Distribution)
                    └── TABELLE   (geladene Datensammlung)
                          └── BEOBACHTUNG   (eine Zeile)
```

Wie in der Doktrin ist diese Hierarchie eine **Ordnungsaussage**, keine Speicheraussage. Sie sagt, woraus sich Herkunft, Lizenz und Zuständigkeit ableiten. Sie sagt nicht, dass Verbindungen nur entlang dieses Baumes verlaufen dürfen. Gerade die interessanten Verbindungen verlaufen quer zu ihm: von einem Datensatz des Kantons Zug zu einem des Bundes, über einen gemeinsamen Begriff.

**Organisation.** Die publizierende Stelle. Der Prototyp führt je Oberorganisation eine Datenbank; die Unterorganisationen stehen als Zeilen darin. Welche Dienststelle einen Datensatz hält, bleibt am Datensatz vermerkt.

**Datensatz.** Der Katalogeintrag einer Dienststelle, mit Titel, Beschreibung, Schlagworten, Thema, Lizenz, Kontakt und Zeitraum. Er ist die Einheit, die ein Mensch sucht und zitiert.

**Datensammlung.** Die einzelne Datei im Datensatz, mit Format, Adresse und Grösse. Ein Datensatz kann viele Datensammlungen haben: dieselben Daten als CSV und XLSX, oder eine Datei pro Jahr.

**Tabelle und Beobachtung.** Wo eine Datensammlung Zeilen und Spalten hergibt, wird sie als Tabelle geladen, so wie die Quelle sie liefert. Jede Zeile trägt die Kennung der Datensammlung, aus der sie stammt. Eine Beobachtung ohne Herkunft kann im Modell nicht existieren.

### 3.2 Begriffsgegenüberstellung

Die häufigste Quelle von Missverständnissen sind englische Fachbegriffe, die im Deutschen mit wechselnder Bedeutung verwendet werden.

| Ebene | Bevorzugter Begriff | DCAT | Synonyme und falsche Synonyme in der Praxis |
| --- | --- | --- | --- |
| Katalogeintrag | **Datensatz** | Dataset | Datenpaket, Package (CKAN), Eintrag |
| Einzelne Datei | **Datensammlung** | Distribution | Datei, Download, Format, *Ressource* (CKAN) |
| Geladene Datei | **Tabelle** | — | Datentabelle, Sheet |
| Eine Zeile | **Beobachtung** | (Observation, RDF Data Cube) | Datensatz (!), Record, Eintrag |
| Benanntes Konzept | **Begriff** | (SKOS Concept) | Schlagwort, Tag, Kategorie |

**Wichtige Klärung.** Zwei Begriffe werden im deutschen Text dieses Projekts nicht verwendet. **«Ressource»** ist in CKAN, der Software hinter opendata.swiss, die Bezeichnung für die Datei; in RDF bezeichnet «Ressource» dagegen jedes beliebige benannte Ding. Das Wort trägt also zwei unverträgliche Bedeutungen. **«Dataset»** ist auf Englisch der Katalogeintrag, wird im Deutschen aber ebenso für eine einzelne Tabelle oder gar eine Zeile gebraucht. Das gefährlichste falsche Synonym ist **«Datensatz» im Sinn einer Datenbankzeile**: In diesem Projekt ist ein Datensatz immer ein Katalogeintrag, nie eine Zeile.

### 3.3 Anschluss an DCAT

DCAT (Data Catalog Vocabulary) ist das W3C-Vokabular für Datenkataloge, und opendata.swiss beschreibt seinen Katalog nach dem Schweizer Anwendungsprofil davon. Die Ebenen Datensatz und Datensammlung sind damit nicht erfunden, sondern die deutsche Benennung von **dcat:Dataset** und **dcat:Distribution**. Für den Prototyp heisst das: Der Katalogteil des Graphen ist eine Übersetzung bestehender Struktur, keine neue Modellierung. Neu sind erst die Begriffe und Orte, an denen sich Datensätze treffen (Kap. 4).

> **Kernsatz.** Datensatz und Datensammlung sind zwei Ebenen. Wer sie vermischt, kann weder sauber zitieren noch sauber verknüpfen.

---

## 4. Woher die Verbindungen kommen

### 4.1 Drei Klassen von Kanten

Nicht jede Verbindung ist gleich verlässlich. Der Prototyp unterscheidet darum drei Klassen und zeigt jede Kante mit ihrer Klasse an:

| Klasse | Woher | Beispiel | Verlässlichkeit |
| --- | --- | --- | --- |
| **belegt** | steht so im Katalog | Datensatz → publizierende Organisation; Datensatz → DCAT-Thema | so verlässlich wie der Katalog selbst |
| **gemessen** | aus den Daten selbst, nach festen Regeln | Tabelle mit einer Spalte gültiger BFS-Gemeindenummern → Gemeinde | hoch, prüfbar |
| **abgeleitet** | vom Sprachmodell aus Titel und Beschreibung extrahiert | Datensatz → Begriff «Leerwohnungsziffer» | unschärfer, mit Beleg |

Die drei Klassen werden nie vermischt. Eine abgeleitete Kante wird nicht dadurch zu einer belegten, dass viele andere Kanten in dieselbe Richtung zeigen.

### 4.2 Belegt: was der Katalog schon sagt

Organisation, Thema, Lizenz und Zeitraum stehen im Katalog. Sie in Tripel zu übersetzen, ist eine mechanische Aufgabe ohne Ermessen. Diese Kanten verbinden allerdings wenig: Zwei Datensätze, die beide das Thema «Bevölkerung» tragen, sind nur grob verwandt.

### 4.3 Gemessen: was die Daten selbst sagen

Die stärksten Verbindungen liegen in den Spalten. Wo zwei Tabellen dieselbe Art von Schlüssel tragen, lassen sie sich über diesen Schlüssel zusammenführen. Eine Durchsicht der Spaltennamen aller 12'768 Tabellen ergibt folgende Grössenordnungen. Es handelt sich um eine Suche nach Namensmustern, nicht um geprüfte Werte:

| Gemeinsamer Schlüssel | Tabellen | Organisationen |
| --- | --- | --- |
| Datum | ~2'200 | 44 |
| Jahr | ~1'450 | 27 |
| Gemeindename | ~690 | 18 |
| BFS-Gemeindenummer | ~530 | 14 |
| Kanton | ~200 | 20 |
| Postleitzahl | ~150 | 18 |
| Gebäude- und Grundstücksnummer (EGID/EGRID) | ~80 | 10 |

Eine Spalte heisst nicht deshalb Gemeindenummer, weil sie so benannt ist. Als **gemessen** gilt eine Kante erst, wenn die Werte der Spalte gegen das amtliche Gemeindeverzeichnis geprüft sind: Liegen sie im gültigen Bereich, und treffen sie existierende Gemeinden?

**Gemeindenamen sind kein Schlüssel.** Gemeinden fusionieren, Namen kommen mehrfach vor, Schreibweisen weichen ab. Ein Gemeindename wird darum nur dann einer Gemeinde zugeordnet, wenn er **exakt** einem Eintrag des amtlichen Gemeindeverzeichnisses zu einem bestimmten Stichtag entspricht. Was nicht eindeutig passt, bleibt unverknüpft und wird als Befund festgehalten, statt geraten zu werden. Ein unverknüpfter Name ist eine Lücke; ein falsch verknüpfter ist ein Fehler, der wie eine Tatsache aussieht.

### 4.4 Abgeleitet: was die Beschreibung nahelegt

Die meisten Datensätze tragen keine Gemeindenummer. Aber fast alle haben einen Titel und eine Beschreibung, und darin steht, worum es geht. Ein Sprachmodell zieht aus Titel, Beschreibung, Schlagworten und Spaltennamen je Datensatz fünf Arten von Angaben heraus:

**Wer extrahiert hat.** Für alle 15'934 Datensätze hat **Claude** (Anthropic, ein externer Dienst) die Angaben erzeugt. Das ging schneller als auf dem eigenen Server und schafft eine Referenz, an der sich später messen lässt, wie gut das selbst gehostete Modell **Gemma** dieselbe Aufgabe löst. Wer extrahiert hat, steht als Urheber an jeder einzelnen abgeleiteten Kante. Die Fragen im Portal beantwortet ausschliesslich Gemma.

| Achse | Frage | Beispiel |
| --- | --- | --- |
| **Ort** | Wo? | Stadt St. Gallen, Kanton Thurgau |
| **Raumebene** | In welcher Auflösung? | Gemeinde, Kanton, Messstation, Gebäude |
| **Beobachtetes Objekt** | Wovon handelt jede Zeile? | Wohnung, Fahrzeug, Hund, Messstation |
| **Kennzahl** | Was wird gemessen? | Leerwohnungsziffer, Stickstoffdioxid-Konzentration |
| **Begriff** | Worum geht es thematisch? | Energie, Mobilität, Tierhaltung |

Drei Regeln halten diese Ableitung prüfbar:

1. **Jede Angabe trägt einen wörtlichen Beleg.** Das Modell muss die Textstelle angeben, aus der es die Angabe gewonnen hat. Ob diese Textstelle tatsächlich im Quelltext steht, wird **deterministisch** geprüft, ohne Sprachmodell. Eine Angabe, deren Beleg nicht im Text steht, wird als solche markiert.
2. **Orte werden nachträglich abgeglichen.** Das Modell schlägt einen Ortsnamen vor; die Zuordnung zu einer Gemeinde oder einem Kanton erfolgt danach nach denselben Regeln wie in Kap. 4.3.
3. **Das Modell erfindet keine Zahlen.** Es benennt, was gemessen wird, nicht welche Werte. Werte kommen ausschliesslich aus den Tabellen.

### 4.5 Ähnlichkeit über Sprachgrenzen

Das Sprachmodell benennt Begriffe frei. Dadurch entstehen Varianten: «Leerwohnungsziffer», «Leerwohnungsbestand», «logements vacants». Der Prototyp führt sie über **Einbettungen** zusammen: Das Modell qwen3-embedding (ebenfalls selbst gehostet) bildet jeden Begriff auf einen Vektor ab, und Begriffe mit ähnlichen Vektoren werden als verwandt verbunden. Das wirkt auch über die Sprachgrenzen Deutsch, Französisch und Italienisch hinweg. Hier entstehen die überraschendsten Verbindungen, etwa zwischen einem Datensatz aus Freiburg auf Französisch und einem aus Zug auf Deutsch.

### 4.6 Was die Unschärfe kostet

Abgeleitete Kanten sind unschärfer als belegte und gemessene. Das ist kein Versehen, sondern der Preis dafür, dass sie alle 15'934 Datensätze erreichen und nicht nur die rund 530 Tabellen mit einer Gemeindenummer. Der Prototyp verschweigt diesen Preis nicht, sondern misst ihn: An einer Stichprobe abgeleiteter Kanten wird von Hand geprüft, wie viele stimmen.

[Trefferquote: Die Messung an einer Stichprobe steht noch aus]

> **Kernsatz.** Eine Verbindung ist nur so viel wert wie das Wissen darüber, woher sie kommt. Darum trägt jede Kante ihre Klasse, und jede abgeleitete Kante ihren Beleg.

---

## 5. Substrat, Protokoll, Sicht

### 5.1 Der Anschluss an die Doktrin

Die Doktrin trennt drei Dinge, die im Alltag in ein Wort fallen: das **Substrat**, in dem die Daten tatsächlich liegen, das **Protokoll**, mit dem sie sich nach aussen zeigen, und die **Sicht**, die sie für einen Zweck zusammenstellt (Doktrin Kap. 4.6 und 8). Dieselbe Trennung trägt den Prototyp:

| Ebene | Im Prototyp | Wie viele |
| --- | --- | --- |
| **Substrat** | die SQLite-Datenbanken, eine je Oberorganisation, dazu eine Datenbank der Verbindungen | eine je Organisation |
| **Protokoll** | RDF in den Serialisierungen Turtle und JSON-LD, aufgerufen über die URI eines Dings | austauschbar |
| **Sicht** | das Portal: Seite eines Datensatzes, eines Begriffs, eines Orts; der Graph-Explorer | beliebig viele |

### 5.2 RDF ist eine Projektion

Das RDF des Prototyps wird nicht gespeichert, sondern beim Aufruf aus dem Substrat erzeugt. Es ist im Sinne der Doktrin eine **Projektion**: eine Form, in der sich das interne Modell nach aussen zeigt, austauschbar und nicht Voraussetzung des Systems. Würde morgen ein anderes Format verlangt, käme eine zweite Projektion hinzu; das Substrat bliebe unberührt.

Eine Projektion verliert etwas. Die Doktrin verlangt, diesen Verlust zu **deklarieren** statt zu verschweigen:

| Im Substrat | In der Projektion | Verlust |
| --- | --- | --- |
| Tabelle mit allen Zeilen | Datensammlung mit Verweis auf die Quelldatei | Die Beobachtungen werden nicht als Tripel ausgegeben. |
| Spaltennamen, wie die Quelle sie liefert | nicht abgebildet | Spalten haben kein gemeinsames Vokabular. |
| Qualitätsbefunde (was nicht geladen werden konnte, und warum) | nicht abgebildet | nur im Portal sichtbar |
| Kantenklasse und Beleg | über PROV-O abgebildet | keiner |
| Ladezeitpunkt und Ladezustand | teilweise | Zeitstempel ja, Zwischenzustände nein |

Der erste Verlust ist der grösste und bewusst gewählt. Die Zeilen der 12'768 Tabellen ohne gemeinsames Vokabular als Tripel auszugeben, ergäbe sehr viel RDF und sehr wenig Verknüpfung: genau den Fall «Format ohne Idee» aus Kap. 2.2.

### 5.3 Herkunft und Urheberschaft

Für die Herkunft jeder Aussage verwendet der Prototyp **PROV-O**, den W3C-Standard für Provenienz:

- **prov:wasDerivedFrom** verbindet eine Tabelle mit ihrer Datensammlung und diese mit ihrem Datensatz. Jede Zahl lässt sich so bis zur Quelldatei zurückverfolgen.
- **prov:wasAttributedTo** hält fest, wer eine Kante gezogen hat: der **Katalog** (belegt), eine **Regel** (gemessen) oder das **Sprachmodell** (abgeleitet), jeweils mit Modellname und Zeitpunkt.

Damit ist die Unterscheidung von Mensch, Regel und KI, die die Doktrin für Records verlangt, auch hier prüfbar: Wer den Graphen liest, kann jede Kante nach ihrer Urheberschaft filtern.

### 5.4 Begriffe mit SKOS

Die abgeleiteten Begriffe werden mit **SKOS** beschrieben, dem W3C-Vokabular für Begriffssysteme. Ein Begriff ist ein **skos:Concept** mit einer bevorzugten Bezeichnung (**skos:prefLabel**) je Sprache. Verwandte Begriffe aus Kap. 4.5 sind über **skos:related** verbunden, nicht über eine Gleichheitsbeziehung: Ähnliche Vektoren beweisen keine Gleichheit.

> **Kernsatz.** Das Substrat bleibt, wie es ist. RDF ist die Form, in der es sich zeigt, mit benanntem Verlust und mit Herkunft bei jeder Kante.

---

## 6. Der URI-Raum

### 6.1 Das Muster

Nach dem ersten Prinzip braucht jedes Ding einen Namen. Der Prototyp vergibt Namen nach diesem Muster:

```
https://linkeddata.sim-research.ch/id/datensatz/{kennung}
https://linkeddata.sim-research.ch/id/datensammlung/{kennung}
https://linkeddata.sim-research.ch/id/organisation/{kennung}
https://linkeddata.sim-research.ch/id/begriff/{kennung}
https://linkeddata.sim-research.ch/id/ort/{kennung}
```

Jede dieser Adressen lässt sich im Browser aufrufen und zeigt eine Seite; dieselbe Adresse liefert einem Programm, das Turtle oder JSON-LD verlangt, die Projektion aus Kap. 5.

### 6.2 Deklaration: diese URIs sind nicht persistent

Diese Namen gehören einem Prototyp. Sie sind **nicht dauerhaft**: Die Domäne kann verschwinden, die Kennungen können sich bei einem Neuaufbau ändern, und niemand verpflichtet sich, sie in zehn Jahren noch aufzulösen. Für eine Demonstration ist das in Ordnung. Für den Betrieb wäre es ein Fehler, denn eine URI, die nicht mehr auflöst, ist schlimmer als keine: Sie verspricht eine Verbindung, die es nicht mehr gibt.

Dauerhafte Namen sind Sache derer, die für die Dinge zuständig sind: der publizierenden Stellen selbst und, für die gemeinsame Infrastruktur, der nationalen Linked-Data-Plattform LINDAS des Bundesarchivs. Wo es dort bereits dauerhafte Namen für Gemeinden, Kantone oder Organisationen gibt, sollte jede verknüpfende Lösung auf sie verweisen, statt eigene zu prägen. Der Prototyp ist so gebaut, dass seine eigenen Namen für Orte und Organisationen später durch solche Verweise ersetzt werden können.

> **Kernsatz.** Ein Name, der nicht auflöst, ist schlechter als keiner. Der Prototyp prägt Namen, um zu zeigen, was sie leisten; dauerhaft prägen müssen sie andere.

---

## 7. Was der Prototyp leistet und was nicht

| Leistet | Leistet nicht |
| --- | --- |
| Macht jeden verknüpften Datensatz über eine URI adressierbar, im Browser und als RDF (alle 15'934 Datensätze des Katalogs) | Persistente URIs (Kap. 6.2) |
| Verbindet Datensätze verschiedener Anbieter über gemeinsame Orte, Kennzahlen, Objekte und Begriffe | Eine geprüfte, kuratierte Ontologie der Verwaltungsdaten |
| Kennzeichnet jede Kante als belegt, gemessen oder abgeleitet, mit Urheberschaft | Gleiche Verlässlichkeit für alle Kanten |
| Belegt jede abgeleitete Angabe mit einer wörtlichen Textstelle und prüft sie deterministisch | Die Garantie, dass jede Ableitung inhaltlich stimmt |
| Misst die Trefferquote der Ableitung an einer Stichprobe | Eine vollständige Prüfung aller Kanten |
| Führt jede Zahl auf ihre Datensammlung zurück | Die Beobachtungen der Tabellen als Tripel (Kap. 5.2) |
| Gleicht Orte exakt gegen das amtliche Gemeindeverzeichnis ab | Unscharfe Zuordnung von Gemeindenamen |
| Beantwortet Fragen mit dem selbst gehosteten Modell Gemma; die Extraktion stammt von Claude und ist so gekennzeichnet | Ersatz für die Abstimmung zwischen den Anbietern |

Die letzte Zeile ist die wichtigste. Was der Prototyp abgeleitet hat, ist ein **Vorschlag**, wie die Daten zusammengehören könnten. Verbindlich wird eine solche Verbindung erst, wenn die zuständigen Stellen sie übernehmen: wenn der Kanton Zug und der Kanton Basel-Landschaft ihre Leerwohnungsziffer selbst auf denselben Begriff beziehen.

---

## 8. Analyse ohne Kuration

### 8.1 Die zwei Stufen der Doktrin

Die Doktrin unterscheidet zwei Stufen (Kap. 9.3): Zuerst wird **kuratiert**, also aus Rohdaten eine verlässliche, geprüfte Grundlage geschaffen. Erst dann wird **analysiert**. Die Reihenfolge ist dort nicht verhandelbar, denn Analyse auf unkuratiertem Bestand reproduziert das Chaos schneller und mit dem Anschein von Autorität.

### 8.2 Was dieser Prototyp bewusst anders macht

Der Prototyp überspringt die erste Stufe mit Absicht. Kein Mensch hat die Begriffe festgelegt, kein Mensch hat die abgeleiteten Kanten freigegeben. Er zeigt damit, was Stufe 2 ohne Stufe 1 heute schon leistet, und er macht sichtbar, wo sie danebenliegt.

Was er **findet**: Verbindungen, die niemand gezogen hat. Dieselbe Kennzahl bei mehreren Anbietern. Themen, die über Kantons- und Sprachgrenzen hinweg zusammenhängen. Datensätze, die über einen gemeinsamen Ort oder ein gemeinsames Objekt plötzlich nebeneinanderstehen.

Wo er **danebenliegt**: bei Begriffen, die gleich klingen und anderes meinen; bei Beschreibungen, die mehr versprechen als die Daten halten; bei Orten, die im Text genannt, aber nicht gemessen werden. Diese Fehler werden nicht versteckt. Sie stehen in der Stichprobe aus Kap. 4.6, und jede abgeleitete Kante zeigt ihren Beleg, damit jede Leserin und jeder Leser selbst urteilen kann.

### 8.3 Was daraus folgt

Der Prototyp ist kein Argument gegen Kuration, sondern eines für sie. Er zeigt, wie viel Verbindung in den offenen Daten der Schweiz steckt, und er zeigt mit gemessener Fehlerquote, wie viel davon ohne menschliche Prüfung unsicher bleibt. Beides zusammen ist die Begründung für den nächsten Schritt: gemeinsame Begriffe und dauerhafte Namen, festgelegt von denen, die für die Daten zuständig sind.

> **Kernsatz.** Der Prototyp zeigt, was Analyse ohne Kuration heute findet. Seine Fehlerquote zeigt, warum Kuration trotzdem nötig bleibt.

---

## Quellen

- Open Data Support (2013): *Trainingsmodul 1.2 — Einführung in Linked Data.* Im Auftrag der Europäischen Kommission, erstellt von PwC. data.europa.eu. Grundlage für die vier Prinzipien, das Tripel und die Unterscheidung von Open Data und Linked Data. Das Modul ist über zehn Jahre alt; seine Begriffe sind gültig, seine Beispiele und Initiativen zum Teil überholt.
- Berners-Lee, Tim (2006): *Linked Data — Design Issues.* w3.org/DesignIssues/LinkedData.html. Die Originalformulierung der vier Prinzipien.
- Ontotext: *What Are Linked Data and Linked Open Data?* ontotext.com/knowledgehub. **Herstellerbeitrag** eines Anbieters von Graphdatenbanken; die Begriffe entsprechen dem W3C-Verständnis, die Gewichtung ist produktnah.
- Diskussionspapier *Information Governance Doctrine*, Version 2.0, August 2026. Arbeitsdokument zur Konsultation. Übernommen: die Unterscheidung von Substrat, Protokoll und Sicht (Kap. 4.6, 8), der deklarierte Verlust, die Urheberschaft Mensch / Regel / KI und die Zweistufigkeit von Kuration und Analyse (Kap. 9.3).
- W3C-Empfehlungen: RDF, SPARQL, DCAT (Data Catalog Vocabulary), PROV-O (Provenance Ontology), SKOS (Simple Knowledge Organization System).
