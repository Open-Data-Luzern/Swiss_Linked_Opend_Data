"""Wege durch den Graphen — gemeinsam fuer das Portal und die Vorberechnung.

Der ganze Graph liegt als Nachbarschaftsliste im Speicher (rund 140'000
Kanten). Gesucht wird breitenweise; «Naben» (Anbieter, Katalogthemen,
Raumebenen, die Schweiz als Ganzes) sind ausgeschlossen, weil ueber sie fast
alles mit allem verbunden ist. «Hubs» sind Begriffe und Orte mit sehr vielen
Verbindungen (Gemeinde, Abstimmung, Kantone); sie lassen sich wahlweise meiden.
"""

from __future__ import annotations

import sqlite3
from collections import deque

NABEN_TYPEN = ("raumebene", "thema", "organisation")
# Gemessen am 18.11.2026: ueber 400 Verbindungen haben 17 Knoten, darunter
# «Gemeinde» (1714), «Abstimmung» (1409), «Politik» (861) und fuenf Kantone.
HUB_GRAD = 400


class Netz:
    def __init__(self, c: sqlite3.Connection):
        self.typ: dict[str, str] = {}
        self.label: dict[str, str] = {}
        for i, t, l in c.execute("select id, typ, label from knoten"):
            self.typ[i] = t
            self.label[i] = l
        self.nachbarn: dict[str, list] = {}
        for von, nach, art, klasse, beleg, urheber in c.execute(
                "select von, nach, art, klasse, beleg, urheber from kante"):
            e = (von, nach, art, klasse, beleg, urheber)
            self.nachbarn.setdefault(von, []).append((nach, e))
            self.nachbarn.setdefault(nach, []).append((von, e))
        self.grad = {i: sum(1 for b, _ in self.nachbarn.get(i, []) if self.typ.get(b) not in NABEN_TYPEN)
                     for i in self.typ}

    def nabe(self, b: str) -> bool:
        return self.typ.get(b) in NABEN_TYPEN or b == "ort/schweiz"

    def hub(self, b: str) -> bool:
        return self.typ.get(b) != "datensatz" and self.grad.get(b, 0) > HUB_GRAD

    def weg(self, von: str, nach: str, verboten: frozenset | set = frozenset(), hubs: bool = True) -> list | None:
        """Kuerzester Weg als Liste von Kanten-Tupeln, oder None."""
        if von == nach:
            return []
        vorher: dict[str, tuple | None] = {von: None}
        schlange = deque([von])
        while schlange:
            a = schlange.popleft()
            if a == nach:
                break
            for b, e in self.nachbarn.get(a, ()):
                if b in vorher or b in verboten:
                    continue
                if b != nach and (self.nabe(b) or (not hubs and self.hub(b))):
                    continue
                vorher[b] = (a, e)
                schlange.append(b)
        if nach not in vorher:
            return None
        schritte = []
        kn = nach
        while vorher[kn]:
            a, e = vorher[kn]
            schritte.append((a, kn, e))
            kn = a
        schritte.reverse()
        return schritte

    def wege(self, von: str, nach: str, k: int = 1, hubs: bool = True) -> list[list]:
        """Bis zu k Wege: der kuerzeste, dann Alternativen, deren Zwischenstationen
        sich nicht mit den bisherigen ueberschneiden (knotendisjunkt in der Mitte)."""
        erster = self.weg(von, nach, hubs=hubs)
        if erster is None:
            return []
        alle = [erster]
        verboten: set[str] = set()
        while len(alle) < k:
            for a, b, _ in alle[-1]:
                verboten.update(x for x in (a, b) if x not in (von, nach))
            if not verboten:
                break  # direkter Weg: keine Alternative ueber andere Stationen
            w = self.weg(von, nach, verboten=verboten, hubs=hubs)
            if w is None or len(w) > len(erster) + 2:
                break
            alle.append(w)
        return alle

    def als_json(self, schritte: list) -> dict:
        """Ein Weg in der Form, die die Oberflaeche erwartet."""
        if not schritte:
            return {"knoten": [], "schritte": []}
        ids = [schritte[0][0]] + [b for _, b, _ in schritte]
        return {
            "knoten": [{"id": i, "typ": self.typ[i], "label": self.label[i], "hub": self.hub(i)} for i in ids],
            "schritte": [{"von": a, "nach": b, "art": e[2], "klasse": e[3], "beleg": e[4], "urheber": e[5],
                          "richtung": "vor" if e[0] == a else "zurueck"} for a, b, e in schritte],
        }
