"""Metadaten-Extraktion mit Gemma (Minimind) — fuer den grossen Lauf auf dem Server.

    python -m swiss_portal.extraktion --eingabe daten/extraktion/eingabe_teil_00.jsonl
    python -m swiss_portal.extraktion --eingabe daten/auswahl.jsonl --parallel 6
    python -m swiss_portal.extraktion --eingabe daten/auswahl.jsonl --nur 20   # Probe

Schreibt dieselbe Form wie der Probelauf (daten/extraktion/SCHEMA.md), Urheber
«gemma»: daten/extraktion/gemma_teil_<name>.jsonl. Fortsetzbar: Was in der
Ausgabe schon steht, wird uebersprungen. Ein Datensatz, dessen Antwort kein
gueltiges JSON ist, landet in <ausgabe>.fehler.jsonl und wird beim naechsten
Lauf erneut versucht.

Die Belege werden hier **nicht** korrigiert — das prueft der Graph beim Import
und markiert jeden Beleg, der nicht woertlich im Text steht. So bleibt der
Vergleich mit dem Probelauf (Urheber «claude») ehrlich.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import ki
from . import konfiguration as k

SCHEMA_DATEI = k.PORTAL / "daten" / "extraktion" / "SCHEMA.md"

SYSTEM = """Du extrahierst Metadaten aus der Katalogbeschreibung eines Datensatzes offener Schweizer Behoerdendaten.
Antworte ausschliesslich mit einem JSON-Objekt nach dieser Feldbeschreibung:

{schema}

Gib die datensatz_id unveraendert zurueck. Kein Text ausserhalb des JSON."""


def _system() -> str:
    text = SCHEMA_DATEI.read_text(encoding="utf-8")
    # nur Ausgabe, Felder und Regeln — die Eingabebeschreibung braucht das Modell nicht
    teil = text[text.find("## Ausgabe"):]
    return SYSTEM.format(schema=teil)


def _nutzer(e: dict) -> str:
    return json.dumps({x: e[x] for x in ("datensatz_id", "organisation", "titel", "beschreibung",
                                          "schlagworte", "thema", "zeitraum", "spalten")}, ensure_ascii=False)


def _lesen(pfad: Path) -> list[dict]:
    if not pfad.exists():
        return []
    return [json.loads(z) for z in pfad.read_text(encoding="utf-8").split("\n") if z.strip()]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--eingabe", required=True, type=Path)
    p.add_argument("--parallel", type=int, default=4, help="gleichzeitige Anfragen an vLLM")
    p.add_argument("--nur", type=int, default=0, help="nur die ersten N (Probe)")
    a = p.parse_args()

    eingabe = _lesen(a.eingabe)
    if a.nur:
        eingabe = eingabe[: a.nur]
    name = a.eingabe.stem.replace("eingabe_teil_", "").replace("eingabe_", "")
    ausgabe = k.PORTAL / "daten" / "extraktion" / f"gemma_teil_{name}.jsonl"
    fehlerdatei = ausgabe.with_suffix(".fehler.jsonl")
    fertig = {d["datensatz_id"] for d in _lesen(ausgabe)}
    offen = [e for e in eingabe if e["datensatz_id"] not in fertig]
    print(f"{len(eingabe)} in der Eingabe, {len(fertig)} schon fertig, {len(offen)} offen -> {ausgabe}")
    if not offen:
        return

    system = _system()
    sperre = threading.Lock()
    start = time.time()
    zaehler = {"ok": 0, "fehler": 0, "token": 0}

    def eins(e: dict) -> None:
        try:
            text, verbrauch = ki.chat(system, _nutzer(e), max_tokens=1200)
            d = ki.json_aus(text)
            d["datensatz_id"] = e["datensatz_id"]
            with sperre:
                with ausgabe.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(d, ensure_ascii=False) + "\n")
                zaehler["ok"] += 1
                zaehler["token"] += verbrauch.get("completion_tokens", 0)
        except (ki.KiFehler, ValueError) as fehler:
            with sperre:
                with fehlerdatei.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"datensatz_id": e["datensatz_id"], "fehler": str(fehler)}, ensure_ascii=False) + "\n")
                zaehler["fehler"] += 1

    with ThreadPoolExecutor(max_workers=a.parallel) as pool:
        auftraege = [pool.submit(eins, e) for e in offen]
        for i, _ in enumerate(as_completed(auftraege), 1):
            if i % 10 == 0 or i == len(offen):
                dauer = time.time() - start
                print(f"  {i}/{len(offen)}  ok {zaehler['ok']}  Fehler {zaehler['fehler']}  "
                      f"{dauer / i:.1f} s je Datensatz  {zaehler['token'] / max(dauer, 1):.0f} Token/s gesamt", flush=True)


if __name__ == "__main__":
    main()
