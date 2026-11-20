"""Swiss Open Linked Data — je Oberorganisation auf opendata.swiss eine
SQLite-Datenbank mit Katalog und generisch geladenen Daten.

Die Module in der Reihenfolge des Datenflusses:

*   ``konfiguration`` — Endpunkte, Drosselung, Formate, Klartexte, Pfade
*   ``modelle``       — Organisation, Datensatz, Datensammlung, Befund
*   ``netz``          — HTTP mit Drosselung je Host und Wiederholung
*   ``katalog``       — Organisationsbaum und Ernte ueber die CKAN-API
*   ``tabellen``      — eine Datei in Zeilen und Spalten aufloesen
*   ``datenbank``     — Schema, Katalog schreiben, Datentabellen anlegen
*   ``aufbau``        — Orchestrierung und Befehlszeile
"""

__version__ = "1.0"
