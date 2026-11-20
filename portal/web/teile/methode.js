// Methode: die Theorie in drei Bildern, danach der Text (inhalt/theorie.md).
"use strict";

function satzBild() {
  return `<svg viewBox="0 0 320 150" role="img" aria-label="Ein Satz: Subjekt Datensatz, Verb misst, Objekt Leerwohnungsziffer">
    <rect class="rahmen" x="6" y="50" width="104" height="48" rx="8"/><rect x="6" y="50" width="104" height="5" rx="2" fill="var(--datensatz)"/>
    <text x="16" y="72" font-size="11" style="fill:var(--text-2)">SUBJEKT</text><text x="16" y="89" font-weight="700">Datensatz</text>
    <line x1="114" y1="74" x2="196" y2="74" stroke="var(--abgeleitet)" stroke-width="2" stroke-dasharray="6 4"/><path d="M196,68 L206,74 L196,80 Z" fill="var(--abgeleitet)"/>
    <text x="160" y="64" text-anchor="middle">misst</text>
    <rect class="rahmen" x="210" y="50" width="104" height="48" rx="8"/><rect x="210" y="50" width="104" height="5" rx="2" fill="var(--begriff)"/>
    <text x="220" y="72" font-size="11" style="fill:var(--text-2)">OBJEKT</text><text x="220" y="89" font-weight="700">Leerwohnung</text>
    <text x="160" y="128" text-anchor="middle" font-size="12" style="fill:var(--text-2)">Subjekt · Verb · Objekt = ein Tripel</text></svg>`;
}

function brueckeBild() {
  return `<svg viewBox="0 0 320 150" role="img" aria-label="Zwei Datensätze verschiedener Anbieter nennen denselben Begriff und werden dadurch verbunden">
    <g class="bruecke-links"><rect class="rahmen" x="6" y="20" width="96" height="44" rx="8"/><rect x="6" y="20" width="96" height="5" rx="2" fill="var(--datensatz)"/><text x="14" y="50" font-weight="700">Kanton Zug</text></g>
    <g class="bruecke-rechts"><rect class="rahmen" x="218" y="20" width="96" height="44" rx="8"/><rect x="218" y="20" width="96" height="5" rx="2" fill="var(--datensatz)"/><text x="226" y="50" font-weight="700">Basel-Land</text></g>
    <g class="bruecke-mitte">
      <rect class="rahmen" x="102" y="98" width="116" height="40" rx="8"/><rect x="102" y="98" width="116" height="5" rx="2" fill="var(--begriff)"/>
      <text x="160" y="125" text-anchor="middle" font-weight="700">Leerwohnungsziffer</text>
      <line x1="80" y1="66" x2="132" y2="96" stroke="var(--abgeleitet)" stroke-width="2" stroke-dasharray="6 4"/>
      <line x1="240" y1="66" x2="188" y2="96" stroke="var(--abgeleitet)" stroke-width="2" stroke-dasharray="6 4"/></g></svg>`;
}

function klassenBild() {
  const zeile = (y, k, text, beispiel) => `<line x1="8" y1="${y}" x2="64" y2="${y}" stroke="var(--${k})" stroke-width="${k === "gemessen" ? 5 : 2}" ${k === "abgeleitet" ? 'stroke-dasharray="6 4"' : ""}/>
    <text x="76" y="${y - 4}" font-weight="700">${k}</text><text x="76" y="${y + 13}" font-size="12" style="fill:var(--text-2)">${text}</text>
    <text x="76" y="${y + 28}" font-size="12" style="fill:var(--text-2)">${beispiel}</text>`;
  return `<svg viewBox="0 0 320 170" role="img" aria-label="Drei Klassen von Verbindungen: belegt, gemessen, abgeleitet">
    ${zeile(22, "belegt", "steht im Katalog oder Verzeichnis", "Winterthur liegt in Kanton Zürich")}
    ${zeile(78, "gemessen", "aus den Daten geprüft", "Spalte «gemeinde_nr»: Gemeindenummern")}
    ${zeile(134, "abgeleitet", "KI aus dem Text, mit Beleg", "«Leerwohnungen nach Zimmerzahl»")}</svg>`;
}

async function methodeSeite() {
  const r = await fetch(new URL("inhalt/theorie.md", location.origin), { cache: "no-cache" });
  const md = await r.text();
  $inhalt.innerHTML = `<h1 class="frage-titel">Wie entstehen die Verbindungen?</h1>
    <div class="bilder3">
      <div class="bild"><h2>1 · Ein Satz</h2>${satzBild()}<p>Jede Verbindung ist ein Satz aus drei Teilen. Der Graph ist die Sammlung aller Sätze.</p></div>
      <div class="bild"><h2>2 · Eine Brücke</h2>${brueckeBild()}<p>Nennen zwei Sätze dasselbe Objekt, sind ihre Subjekte verbunden — auch über Anbieter hinweg.</p></div>
      <div class="bild"><h2>3 · Drei Klassen</h2>${klassenBild()}<p>Jede Verbindung trägt, woher sie kommt. Farbe und Linie sind überall gleich.</p></div>
    </div>
    <article class="theorie methode">${window.markdown(md)}</article>`;
}
