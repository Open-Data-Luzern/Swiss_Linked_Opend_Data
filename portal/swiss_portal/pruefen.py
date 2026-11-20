"""Prueft Extraktionspakete gegen ihre Eingabe — deterministisch, ohne Modell.

    python -m swiss_portal.pruefen daten/extraktion/claude_voll_0007.jsonl
    python -m swiss_portal.pruefen --alle

Fuer jede Ausgabedatei <urheber>_<name>.jsonl wird die Eingabe
eingabe_<name>.jsonl gesucht. Geprueft wird:

  - jede Zeile ist gueltiges JSON mit den Feldern aus SCHEMA.md
  - jede datensatz_id der Eingabe kommt genau einmal vor, keine fremden
  - jeder Beleg steht woertlich (Kleinschreibung, Leerraum zusammengefasst)
    in Titel, Beschreibung, Schlagworten, Thema oder Spaltennamen; Ausnahme
    "zeitraum" im Feld zeit

Exit 0 = alles in Ordnung, 1 = Befunde (werden ausgegeben). Wer extrahiert,
ruft das nach jedem Paket auf und korrigiert, bis es 0 ergibt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import konfiguration as k

ORDNER = k.PORTAL / "daten" / "extraktion"
FELDER_LISTE = ("orte", "objekte", "kennzahlen", "konzepte")
ORT_ARTEN = {"gemeinde", "kanton", "bezirk", "region", "schweiz", "ausland", "andere"}


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").lower()).strip()


def quelle(e: dict) -> str:
    teile = [e["titel"], e["beschreibung"], " ".join(e["schlagworte"]), " ".join(e["thema"]), " ".join(e["spalten"])]
    return norm(" ".join(t for t in teile if t))


def lesen(pfad: Path) -> list[str]:
    return [z for z in pfad.read_text(encoding="utf-8").split("\n") if z.strip()]


def pruefe(ausgabe: Path) -> list[str]:
    name = ausgabe.stem.split("_", 1)[1]  # claude_voll_0007 -> voll_0007
    eingabe_pfad = ausgabe.with_name(f"eingabe_{name}.jsonl")
    if not eingabe_pfad.exists():
        return [f"{ausgabe.name}: keine Eingabe {eingabe_pfad.name}"]
    eingabe = {json.loads(z)["datensatz_id"]: json.loads(z) for z in lesen(eingabe_pfad)}
    befunde: list[str] = []
    gesehen: dict[str, int] = {}
    for nr, zeile in enumerate(lesen(ausgabe), 1):
        try:
            d = json.loads(zeile)
        except json.JSONDecodeError as f:
            befunde.append(f"Zeile {nr}: kein gueltiges JSON ({f})")
            continue
        i = d.get("datensatz_id")
        if i not in eingabe:
            befunde.append(f"Zeile {nr}: datensatz_id {i!r} steht nicht in der Eingabe")
            continue
        gesehen[i] = gesehen.get(i, 0) + 1
        q = quelle(eingabe[i])
        for feld in FELDER_LISTE:
            if not isinstance(d.get(feld, []), list):
                befunde.append(f"{i}: Feld {feld} ist keine Liste")
                continue
            for eintrag in d.get(feld, []):
                if feld == "orte":
                    if eintrag.get("art") not in ORT_ARTEN:
                        befunde.append(f"{i}: Ort {eintrag.get('name')!r} mit unbekannter art {eintrag.get('art')!r}")
                elif not str(eintrag.get("begriff", "")).strip():
                    befunde.append(f"{i}: {feld} ohne begriff")
                b = eintrag.get("beleg")
                if not b or norm(b) not in q:
                    befunde.append(f"{i}: {feld} {eintrag.get('begriff') or eintrag.get('name')!r} — Beleg nicht woertlich: {b!r}")
        zeit = d.get("zeit") or {}
        b = zeit.get("beleg")
        if (zeit.get("von") or zeit.get("bis")) and b and b != "zeitraum" and norm(b) not in q:
            befunde.append(f"{i}: zeit — Beleg nicht woertlich: {b!r}")
    for i in eingabe:
        if gesehen.get(i, 0) != 1:
            befunde.append(f"{i}: kommt {gesehen.get(i, 0)}-mal vor statt einmal")
    return befunde


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("dateien", nargs="*", type=Path)
    p.add_argument("--alle", action="store_true", help="alle claude_*.jsonl im Extraktionsordner")
    a = p.parse_args()
    dateien = sorted(ORDNER.glob("claude_*.jsonl")) if a.alle else a.dateien
    gesamt = 0
    for d in dateien:
        befunde = pruefe(d)
        gesamt += len(befunde)
        print(f"{d.name}: {'ok' if not befunde else f'{len(befunde)} Befunde'}")
        for b in befunde[:40]:
            print("   ", b)
    sys.exit(1 if gesamt else 0)


if __name__ == "__main__":
    main()
