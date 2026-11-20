#!/usr/bin/env bash
# Uebertraegt das Projekt auf einen Linux-Server: Code, Kataloge, Protokolle und
# die 85 Datenbanken, eine Datei nach der anderen.
#
#   werkzeuge/uebertragen.sh BENUTZER@SERVER /srv/swiss_ogd            # alles
#   werkzeuge/uebertragen.sh BENUTZER@SERVER /srv/swiss_ogd --probe    # nur zeigen
#   werkzeuge/uebertragen.sh BENUTZER@SERVER /srv/swiss_ogd --nur elcom swissmedic
#   werkzeuge/uebertragen.sh BENUTZER@SERVER /srv/swiss_ogd --ohne-code
#   werkzeuge/uebertragen.sh BENUTZER@SERVER /srv/swiss_ogd --ohne-kompression
#
# Laeuft in Git Bash unter Windows und in jeder Linux-Shell. Auf dem Server
# braucht es nur bash, gzip, sha256sum und df.
#
# Warum Datei fuer Datei
# ----------------------
# 62 GB in einem Stueck: Bricht die Verbindung nach 50 GB ab, beginnt alles von
# vorn. Hier wird jede Datenbank einzeln uebertragen, auf dem Server zuerst
# unter "<name>.teil" abgelegt, dort gegen die Pruefsumme von hier geprueft und
# erst dann umbenannt. Neben jeder fertigen Datei liegt "<name>.sha256". Ein
# zweiter Aufruf ueberspringt jede Datei, deren Pruefsumme auf dem Server schon
# stimmt — ein Abbruch kostet hoechstens die Datei, die gerade unterwegs war.
#
# Komprimiert wird mit gzip -1 (schnell, nicht stark): SQLite mit viel Text
# schrumpft damit auf etwa ein Drittel. Im schnellen lokalen Netz kann gzip
# langsamer sein als die Leitung; dann --ohne-kompression.
#
# Was nicht mitgeht
# -----------------
# .venv (Windows-spezifisch, auf dem Server neu anlegen), __pycache__,
# .pytest_cache, das leere arbeit/ und die -wal/-shm-Dateien. Die WAL-Dateien
# muessen leer sein — sonst steht ein Teil der Daten noch dort und nicht in der
# .sqlite. Eine Datenbank mit nicht leerer WAL wird nicht uebertragen, sondern
# gemeldet: erst den laufenden Aufbau beenden.
#
# Anmeldung: Am besten mit SSH-Schluessel (ssh-copy-id). Mit Passwort fragt ssh
# einmal je Datenbank, also rund 90 Mal.
#
# Zum Ausprobieren ohne Server: SERVER "lokal" schreibt in ein lokales
# Verzeichnis und fuehrt die Serverbefehle mit bash aus.

set -u -o pipefail

PROJEKT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATEN_REL="Swiss_Open_Linked_Data/datenbanken"
DATEN="$PROJEKT/$DATEN_REL"
CACHE="$PROJEKT/Swiss_Open_Linked_Data/protokolle/uebertragung_pruefsummen.txt"
LOG="$PROJEKT/Swiss_Open_Linked_Data/protokolle/uebertragung_$(date +%Y-%m-%d_%H%M%S).log"

