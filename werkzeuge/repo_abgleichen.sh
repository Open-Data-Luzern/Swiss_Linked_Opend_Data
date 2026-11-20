#!/usr/bin/env bash
# Spiegelt den Code aus /srv/swiss_ogd nach /srv/swiss_ogd/repo (Git-Arbeitskopie
# von Open-Data-Luzern/Swiss_Linked_Opend_Data) und zeigt, was sich geaendert hat.
# Nie dabei: .env, Daten, Graph, Protokolle, Anleitungen, Schulung, Rohdaten.
#
#   werkzeuge/repo_abgleichen.sh                       # nur abgleichen und zeigen
#   werkzeuge/repo_abgleichen.sh "Kurze Beschreibung"  # zusaetzlich committen und pushen
set -euo pipefail
Q=/srv/swiss_ogd; Z=$Q/repo
X=(--delete --exclude .git --exclude .gitignore --exclude __pycache__ --exclude '*.egg-info' --exclude .pytest_cache)
rsync -a "${X[@]}" "$Q/README.md" "$Q/pyproject.toml" "$Q/src" "$Q/tests" "$Q/werkzeuge" "$Z/"
rsync -a "${X[@]}" --exclude .env --exclude .env.bak --exclude daten --exclude anleitungen --exclude schulung "$Q/portal" "$Z/"
cd "$Z"; git status --short
if [ $# -ge 1 ]; then
  git add -A
  git diff --cached --name-only | grep -E '(^|/)\.env$|\.sqlite' && { echo "Abbruch: Geheimnis oder Datenbank im Commit"; exit 1; }
  git commit -m "$1" && git push
fi
