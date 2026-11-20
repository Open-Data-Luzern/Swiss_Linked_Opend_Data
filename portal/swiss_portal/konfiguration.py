"""Pfade, Dienste und Zugangsdaten — der einzige Ort, an dem sie stehen.

Vorrang: Umgebungsvariable > portal/.env > Rueckfall hier. Auf dem Server
genuegt es, SWISS_OGD_DATEN auf das Verzeichnis mit den 85 Datenbanken zu
setzen; alles andere ergibt sich relativ zum Projekt.
"""

from __future__ import annotations

import os
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent
PROJEKT = PORTAL.parent


def _env_datei() -> dict[str, str]:
    datei = PORTAL / ".env"
    werte: dict[str, str] = {}
    if datei.exists():
        for zeile in datei.read_text(encoding="utf-8").splitlines():
            zeile = zeile.strip()
            if not zeile or zeile.startswith("#") or "=" not in zeile:
                continue
            k, v = zeile.split("=", 1)
            werte[k.strip()] = v.strip()
    return werte


_ENV = _env_datei()


def wert(name: str, rueckfall: str = "") -> str:
    v = os.environ.get(name)
    if v:
        return v
    return _ENV.get(name, rueckfall)


DATENBANKEN = Path(wert("SWISS_OGD_DATEN", str(PROJEKT / "Swiss_Open_Linked_Data" / "datenbanken")))
GRAPH = Path(wert("SWISS_OGD_GRAPH", str(PROJEKT / "Swiss_Open_Linked_Data" / "verknuepfung.sqlite")))
GEMEINDEVERZEICHNIS = PORTAL / "daten" / "gemeindeverzeichnis_2026-01-01.csv"
WEB = PORTAL / "web"

# Der URI-Raum des Prototyps. Nicht persistent — so steht es auch im Theorieteil.
URI_BASIS = wert("URI_BASIS", "https://linkeddata.sim-research.ch/id/")

# Sprachmodell: Gemma ueber den eigenen LiteLLM-Server (OpenAI-Form).
LLM_URL = wert("LLM_URL", "https://litellm.minimind.ch/v1/chat/completions")
LLM_MODELL = wert("LLM_MODELL", "google/gemma-4-31B-it-qat-w4a16-ct")
LLM_SCHLUESSEL = wert("SIM_AI_KEY")

# Einbettung: qwen3-embedding direkt auf spark5 (Ollama-Form), hinter Cloudflare Access.
EMB_URL = wert("EMB_URL", "https://spark5.minimind.ch/api/embed")
EMB_MODELL = wert("EMB_MODELL", "qwen3-embedding:8b")
EMB_KOPF = {
    "CF-Access-Client-Id": wert("SPARK5_CLIENT_ID"),
    "CF-Access-Client-Secret": wert("SPARK5_CLIENT_SECRET"),
}

# Cloudflare weist den Standard-User-Agent von urllib ab (Fehler 1010).
USER_AGENT = "swiss-ogd-portal/0.1"

PORTAL_BENUTZER = wert("PORTAL_BENUTZER")
PORTAL_PASSWORT = wert("PORTAL_PASSWORT")

# Begrenzung der KI-Anfragen je Adresse: so viele pro Stunde.
KI_ANFRAGEN_PRO_STUNDE = int(wert("KI_ANFRAGEN_PRO_STUNDE", "60"))