if [[ $# -lt 2 ]]; then
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
fi

SERVER="$1"; ZIEL="$2"; shift 2
PROBE=0; CODE=1; KOMPRIMIEREN=1; NUR=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --probe) PROBE=1 ;;
        --ohne-code) CODE=0 ;;
        --ohne-kompression) KOMPRIMIEREN=0 ;;
        --nur) shift; while [[ $# -gt 0 && "$1" != --* ]]; do NUR+=("$1"); shift; done; continue ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

ZIEL_Q="$(printf '%q' "$ZIEL")"
ZIEL_DATEN_Q="$(printf '%q' "$ZIEL/$DATEN_REL")"

# Fuehrt einen Befehl auf dem Server aus; stdin wird durchgereicht.
fern() {
    if [[ "$SERVER" == "lokal" ]]; then bash -c "$1"; else ssh "$SERVER" "$1"; fi
}

log() { echo "$*" | tee -a "$LOG"; }

mb() { awk -v b="$1" 'BEGIN { printf "%.1f", b / 1048576 }'; }

# Pruefsumme mit Zwischenspeicher: gerechnet wird nur, wenn sich Groesse oder
# Aenderungszeit seit dem letzten Mal geaendert haben.
pruefsumme() {
    local datei="$1" name groesse zeit treffer summe
    name="$(basename "$datei")"; groesse="$(stat -c %s "$datei")"; zeit="$(stat -c %Y "$datei")"
    treffer="$(awk -v n="$name" -v g="$groesse" -v z="$zeit" '$1 == n && $2 == g && $3 == z { print $4 }' "$CACHE" 2>/dev/null | tail -1)"
    if [[ -n "$treffer" ]]; then echo "$treffer"; return; fi
    summe="$(sha256sum "$datei" | cut -d' ' -f1)"
    echo "$name $groesse $zeit $summe" >> "$CACHE"
    echo "$summe"
}

mkdir -p "$(dirname "$LOG")"
log "Uebertragung $(date '+%d.%m.%Y %H:%M') nach $SERVER:$ZIEL"
[[ $PROBE -eq 1 ]] && log "PROBE — es wird nichts uebertragen."

# --- 1. Welche Datenbanken ------------------------------------------------------
DATEIEN=()
if [[ ${#NUR[@]} -gt 0 ]]; then
    for n in "${NUR[@]}"; do
        f="$DATEN/${n%.sqlite}.sqlite"
        [[ -f "$f" ]] || { log "Nicht gefunden: $f"; exit 1; }
        DATEIEN+=("$f")
    done
else
    while IFS= read -r f; do DATEIEN+=("$f"); done < <(ls -1Sr "$DATEN"/*.sqlite)
fi
# kleinste zuerst: die ersten Erfolge kommen nach Sekunden, nicht nach Stunden
mapfile -t DATEIEN < <(for f in "${DATEIEN[@]}"; do echo "$(stat -c %s "$f") $f"; done | sort -n | cut -d' ' -f2-)

# --- 2. Server erreichbar, was liegt schon dort ---------------------------------
log "Pruefe den Server ..."
FERTIG="$(fern "mkdir -p $ZIEL_DATEN_Q && cd $ZIEL_DATEN_Q && for s in *.sha256; do [ -f \"\$s\" ] && echo \"\${s%.sha256} \$(cat \"\$s\")\"; done; true")" \
    || { log "Server nicht erreichbar oder Zielverzeichnis nicht anlegbar."; exit 1; }
FREI="$(fern "df -P -B1 $ZIEL_Q | awk 'NR == 2 { print \$4 }'")"

# --- 3. Plan --------------------------------------------------------------------
PLAN=(); BEDARF=0; UEBERSPRUNGEN=0; BLOCKIERT=0
for f in "${DATEIEN[@]}"; do
    name="$(basename "$f")"
    wal="$f-wal"
    if [[ -s "$wal" ]]; then
        log "  BLOCKIERT  $name — die WAL-Datei ist nicht leer (laeuft ein Aufbau?)"
        BLOCKIERT=$((BLOCKIERT + 1)); continue
    fi
    summe="$(pruefsumme "$f")"
    if grep -qx "$name $summe" <<< "$FERTIG"; then
        UEBERSPRUNGEN=$((UEBERSPRUNGEN + 1)); continue
    fi
    PLAN+=("$f|$summe")
    BEDARF=$((BEDARF + $(stat -c %s "$f")))
done

log "Datenbanken: ${#DATEIEN[@]}, schon auf dem Server: $UEBERSPRUNGEN, blockiert: $BLOCKIERT, zu uebertragen: ${#PLAN[@]} ($(mb $BEDARF) MB)"
log "Frei auf dem Server: $(mb "${FREI:-0}") MB"
if [[ -n "$FREI" && "$FREI" -lt $((BEDARF + 1073741824)) ]]; then
    log "Zu wenig Platz auf dem Server (Bedarf plus 1 GB Reserve). Abbruch."
    exit 1
fi
if [[ $PROBE -eq 1 ]]; then
    for p in "${PLAN[@]}"; do log "  wuerde uebertragen: $(basename "${p%%|*}") ($(mb "$(stat -c %s "${p%%|*}")") MB)"; done
    exit 0
fi

# --- 4. Code, Kataloge, Protokolle ----------------------------------------------
if [[ $CODE -eq 1 ]]; then
    log "Uebertrage Code, Portal, Kataloge und Protokolle ..."
    # portal/.env bleibt hier: sie enthaelt Schluessel und wird auf dem Server
    # aus .env.example neu angelegt. Der Graph wird dort neu gebaut.
    ( cd "$PROJEKT" && tar czf - \
        --exclude='__pycache__' --exclude='.pytest_cache' \
        --exclude='portal/.env' --exclude='*.sqlite.neu' \
        README.md pyproject.toml src tests werkzeuge protokolle portal \
        Swiss_Open_Linked_Data/kataloge Swiss_Open_Linked_Data/protokolle ) \
      | fern "mkdir -p $ZIEL_Q/graph && tar xzf - -C $ZIEL_Q" \
      && log "  Code: ok" || { log "  Code: FEHLER"; exit 1; }
fi

# --- 5. Datenbanken, eine nach der anderen --------------------------------------
OK=0; FEHLER=(); i=0
for p in "${PLAN[@]}"; do
    i=$((i + 1))
    f="${p%%|*}"; summe="${p##*|}"; name="$(basename "$f")"
    groesse="$(stat -c %s "$f")"
    ziel_q="$(printf '%q' "$ZIEL/$DATEN_REL/$name")"
    start=$(date +%s)
    printf '[%d/%d] %s (%s MB) ... ' "$i" "${#PLAN[@]}" "$name" "$(mb "$groesse")" | tee -a "$LOG"

    # Auf dem Server: als .teil schreiben, pruefen, erst dann umbenennen.
    nachher="echo \"$summe  $ziel_q.teil\" | sha256sum -c --status && mv $ziel_q.teil $ziel_q && echo $summe > $ziel_q.sha256"
    if [[ $KOMPRIMIEREN -eq 1 ]]; then
        gzip -1 -c "$f" | fern "gunzip -c > $ziel_q.teil && $nachher"
    else
        fern "cat > $ziel_q.teil && $nachher" < "$f"
    fi
    status=$?
    dauer=$(( $(date +%s) - start )); [[ $dauer -lt 1 ]] && dauer=1

    if [[ $status -eq 0 ]]; then
        OK=$((OK + 1))
        log "ok, ${dauer}s, $(mb $((groesse / dauer))) MB/s"
    else
        FEHLER+=("$name")
        log "FEHLER (Pruefsumme oder Verbindung)"
        fern "rm -f $ziel_q.teil" >/dev/null 2>&1
    fi
done

# --- 6. Bilanz ------------------------------------------------------------------
log ""
log "Fertig: $OK uebertragen, $UEBERSPRUNGEN waren schon da, ${#FEHLER[@]} Fehler, $BLOCKIERT blockiert."
if [[ ${#FEHLER[@]} -gt 0 ]]; then
    log "Fehlgeschlagen: ${FEHLER[*]}"
    log "Einfach nochmals aufrufen — Fertiges wird uebersprungen."
    exit 1
fi
[[ $BLOCKIERT -gt 0 ]] && exit 1
log "Protokoll: $LOG"
exit 0
