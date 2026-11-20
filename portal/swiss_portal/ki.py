"""Die beiden KI-Dienste: Gemma (Text) und qwen3-embedding (Vektoren).

Nur Standardbibliothek. Beide Dienste sind selbst gehostet (Minimind).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from . import konfiguration as k


class KiFehler(RuntimeError):
    pass


def _post(url: str, nutzlast: dict, kopf: dict, zeitlimit: int) -> dict:
    kopfzeilen = {
        "Content-Type": "application/json",
        "User-Agent": k.USER_AGENT,
        "Cache-Control": "no-cache, no-store, must-revalidate",
        **kopf,
    }
    anfrage = urllib.request.Request(url, data=json.dumps(nutzlast).encode("utf-8"), headers=kopfzeilen)
    letzter = None
    for versuch in range(3):
        try:
            with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
                return json.load(antwort)
        except urllib.error.HTTPError as e:
            letzter = f"HTTP {e.code}: {e.read()[:200]!r}"
            if e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            letzter = str(e)
        time.sleep(2 * (versuch + 1))
    raise KiFehler(letzter or "unbekannter Fehler")


def chat(system: str, nutzer: str, max_tokens: int = 900, temperatur: float = 0.0) -> tuple[str, dict]:
    """Eine Antwort von Gemma. Gibt Text und Verbrauch zurueck."""
    nutzlast = {
        "model": k.LLM_MODELL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": nutzer}],
        "max_tokens": max_tokens,
        "temperature": temperatur,
    }
    d = _post(k.LLM_URL, nutzlast, {"Authorization": f"Bearer {k.LLM_SCHLUESSEL}"}, 300)
    return d["choices"][0]["message"]["content"] or "", d.get("usage", {})


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def json_aus(text: str) -> dict:
    """Holt das JSON-Objekt aus einer Modellantwort (auch aus ```json-Bloecken)."""
    treffer = _JSON_BLOCK.search(text)
    if not treffer:
        raise ValueError("kein JSON in der Antwort")
    return json.loads(treffer.group(0))


def einbetten(texte: list[str], stapel: int = 32) -> list[list[float]]:
    """Vektoren fuer kurze Texte (Begriffe). Lange Karten brauchen kleinere Stapel."""
    vektoren: list[list[float]] = []
    for i in range(0, len(texte), stapel):
        teil = texte[i : i + stapel]
        d = _post(k.EMB_URL, {"model": k.EMB_MODELL, "input": teil}, k.EMB_KOPF, 300)
        vektoren.extend(d["embeddings"])
    return vektoren
