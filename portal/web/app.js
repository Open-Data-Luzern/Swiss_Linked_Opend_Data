// Swiss Open Linked Data — Cockpit. Hash-Router, kein Build-Schritt.
// Kern: Hilfen, Router, Kopfsuche, Cockpit, Verbinden, Knoten, Graph, Fragen.
// Schwere Teile (Diagramme, Karte, Entdecken, Methode) liegen in teile/ und
// werden erst geladen, wenn eine Seite sie braucht.
"use strict";

const $inhalt = document.getElementById("inhalt");

// ---------- Hilfen ----------------------------------------------------------

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// Schweizer Tausendertrenner mit geradem Apostroph: 1'234
const zahl = (n, stellen = 0) => (n == null || Number.isNaN(+n) ? "–" : Number(n).toLocaleString("de-CH", { maximumFractionDigits: stellen }).replace(/’/g, "'"));
const prozent = (a, b) => (b ? Math.round((100 * a) / b) : 0);

async function api(pfad, optionen) {
  // Immer gegen location.origin: Enthaelt die Seitenadresse Zugangsdaten
  // (http://benutzer:pw@host/), verweigert fetch relative Pfade.
  const r = await fetch(new URL(pfad, location.origin), optionen);
  const text = await r.text();
  let daten;
  try { daten = JSON.parse(text); } catch { daten = { fehler: text }; }
  if (!r.ok) throw new Error(daten.detail || daten.fehler || `HTTP ${r.status}`);
  return daten;
}
const post = (pfad, nutzlast) => api(pfad, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(nutzlast) });

const knotenHref = (id) => `#/knoten/${encodeURI(id)}`;
const knotenLink = (id, label) => `<a href="${knotenHref(id)}">${esc(label)}</a>`;

const TYP_NAME = {
  datensatz: "Datensatz", organisation: "Anbieter", thema: "Thema", ort: "Ort",
  begriff: "Begriff", raumebene: "Raumebene", schluessel: "Schlüssel",
};
const ART_NAME = {
  publiziert_von: "publiziert von", thema: "Thema", ort: "Ort", objekt: "beobachtet",
  kennzahl: "misst", konzept: "handelt von", raumebene: "Raumebene", liegt_in: "liegt in",
  aehnlich: "ähnlich", enthaelt_schluessel: "Schlüssel in den Daten",
};
const ART_EINGEHEND = {
  publiziert_von: "Publizierte Datensätze", thema: "Datensätze mit diesem Thema", ort: "Datensätze zu diesem Ort",
  objekt: "Datensätze, die dies beobachten", kennzahl: "Datensätze, die dies messen", konzept: "Datensätze zu diesem Thema",
  raumebene: "Datensätze auf dieser Ebene", liegt_in: "Enthält", aehnlich: "Ähnlicher Begriff",
  enthaelt_schluessel: "Datensätze mit diesem Schlüssel",
};
const ART_AUSGEHEND = {
  publiziert_von: "Anbieter", thema: "Thema", ort: "Orte", objekt: "Beobachtet", kennzahl: "Misst", konzept: "Handelt von",
  raumebene: "Raumebene", liegt_in: "Liegt in", aehnlich: "Ähnlicher Begriff", enthaelt_schluessel: "Schlüssel in den Daten",
};
const KLASSEN = ["belegt", "gemessen", "abgeleitet"];
const KLASSE_TEXT = {
  belegt: "steht im Katalog oder im Gemeindeverzeichnis",
  gemessen: "aus den Daten selbst geprüft",
  abgeleitet: "von der KI aus dem Text, mit Beleg",
};
const klasseMarke = (k) => `<span class="marke-klasse ${esc(k)}">${esc(k)}</span>`;
const legendeKlassen = () => `<div class="legende" aria-label="Legende der Verbindungen">
  ${KLASSEN.map((k) => `<span><i class="strich ${k}" aria-hidden="true"></i> <b>${k}</b> — ${KLASSE_TEXT[k]}</span>`).join("")}</div>`;
const legendeTypen = () => `<div class="legende" aria-label="Legende der Knoten">
  <span><i class="punkt begriff"></i> Begriff</span><span><i class="punkt ort"></i> Ort</span>
  <span><i class="punkt datensatz"></i> Datensatz</span><span><i class="punkt andere"></i> Schlüssel, Thema</span></div>`;

function laden(text = "Lädt …") { $inhalt.innerHTML = `<p class="laden" role="status">${esc(text)}</p>`; }
function fehler(e) { $inhalt.innerHTML = `<p class="fehler" role="alert">${esc(e.message || e)}</p>`; }
const farbe = (name) => getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim();

// Teile erst bei Bedarf laden (klassische Skripte; ihre Funktionen sind global).
const _geladen = {};
function brauche(...teile) {
  return Promise.all(teile.map((t) => (_geladen[t] ||= new Promise((ok, nein) => {
    const s = document.createElement("script");
    s.src = t.endsWith(".js") ? t : `teile/${t}.js`;
    s.onload = ok;
    s.onerror = () => nein(new Error(`${t} konnte nicht geladen werden`));
    document.head.appendChild(s);
  }))));
}

// Tooltip in einer Grafikfläche
function tipp(huelle) {
  let t = huelle.querySelector(".dg-tipp");
  if (!t) { t = document.createElement("div"); t.className = "dg-tipp"; t.setAttribute("role", "tooltip"); huelle.appendChild(t); }
  return {
    zeigen: (ev, html) => {
      t.innerHTML = html; t.style.display = "block";
      const r = huelle.getBoundingClientRect();
      const x = ev.clientX - r.left + 12, breite = t.offsetWidth;
      t.style.left = Math.min(x, r.width - breite - 4) + "px";
      t.style.top = ev.clientY - r.top - 12 + "px";
    },
    weg: () => { t.style.display = "none"; },
  };
}

// Jede Grafik: Titel, Fläche, Umschalter «Als Tabelle», darunter höchstens der Stand.
function grafik(ziel, { titel, ebene = "h2", zeichnen, tabelle, stand, rechts = "" }) {
  ziel.innerHTML = `<figure class="grafik">
    <div class="grafik-kopf">${titel ? `<${ebene}>${titel}</${ebene}>` : "<span></span>"}
      <span>${rechts}<button type="button" class="grafik-schalter" aria-pressed="false">Als Tabelle</button></span></div>
    <div class="grafik-flaeche"></div><div class="grafik-tabelle" hidden></div>
    ${stand ? `<figcaption class="stand">${stand}</figcaption>` : ""}</figure>`;
  const flaeche = ziel.querySelector(".grafik-flaeche"), tab = ziel.querySelector(".grafik-tabelle");
  const knopf = ziel.querySelector(".grafik-schalter");
  knopf.addEventListener("click", () => {
    const alsTabelle = tab.hidden;
    if (alsTabelle && !tab.innerHTML) tab.innerHTML = tabelle();
    tab.hidden = !alsTabelle; flaeche.hidden = alsTabelle;
    knopf.textContent = alsTabelle ? "Als Grafik" : "Als Tabelle";
    knopf.setAttribute("aria-pressed", String(alsTabelle));
  });
  zeichnen(flaeche);
  return flaeche;
}

function tabelleHtml(spalten, zeilen, zahlSpalten = []) {
  return `<div class="tabelle-huelle"><table class="daten"><thead><tr>${spalten.map((s) => `<th scope="col">${esc(s)}</th>`).join("")}</tr></thead>
    <tbody>${zeilen.map((z) => `<tr>${z.map((v, i) => `<td class="${zahlSpalten.includes(i) ? "zahl-zelle" : ""}">${v}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

// ---------- Router ---------------------------------------------------------

const ROUTEN = [
  [/^$/, cockpit, "Cockpit"], [/^entdecken$/, entdecken, "Entdecken"], [/^frage$/, frage, "Fragen"],
  [/^pfad$/, verbinden, "Verbinden"], [/^methode$/, methode, "Methode"], [/^theorie$/, methode, "Methode"],
  [/^knoten\/(.+)$/, knotenSeite, "Knoten"], [/^graph\/(.+)$/, graphSeite, "Umgebung"],
  [/^vergleich$/, () => { location.replace("#/entdecken?reiter=vergleichen"); return Promise.resolve(); }, "Vergleichen"],
];

function route() {
  const roh = location.hash.replace(/^#\/?/, "");
  const [pfad, abfrage] = roh.split("?");
  const parameter = new URLSearchParams(abfrage || "");
  const erstes = pfad.split("/")[0];
  document.querySelectorAll(".haupt a").forEach((a) => {
    const aktiv = a.dataset.route === erstes || (erstes === "theorie" && a.dataset.route === "methode");
    a.classList.toggle("aktiv", aktiv);
    if (aktiv) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  for (const [muster, seite, name] of ROUTEN) {
    const m = muster.exec(decodeURI(pfad));
    if (m) {
      document.title = `${name} · Swiss Open Linked Data`;
      window.scrollTo(0, 0);
      seite(m[1], parameter).catch(fehler);
      return;
    }
  }
  $inhalt.innerHTML = `<p class="fehler">Diese Seite gibt es nicht. <a href="#/">Zum Cockpit</a></p>`;
}
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => { route(); kopfsucheVerdrahten(); });

// ---------- Suche mit Vorschlägen (Kopf und Auswahlfelder) --------------------

const GRUPPEN = [["begriff", "Begriffe"], ["ort", "Orte"], ["datensatz", "Datensätze"]];

// Verdrahtet ein Eingabefeld mit gruppierten Vorschlägen. beiWahl(treffer) wird
// beim Klick oder mit Enter aufgerufen.
function vorschlaegeVerdrahten(feld, liste, beiWahl) {
  let zeit, eintraege = [], aktiv = -1, anfrageNr = 0;
  const schliessen = () => { liste.hidden = true; feld.setAttribute("aria-expanded", "false"); aktiv = -1; };
  const markieren = (i) => {
    aktiv = i;
    liste.querySelectorAll(".vorschlag").forEach((el, j) => el.setAttribute("aria-selected", String(j === i)));
    const el = liste.querySelectorAll(".vorschlag")[i];
    if (el) { feld.setAttribute("aria-activedescendant", el.id); el.scrollIntoView({ block: "nearest" }); }
  };
  feld.addEventListener("input", () => {
    clearTimeout(zeit);
    const q = feld.value.trim();
    if (q.length < 2) { schliessen(); return; }
    zeit = setTimeout(async () => {
      const nr = ++anfrageNr;
      let g;
      try { g = await api(`/api/suche?gruppiert=1&q=${encodeURIComponent(q)}`); } catch { return; }
      if (nr !== anfrageNr) return;
      eintraege = [];
      let html = "";
      for (const [typ, name] of GRUPPEN) {
        if (!g[typ]?.length) continue;
        html += `<div class="vorschlag-gruppe" role="presentation">${name}</div>`;
        for (const t of g[typ]) {
          const i = eintraege.push(t) - 1;
          html += `<a class="vorschlag" role="option" id="${feld.id}-v${i}" aria-selected="false" data-i="${i}" href="${knotenHref(t.id)}">
            <i class="punkt ${t.typ}" aria-hidden="true"></i><span>${esc(t.label)}</span><small>${zahl(t.grad)} Verb.</small></a>`;
        }
      }
      liste.innerHTML = html || `<div class="vorschlag-leer">Nichts gefunden zu «${esc(q)}».</div>`;
      liste.hidden = false; feld.setAttribute("aria-expanded", "true"); aktiv = -1;
    }, 160);
  });
  feld.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" && eintraege.length) { ev.preventDefault(); markieren(Math.min(aktiv + 1, eintraege.length - 1)); }
    else if (ev.key === "ArrowUp" && eintraege.length) { ev.preventDefault(); markieren(Math.max(aktiv - 1, 0)); }
    else if (ev.key === "Escape") schliessen();
    else if (ev.key === "Enter") {
      ev.preventDefault();
      const t = eintraege[aktiv >= 0 ? aktiv : 0];
      if (t && !liste.hidden) { schliessen(); beiWahl(t); }
    }
  });
  liste.addEventListener("click", (ev) => {
    const a = ev.target.closest(".vorschlag");
    if (!a) return;
    ev.preventDefault();
    schliessen();
    beiWahl(eintraege[+a.dataset.i]);
  });
  feld.addEventListener("blur", () => setTimeout(schliessen, 150));
}

function kopfsucheVerdrahten() {
  const feld = document.getElementById("kopfsuche");
  vorschlaegeVerdrahten(feld, document.getElementById("kopfvorschlaege"), (t) => {
    feld.value = "";
    location.hash = knotenHref(t.id);
  });
}

// ---------- Kette (ein Weg als Folge von Knoten-Karten) -----------------------

function kette(weg, { klein = false, senkrecht = false } = {}) {
  let html = `<div class="kette${klein ? " klein" : ""}${senkrecht ? " senkrecht" : ""}">`;
  weg.knoten.forEach((k, i) => {
    html += `<a class="glied ${esc(k.typ)}" href="${knotenHref(k.id)}"><span class="typ">${esc(TYP_NAME[k.typ] || k.typ)}</span>
      <span class="name">${esc(k.label)}</span>${k.hub && !klein ? `<span class="hub">Hub</span>` : ""}</a>`;
    const s = weg.schritte[i];
    if (s) {
      const art = ART_NAME[s.art] || s.art;
      html += `<span class="pfeil ${esc(s.klasse)}" role="img" tabindex="${klein ? -1 : 0}" aria-label="${esc(`${s.klasse}: ${art}${s.beleg ? ", Beleg: " + s.beleg : ""}`)}">
        <span class="art" aria-hidden="true">${esc(art)}</span>${klein ? "" : `<span class="zitat">${klasseMarke(s.klasse)} ${esc(art)}${s.beleg ? `<br>«${esc(s.beleg)}»` : `<br>${esc(KLASSE_TEXT[s.klasse])}`}</span>`}</span>`;
    }
  });
  return html + "</div>";
}

function vertrauen(weg) {
  const n = weg.schritte.length;
  const z = Object.fromEntries(KLASSEN.map((k) => [k, weg.schritte.filter((s) => s.klasse === k).length]));
  const ki = prozent(z.abgeleitet, n);
  return `<div class="vertrauen"><span class="balken" role="img" aria-label="${KLASSEN.map((k) => `${k} ${z[k]}`).join(", ")}">
    ${KLASSEN.filter((k) => z[k]).map((k) => `<i class="k-${k}" style="flex:${z[k]}"></i>`).join("")}</span>
    <span>${ki === 0 ? "Dieser Weg stützt sich nur auf belegte und gemessene Verbindungen." : `Dieser Weg stützt sich zu ${ki} % auf KI-Ableitungen.`}</span></div>`;
}

// Mini-Grafik eines Wegs für Karten: Punkte nach Knotentyp, Linien nach Kantenklasse.
function miniKette(weg) {
  const n = weg.knoten.length, b = 260, h = 28, x = (i) => 10 + (i * (b - 20)) / (n - 1);
  const linie = { belegt: ["belegt", 2, ""], gemessen: ["gemessen", 4, ""], abgeleitet: ["abgeleitet", 2, "5 4"] };
  const typ = (t) => ({ ort: "ort", begriff: "begriff", datensatz: "datensatz" }[t] || "andere");
  return `<svg viewBox="0 0 ${b} ${h}" role="img" aria-label="${esc(weg.knoten.map((k) => k.label).join(" → "))}" style="width:100%;height:auto;display:block">
    ${weg.schritte.map((s, i) => { const [f, w, d] = linie[s.klasse]; return `<line x1="${x(i)}" y1="14" x2="${x(i + 1)}" y2="14" stroke="var(--${f})" stroke-width="${w}" ${d ? `stroke-dasharray="${d}"` : ""}/>`; }).join("")}
    ${weg.knoten.map((k, i) => `<circle cx="${x(i)}" cy="14" r="${i === 0 || i === n - 1 ? 8 : 6}" fill="var(--${typ(k.typ)})" stroke="var(--karte)" stroke-width="2"/>`).join("")}</svg>
    <p>über ${weg.knoten.slice(1, -1).map((k) => esc(k.label.length > 40 ? k.label.slice(0, 38) + "…" : k.label)).join(" · ")}</p>`;
}

// ---------- Cockpit ---------------------------------------------------------

async function cockpit() {
  $inhalt.innerHTML = `
    <h1 class="frage-titel">Was steckt in den offenen Daten der Schweiz?</h1>
    <p class="unter">Datensätze von Bund, Kantonen und Gemeinden, verknüpft über gemeinsame Orte, Kennzahlen und Begriffe.</p>
    <div class="raster12" id="kacheln"><div class="tafel s12 laden-block"></div></div>
    <div class="raster12">
      <section class="tafel s8" id="herkunft" aria-labelledby="h-herkunft"></section>
      <section class="tafel s4" id="wegdestages" aria-labelledby="h-weg"></section>
    </div>
    <div class="raster12"><section class="tafel s12" id="karte"><div class="laden-block" style="min-height:420px"></div></section></div>
    <div class="raster12"><section class="tafel s12" id="sprache"></section></div>
    <div class="raster12" id="einstiege"></div>`;
  const c = await api("/api/cockpit");
  const b = c.bestand, kanten = KLASSEN.reduce((a, k) => a + (c.klassen[k] || 0), 0);
  const knoten = Object.values(c.knoten).reduce((a, x) => a + x, 0);
  const verlauf = (feld) => c.laeufe.map((l) => l[feld]);
  const kacheln = [
    { wert: b.datensaetze, name: `Datensätze von ${zahl(b.organisationen)} Anbietern, ${zahl(c.knoten.datensatz)} verknüpft`, reihe: verlauf("datensaetze"), href: "#/entdecken" },
    { wert: b.tabellen, name: `Tabellen mit ${zahl(b.zeilen)} Zeilen`, reihe: null, href: "#/entdecken?reiter=vergleichen" },
    { wert: knoten, name: `Knoten: ${zahl(c.knoten.begriff)} Begriffe, ${zahl(c.knoten.ort)} Orte`, reihe: verlauf("knoten"), href: "#/methode" },
    { wert: kanten, name: "Verbindungen zwischen den Knoten", reihe: verlauf("kanten"), href: "#/entdecken" },
  ];
  document.getElementById("kacheln").innerHTML = kacheln.map((k) => `<a class="tafel kachel s3" href="${k.href}">
      <div class="wert">${zahl(k.wert)}</div><div class="name">${esc(k.name)}</div>${k.reihe && k.reihe.length > 1 ? funke(k.reihe) : ""}</a>`).join("");

  // Herkunft der Verbindungen
  const ziele = { belegt: "#/methode", gemessen: "#/entdecken?reiter=schluessel", abgeleitet: "#/entdecken?reiter=wege" };
  document.getElementById("herkunft").innerHTML = `<div class="tafel-kopf"><h2 id="h-herkunft">Woher stammen die Verbindungen?</h2></div>
    <div class="herkunft-balken" role="img" aria-label="${KLASSEN.map((k) => `${k} ${prozent(c.klassen[k], kanten)} Prozent`).join(", ")}">
      ${KLASSEN.map((k) => `<span class="k-${k}" style="flex:${c.klassen[k] || 0}" title="${k}: ${zahl(c.klassen[k])}"></span>`).join("")}</div>
    <div class="herkunft-legende">${KLASSEN.map((k) => `<a href="${ziele[k]}"><i class="strich ${k}" aria-hidden="true"></i> <b>${prozent(c.klassen[k], kanten) || "<1"} %</b> ${k} · ${zahl(c.klassen[k])}</a>`).join("")}</div>
    <p class="leise" style="margin:16px 0 0">Die Überraschungen entstehen im orangen Teil, die Belastbarkeit im grünen.</p>`;

  wegDesTages();
  begriffeBalken(document.getElementById("sprache"), c.begriffe);
  document.getElementById("einstiege").innerHTML = `
    <form class="tafel karte-l einstieg s4" id="e-frage"><h3><label for="e-frage-feld">Frag die Daten</label></h3>
      <p>Eine Frage in Alltagssprache; die Antwort zeigt passende Datensätze und eine Grafik.</p>
      <input type="text" id="e-frage-feld" placeholder="z. B. Wo wird Lärm gemessen?"></form>
    <div class="tafel karte-l einstieg s4"><h3>Finde einen Weg</h3><p>Wie hängen Hund und Steuer zusammen? Oder Biber und Kirche?</p>
      <p><a class="knopf" href="#/pfad?von=begriff/hund&nach=begriff/steuer">Weg ansehen</a> <button type="button" class="zweit" id="e-zufall">Überrasch mich</button></p></div>
    <form class="tafel karte-l einstieg s4" id="e-gemeinde"><h3><label for="e-gemeinde-feld">Alles zu meiner Gemeinde</label></h3>
      <p>Was Bund, Kanton und Gemeinde über einen Ort publizieren.</p>
      <input type="text" id="e-gemeinde-feld" list="gemeindeliste" placeholder="Gemeinde wählen …" autocomplete="off"><datalist id="gemeindeliste"></datalist></form>`;
  document.getElementById("e-frage").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = document.getElementById("e-frage-feld").value.trim();
    if (q) location.hash = `#/frage?q=${encodeURIComponent(q)}`;
  });
  document.getElementById("e-zufall").addEventListener("click", ueberraschMich);

  // Karte zuletzt: TopoJSON (rund 380 kB) erst nach dem Rest
  await brauche("karte");
  const k = await gemeindeKarteDaten();
  const liste = document.getElementById("gemeindeliste");
  liste.innerHTML = k.daten.gemeinden.map((g) => `<option value="${esc(g.name)}">`).join("");
  const gemeindeFeld = document.getElementById("e-gemeinde-feld");
  const gemeindeOeffnen = () => {
    const g = k.daten.gemeinden.find((x) => x.name.toLowerCase() === gemeindeFeld.value.trim().toLowerCase());
    if (g) location.hash = gemeindeZiel(g);
  };
  gemeindeFeld.addEventListener("change", gemeindeOeffnen);
  document.getElementById("e-gemeinde").addEventListener("submit", (ev) => { ev.preventDefault(); gemeindeOeffnen(); });
  gemeindeKarte(document.getElementById("karte"), k, { titel: "Wo sind die Daten verortet?", stand: `Stand ${standDatum(c.stand)} · Grenzen © swisstopo (swissBOUNDARIES3D, 1.1.2026)` });
}

const standDatum = (s) => (s ? s.slice(0, 10).split("-").reverse().join(".") : "–");

function funke(reihe) {
  const b = 200, h = 32, n = reihe.length;
  const min = Math.min(...reihe), max = Math.max(...reihe);
  const x = (i) => 4 + (i * (b - 8)) / (n - 1), y = (v) => (max === min ? h / 2 : h - 4 - ((v - min) * (h - 8)) / (max - min));
  const d = reihe.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  return `<svg viewBox="0 0 ${b} ${h}" preserveAspectRatio="none" role="img" aria-label="Verlauf über ${n} Graph-Läufe: ${reihe.map((v) => zahl(v)).join(", ")}">
    <path class="funke" d="${d}" vector-effect="non-scaling-stroke"/><circle class="funke-punkt" cx="${x(n - 1)}" cy="${y(reihe[n - 1])}" r="3"/></svg>`;
}

async function wegDesTages(neu = false) {
  const ziel = document.getElementById("wegdestages");
  if (!ziel) return;
  const gesehen = gesehenListe();
  try {
    const w = await api(`/api/zufallsweg?ohne=${gesehen.join(",")}`);
    if (neu) gesehenMerken(w.nr);
    const a = w.knoten[0], z = w.knoten[w.knoten.length - 1];
    ziel.innerHTML = `<div class="tafel-kopf"><h2 id="h-weg">Weg des Tages</h2></div>
      <p class="leise" style="margin:0">${esc(a.label)} → ${esc(z.label)} in ${w.knoten.length} Stationen</p>
      ${kette(w, { klein: true, senkrecht: true })}
      <div class="werkzeuge"><a class="knopf" href="#/pfad?von=${encodeURIComponent(a.id)}&nach=${encodeURIComponent(z.id)}">Weg öffnen</a>
      <button type="button" class="zweit" id="nocheiner">Noch einer</button></div>`;
    document.getElementById("nocheiner").addEventListener("click", () => wegDesTages(true));
  } catch (e) { ziel.innerHTML = `<p class="fehler">${esc(e.message)}</p>`; }
}

function gesehenListe() { try { return JSON.parse(sessionStorage.getItem("gesehen") || "[]"); } catch { return []; } }
function gesehenMerken(nr) {
  let l = gesehenListe().filter((x) => x !== nr);
  l.push(nr);
  if (l.length >= 50) l = [nr];
  try { sessionStorage.setItem("gesehen", JSON.stringify(l)); } catch { /* privat: dann eben ohne Gedächtnis */ }
}
async function ueberraschMich() {
  const w = await api(`/api/zufallsweg?ohne=${gesehenListe().join(",")}`);
  gesehenMerken(w.nr);
  location.hash = `#/pfad?von=${encodeURIComponent(w.knoten[0].id)}&nach=${encodeURIComponent(w.knoten[w.knoten.length - 1].id)}`;
}

function begriffeBalken(ziel, begriffe) {
  grafik(ziel, {
    titel: "Welche Begriffe teilen die meisten Anbieter?",
    stand: "Anzahl Anbieter, die Datensätze zum Begriff publizieren",
    tabelle: () => tabelleHtml(["Begriff", "Anbieter", "Datensätze"], begriffe.map((b) => [knotenLink(b.id, b.label), zahl(b.anbieter), zahl(b.datensaetze)]), [1, 2]),
    zeichnen: (huelle) => horizontaleBalken(huelle, begriffe.map((b) => ({ label: b.label, wert: b.anbieter, href: knotenHref(b.id), tipp: `${zahl(b.anbieter)} Anbieter · ${zahl(b.datensaetze)} Datensätze` }))),
  });
}

// Horizontale Balken, direkt beschriftet, jeder Balken ein Link.
function horizontaleBalken(huelle, zeilen, { namenBreite = 200, klasse = "dg-balken" } = {}) {
  const zeile = 28, breite = Math.max(huelle.clientWidth, 320), hoehe = zeilen.length * zeile + 8;
  const nb = Math.min(namenBreite, breite * 0.4);
  const x = d3.scaleLinear().domain([0, d3.max(zeilen, (z) => z.wert) || 1]).range([0, breite - nb - 56]);
  const svg = d3.select(huelle).append("svg").attr("viewBox", [0, 0, breite, hoehe]).attr("role", "img")
    .attr("aria-label", zeilen.map((z) => `${z.label}: ${zahl(z.wert)}`).join("; "));
  const t = tipp(huelle);
  const g = svg.selectAll("a").data(zeilen).join("a").attr("href", (z) => z.href).attr("transform", (_, i) => `translate(0,${i * zeile + 4})`)
    .on("mousemove", (ev, z) => t.zeigen(ev, `<b>${esc(z.label)}</b><br>${esc(z.tipp || zahl(z.wert))}`)).on("mouseleave", t.weg);
  const zeichen = Math.max(12, Math.floor(nb / 6.6));
  g.append("text").attr("class", "dg-schrift").attr("x", nb - 8).attr("y", zeile / 2 + 4).attr("text-anchor", "end")
    .text((z) => (z.label.length > zeichen ? z.label.slice(0, zeichen - 1) + "…" : z.label));
  g.append("rect").attr("class", klasse).attr("x", nb).attr("y", 6).attr("height", zeile - 12).attr("rx", 4)
    .attr("width", (z) => Math.max(2, x(z.wert)));
  g.append("text").attr("class", "dg-wert").attr("x", (z) => nb + Math.max(2, x(z.wert)) + 6).attr("y", zeile / 2 + 4).text((z) => zahl(z.wert));
}

// ---------- Verbinden -------------------------------------------------------

async function verbinden(_, p) {
  const von = p.get("von") || "", nach = p.get("nach") || "", hubs = p.get("hubs") !== "aus";
  $inhalt.innerHTML = `
    <h1 class="frage-titel">Wie hängen zwei Dinge zusammen?</h1>
    <p class="unter">Der kürzeste Weg durch die verknüpften Daten, mit den Belegen jeder Verbindung.</p>
    <form class="verbinden-eingabe" id="verbinden" role="search">
      ${auswahlFeld("von", "Von … (z. B. Hund)")} ${auswahlFeld("nach", "Nach … (z. B. Steuer)")}
      <button type="submit">Weg suchen</button>
      <button type="button" class="zweit" id="zufall"><span aria-hidden="true">⚄</span> Überrasch mich</button>
    </form>
    <div class="werkzeuge"><label class="schalter"><input type="checkbox" id="hubs" ${hubs ? "checked" : ""}> Über Hubs</label>
      <span class="leise">Aus: Wege meiden Knoten mit sehr vielen Verbindungen (Gemeinde, Abstimmung, Kantone) und werden oft überraschender.</span></div>
    <div id="pfadergebnis"></div>`;
  const felder = { von: auswahlVerdrahten("von", von), nach: auswahlVerdrahten("nach", nach) };
  const los = () => {
    const v = felder.von(), n = felder.nach();
    if (v && n) location.hash = `#/pfad?von=${encodeURIComponent(v)}&nach=${encodeURIComponent(n)}${document.getElementById("hubs").checked ? "" : "&hubs=aus"}`;
  };
  document.getElementById("verbinden").addEventListener("submit", (ev) => { ev.preventDefault(); los(); });
  document.getElementById("hubs").addEventListener("change", los);
  document.getElementById("zufall").addEventListener("click", ueberraschMich);
  if (von && nach) await wegZeigen(von, nach, hubs);
}

function auswahlFeld(name, platzhalter) {
  return `<div class="auswahl-feld"><label class="sr" for="feld-${name}">${esc(platzhalter)}</label>
    <input type="text" id="feld-${name}" placeholder="${esc(platzhalter)}" autocomplete="off" role="combobox" aria-expanded="false" aria-controls="vor-${name}">
    <div class="vorschlag-liste" id="vor-${name}" role="listbox" hidden></div></div>`;
}

function auswahlVerdrahten(name, vorgabe) {
  const feld = document.getElementById("feld-" + name);
  let gewaehlt = vorgabe;
  if (vorgabe) api("/api/knoten?id=" + encodeURIComponent(vorgabe)).then((n) => { feld.value = n.label; gewaehlt = n.id; }).catch(() => {});
  feld.addEventListener("input", () => { gewaehlt = ""; });
  vorschlaegeVerdrahten(feld, document.getElementById("vor-" + name), (t) => { gewaehlt = t.id; feld.value = t.label; });
  return () => gewaehlt;
}

async function wegZeigen(von, nach, hubs) {
  const ziel = document.getElementById("pfadergebnis");
  ziel.innerHTML = `<p class="laden" role="status">Sucht den Weg …</p>`;
  const d = await api(`/api/pfad?von=${encodeURIComponent(von)}&nach=${encodeURIComponent(nach)}&k=4${hubs ? "" : "&hubs=aus"}`);
  if (!d.gefunden) {
    ziel.innerHTML = `<p class="leise">Kein Weg gefunden — diese beiden hängen im Graphen nicht zusammen${hubs ? "" : " (ohne Hubs). Versuchen Sie es mit «Über Hubs»"}.</p>`;
    return;
  }
  const [haupt, ...andere] = d.wege;
  const a = haupt.knoten[0], z = haupt.knoten[haupt.knoten.length - 1];
  ziel.innerHTML = `<section class="tafel" style="margin-top:16px" aria-labelledby="h-weg">
      <div class="tafel-kopf"><h2 id="h-weg">${esc(a.label)} → ${esc(z.label)} · ${haupt.schritte.length} Schritte</h2></div>
      ${kette(haupt)}
      ${vertrauen(haupt)}
      <div class="werkzeuge" style="margin-top:16px"><button type="button" id="teilen"><span aria-hidden="true">⤓</span> Als Bild teilen</button>
        <button type="button" class="zweit" id="alsnetz">Als Netz zeigen</button>
        <a class="knopf zweit" href="#/graph/${encodeURI(a.id)}">Umgebung von «${esc(a.label)}»</a>
        <a class="knopf zweit" href="#/graph/${encodeURI(z.id)}">Umgebung von «${esc(z.label)}»</a>
        <span class="leise" id="teilenmeldung" role="status"></span></div>
      <div id="wegnetz"></div>
      ${legendeKlassen()}
    </section>
    ${andere.length ? `<details class="detail" open><summary>${andere.length} ${andere.length === 1 ? "anderer Weg" : "andere Wege"} mit anderen Zwischenstationen</summary>
      ${andere.map((w) => `<div class="weg-block">${kette(w)}${vertrauen(w)}</div>`).join("")}</details>` : ""}`;
  document.getElementById("teilen").addEventListener("click", () => wegTeilen(haupt));
  document.getElementById("alsnetz").addEventListener("click", (ev) => {
    const n = document.getElementById("wegnetz");
    if (n.innerHTML) { n.innerHTML = ""; ev.target.textContent = "Als Netz zeigen"; return; }
    ev.target.textContent = "Netz ausblenden";
    n.innerHTML = `<div class="netz klein" id="graph"><div class="netz-info" id="graphinfo"></div></div>`;
    const kanten = d.wege.flatMap((w) => w.schritte.map((s) => ({ von: s.von, nach: s.nach, art: s.art, klasse: s.klasse, beleg: s.beleg })));
    const knoten = [...new Map(d.wege.flatMap((w) => w.knoten).map((k) => [k.id, k])).values()];
    graphZeichnen({ knoten, kanten }, a.id);
  });
}

// Ein Weg als PNG 1200×627 (LinkedIn-Format); dazu die Adresse in die Zwischenablage.
function zeilenUmbruch(text, max) {
  // Wörter länger als eine Zeile werden mit Trennstrich geteilt («Kirchgemeinde» in schmalen Kästen).
  const woerter = String(text).split(/\s+/).flatMap((w) => (w.length <= max ? [w] : w.match(new RegExp(`.{1,${max - 1}}`, "g")).map((t, i, a) => (i < a.length - 1 ? t + "-" : t)))), zeilen = [];
  let z = "";
  for (const w of woerter) {
    if ((z + " " + w).trim().length > max && z) { zeilen.push(z); z = w; } else z = (z + " " + w).trim();
  }
  if (z) zeilen.push(z);
  return zeilen.length > 4 ? [...zeilen.slice(0, 3), zeilen[3].slice(0, max - 1) + "…"] : zeilen;
}

async function wegTeilen(weg) {
  const B = 1200, H = 627, rand = 56, n = weg.knoten.length, luecke = 56;
  const box = (B - 2 * rand - (n - 1) * luecke) / n, boxH = 196, y0 = 200;
  const typFarbe = { ort: "#1baf7a", begriff: "#2a78d6", datensatz: "#eb6834" };
  const klasse = { belegt: ["#2a78d6", 3, ""], gemessen: ["#1baf7a", 6, ""], abgeleitet: ["#eb6834", 3, "10 7"] };
  let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${B}" height="${H}" viewBox="0 0 ${B} ${H}">
    <rect width="${B}" height="${H}" fill="#fcfcfb"/><rect width="${B}" height="8" fill="#da291c"/>
    <text x="${rand}" y="92" font-family="Helvetica, Arial, sans-serif" font-size="40" font-weight="700" fill="#0b0b0b">${esc(zeilenUmbruch(`${weg.knoten[0].label} → ${weg.knoten[n - 1].label}`, 48)[0])}</text>
    <text x="${rand}" y="136" font-family="Helvetica, Arial, sans-serif" font-size="22" fill="#52514e">Ein Weg in ${n - 1} Schritten durch die offenen Daten der Schweiz</text>`;
  weg.knoten.forEach((k, i) => {
    const x = rand + i * (box + luecke);
    svg += `<rect x="${x}" y="${y0}" width="${box}" height="${boxH}" rx="10" fill="#ffffff" stroke="#dcdad4"/>
      <rect x="${x}" y="${y0}" width="${box}" height="8" rx="4" fill="${typFarbe[k.typ] || "#a8a6a0"}"/>
      <text x="${x + 14}" y="${y0 + 38}" font-family="Helvetica, Arial, sans-serif" font-size="15" font-weight="700" letter-spacing="1.5" fill="#52514e">${esc((TYP_NAME[k.typ] || k.typ).toUpperCase())}</text>
      ${(() => {
        // Lange Wörter: Schrift verkleinern statt trennen (bis 14 px), erst darunter trennen.
        const laengstes = Math.max(...k.label.split(/\s+/).map((w) => w.length));
        const fs = Math.max(14, Math.min(21, Math.floor((box - 24) / (laengstes * 0.6))));
        const max = Math.max(7, Math.floor((box - 24) / (fs * 0.6)));
        return zeilenUmbruch(k.label, max).map((z, j) => `<text x="${x + 14}" y="${y0 + 72 + j * (fs + 5)}" font-family="Helvetica, Arial, sans-serif" font-size="${fs}" font-weight="700" fill="#0b0b0b">${esc(z)}</text>`).join("");
      })()}`;
    const s = weg.schritte[i];
    if (s) {
      const [f, w, dash] = klasse[s.klasse];
      const ax = x + box + 6, bx = x + box + luecke - 8, ay = y0 + boxH / 2;
      svg += `<line x1="${ax}" y1="${ay}" x2="${bx - 6}" y2="${ay}" stroke="${f}" stroke-width="${w}" ${dash ? `stroke-dasharray="${dash}"` : ""}/>
        <path d="M${bx - 10},${ay - 8} L${bx},${ay} L${bx - 10},${ay + 8} Z" fill="${f}"/>`;
    }
  });
  const leg = [["belegt", "#2a78d6", ""], ["gemessen", "#1baf7a", ""], ["abgeleitet (KI, mit Beleg)", "#eb6834", "10 7"]];
  svg += leg.map(([t, f, dash], i) => `<line x1="${rand + i * 190}" y1="${H - 64}" x2="${rand + i * 190 + 40}" y2="${H - 64}" stroke="${f}" stroke-width="${i === 1 ? 6 : 3}" ${dash ? `stroke-dasharray="${dash}"` : ""}/>
      <text x="${rand + i * 190 + 52}" y="${H - 58}" font-family="Helvetica, Arial, sans-serif" font-size="18" fill="#52514e">${t}</text>`).join("");
  svg += `<text x="${B - rand}" y="${H - 58}" text-anchor="end" font-family="Helvetica, Arial, sans-serif" font-size="18" font-weight="700" fill="#0b0b0b">linkeddata.sim-research.ch</text></svg>`;

  const meldung = document.getElementById("teilenmeldung");
  const bild = new Image();
  bild.onload = async () => {
    const canvas = document.createElement("canvas");
    canvas.width = B; canvas.height = H;
    canvas.getContext("2d").drawImage(bild, 0, 0);
    canvas.toBlob(async (blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `weg-${weg.knoten[0].label}-${weg.knoten[n - 1].label}.png`.toLowerCase().replace(/[^a-z0-9äöüé.-]+/g, "-");
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      let kopiert = false;
      try { await navigator.clipboard.writeText(location.href); kopiert = true; } catch { /* ohne Zwischenablage */ }
      if (meldung) meldung.textContent = kopiert ? "Bild gespeichert, Link kopiert." : "Bild gespeichert.";
    }, "image/png");
  };
  bild.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

// ---------- Knoten-Steckbrief ------------------------------------------------

async function knotenSeite(id) {
  laden();
  const n = await api("/api/knoten?id=" + encodeURIComponent(id));
  if (n.id !== id) history.replaceState(null, "", knotenHref(n.id));
  const kat = n.katalog;
  const klassen = Object.fromEntries(KLASSEN.map((k) => [k, n.kanten.filter((e) => e.klasse === k).length]));
  const ds = n.kanten.filter((e) => e.nachbar.typ === "datensatz").length;
  const meta = [];
  if (n.typ === "datensatz") {
    const von = kat?.zeitraum_von || n.zeit?.von, bis = kat?.zeitraum_bis || n.zeit?.bis;
    if (von || bis) meta.push(`Zeitraum ${esc(String(von || "?").slice(0, 10))} – ${esc(String(bis || "?").slice(0, 10))}`);
    if (kat?.aktualisierungsintervall) meta.push(esc(kat.aktualisierungsintervall));
  }
  if (n.bfs) meta.push(`BFS-Nr. ${esc(n.bfs)}`);
  if (n.typ === "ort" && n.amtlich === false) meta.push("nicht im amtlichen Gemeindeverzeichnis");
  if (n.aliase?.length) meta.push(`auch: ${n.aliase.map(esc).join(", ")}`);
  const verlag = n.kanten.find((e) => e.art === "publiziert_von");

  $inhalt.innerHTML = `
    <header class="steckbrief-kopf"><span class="typ">${esc(TYP_NAME[n.typ] || n.typ)}</span><h1>${esc(n.label)}</h1>
      ${meta.length ? `<div class="meta">${meta.join(" · ")}</div>` : ""}
      ${verlag ? `<div class="verlag">publiziert von ${knotenLink(verlag.nachbar.id, verlag.nachbar.label)}</div>` : ""}</header>
    ${kat?.beschreibung_de ? `<p class="unter">${esc(kat.beschreibung_de.slice(0, 600))}${kat.beschreibung_de.length > 600 ? " …" : ""}</p>` : ""}
    <div class="raster12">
      <section class="tafel s8" aria-labelledby="h-ego"><div class="tafel-kopf"><h2 id="h-ego">Womit ist ${esc(n.label.length > 50 ? "das" : `«${n.label}»`)} direkt verbunden?</h2>
        <a href="#/graph/${encodeURI(n.id)}">Grössere Umgebung →</a></div><div id="ego"></div></section>
      <aside class="tafel s4" aria-labelledby="h-mass"><h2 id="h-mass">Auf einen Blick</h2>
        <div class="mass-liste"><div><b>${zahl(n.kanten.length)}</b><span>Verbindungen</span></div>
          ${n.typ !== "datensatz" ? `<div><b>${zahl(ds)}</b><span>Datensätze</span></div>` : `<div><b>${zahl(kat?.tabellen?.length || 0)}</b><span>Tabellen geladen</span></div>`}</div>
        <div class="herkunft-balken" style="height:16px;margin:8px 0" role="img" aria-label="${KLASSEN.map((k) => `${k} ${klassen[k]}`).join(", ")}">
          ${KLASSEN.filter((k) => klassen[k]).map((k) => `<span class="k-${k}" style="flex:${klassen[k]}" title="${k}: ${klassen[k]}"></span>`).join("")}</div>
        <div class="herkunft-legende" style="font-size:.875rem">${KLASSEN.map((k) => `<span><i class="strich ${k}" aria-hidden="true"></i> ${prozent(klassen[k], n.kanten.length)} % ${k}</span>`).join("")}</div>
        <div id="ortkarte"></div>
        <p class="uri" style="margin-top:16px">${esc(n.uri)}<br><a href="/id/${encodeURI(n.id)}?format=ttl" target="_blank" rel="noopener">Turtle</a> · <a href="/id/${encodeURI(n.id)}?format=jsonld" target="_blank" rel="noopener">JSON-LD</a></p>
        <p><a class="knopf zweit" href="#/pfad?von=${encodeURIComponent(n.id)}">Weg von hier suchen</a></p></aside>
    </div>
    ${kat ? `<section class="tafel" id="daten" aria-labelledby="h-daten" style="margin-bottom:16px"></section>` : ""}
    <section aria-labelledby="h-aehnlich"><h2 id="h-aehnlich">Ähnliche ${esc(n.typ === "datensatz" ? "Datensätze" : n.typ === "ort" ? "Orte" : "Knoten")}</h2><div id="aehnlich"><p class="laden">Lädt …</p></div></section>
    <details class="detail"><summary>Alle ${zahl(n.kanten.length)} Verbindungen mit Belegen</summary>${legendeKlassen()}${kantenListe(n)}</details>`;

  egoNetz(n);
  api("/api/aehnliche?id=" + encodeURIComponent(n.id)).then((l) => {
    document.getElementById("aehnlich").innerHTML = l.length ? `<div class="chips">${l.map((x) => `<a class="chip" href="${knotenHref(x.id)}">${esc(x.label)}${x.aehnlich ? " · ähnlich" : x.gemeinsam ? ` · ${x.gemeinsam} gemeinsam` : ""}</a>`).join("")}</div>`
      : `<p class="leise">Keine ähnlichen Knoten gefunden.</p>`;
  }).catch(() => { document.getElementById("aehnlich").innerHTML = ""; });
  if (kat) brauche("diagramm").then(() => datenTafel(document.getElementById("daten"), n, kat)).catch((e) => { document.getElementById("daten").innerHTML = `<p class="fehler">${esc(e.message)}</p>`; });
  if (n.typ === "ort" && (n.bfs || n.kuerzel)) brauche("karte").then(() => ortKarte(document.getElementById("ortkarte"), n)).catch(() => {});
}

function kantenListe(n) {
  const gruppen = {};
  for (const k of n.kanten) {
    const name = k.richtung === "aus" ? ART_AUSGEHEND[k.art] || k.art : ART_EINGEHEND[k.art] || k.art;
    (gruppen[name] = gruppen[name] || []).push(k);
  }
  return Object.entries(gruppen).map(([name, liste]) => `
    <div class="kanten-gruppe"><h3>${esc(name)} · ${liste.length}</h3>
    ${liste.slice(0, 80).map((k) => `<div class="kante-zeile">
      <span>${knotenLink(k.nachbar.id, k.nachbar.label)}</span><span>${klasseMarke(k.klasse)}</span>
      ${k.beleg ? `<span class="beleg">«${esc(k.beleg)}»</span>` : ""}</div>`).join("")}
    ${liste.length > 80 ? `<p class="leise">… und ${liste.length - 80} weitere</p>` : ""}</div>`).join("");
}

async function egoNetz(n) {
  const ziel = document.getElementById("ego");
  const d = await api(`/api/graph?id=${encodeURIComponent(n.id)}&tiefe=1&max_knoten=31`);
  grafik(ziel, {
    ebene: "h3",
    rechts: legendeTypenKurz(),
    tabelle: () => tabelleHtml(["Nachbar", "Typ", "Verbindung"], d.kanten.map((e) => {
      const nb = d.knoten.find((k) => k.id === (e.von === n.id ? e.nach : e.von));
      return nb ? [knotenLink(nb.id, nb.label), esc(TYP_NAME[nb.typ] || nb.typ), `${klasseMarke(e.klasse)} ${esc(ART_NAME[e.art] || e.art)}`] : null;
    }).filter(Boolean)),
    zeichnen: (flaeche) => {
      flaeche.innerHTML = `<div class="netz klein" id="graph"><div class="netz-info" id="graphinfo"></div></div>`;
      graphZeichnen(d, n.id, { radial: true });
    },
    stand: d.knoten.length > 30 ? "Die 30 ersten Nachbarn; alle stehen unten in der Liste." : "",
  });
}
const legendeTypenKurz = () => `<span class="legende" style="display:inline-flex;margin:0 8px 0 0"><span><i class="punkt begriff"></i> Begriff</span><span><i class="punkt ort"></i> Ort</span><span><i class="punkt datensatz"></i> Datensatz</span></span>`;

// ---------- Graph (Netz) ---------------------------------------------------------

const TYP_FARBE = (typ) => farbe({ datensatz: "datensatz", begriff: "begriff", ort: "ort" }[typ] || "andere");

async function graphSeite(id, p) {
  laden();
  const tiefe = +(p.get("tiefe") || 2);
  const d = await api(`/api/graph?id=${encodeURIComponent(id)}&tiefe=${tiefe}&max_knoten=140`);
  const zentrum = d.knoten.find((k) => k.id === d.zentrum) || d.knoten[0];
  $inhalt.innerHTML = `
    <h1 class="frage-titel">Was liegt rund um «${esc(zentrum?.label || id)}»?</h1>
    <div class="werkzeuge">
      <a class="knopf zweit" href="${knotenHref(d.zentrum)}">Zum Steckbrief</a>
      ${[1, 2, 3].map((t) => `<a class="knopf ${t === tiefe ? "" : "zweit"}" href="#/graph/${encodeURI(d.zentrum)}?tiefe=${t}" ${t === tiefe ? 'aria-current="true"' : ""}>${t} ${t === 1 ? "Schritt" : "Schritte"}</a>`).join("")}
      <span class="leise">${d.knoten.length} Knoten · Klick: Details · Doppelklick: neu zentrieren</span></div>
    ${legendeKlassen()}${legendeTypen()}
    <div id="netzgrafik"></div>`;
  grafik(document.getElementById("netzgrafik"), {
    tabelle: () => tabelleHtml(["Knoten", "Typ", "Schritte vom Zentrum"], d.knoten.sort((a, b) => a.stufe - b.stufe).map((k) => [knotenLink(k.id, k.label), esc(TYP_NAME[k.typ] || k.typ), k.stufe]), [2]),
    zeichnen: (f) => { f.innerHTML = `<div class="netz" id="graph"><div class="netz-info" id="graphinfo"></div></div>`; graphZeichnen(d, d.zentrum); },
  });
}

function graphZeichnen(d, zentrumId, { radial = false } = {}) {
  const huelle = document.getElementById("graph");
  const breite = huelle.clientWidth || 800, hoehe = huelle.clientHeight || 500;
  const svg = d3.select(huelle).append("svg").attr("viewBox", [0, 0, breite, hoehe]).attr("role", "img")
    .attr("aria-label", `Netz mit ${d.knoten.length} Knoten`);
  const ebene = svg.append("g");
  svg.call(d3.zoom().scaleExtent([0.2, 4]).on("zoom", (ev) => ebene.attr("transform", ev.transform)));
  const knoten = d.knoten.map((k) => ({ ...k }));
  const kanten = d.kanten.map((k) => ({ ...k, source: k.von, target: k.nach }));
  const grad = {};
  kanten.forEach((k) => { grad[k.von] = (grad[k.von] || 0) + 1; grad[k.nach] = (grad[k.nach] || 0) + 1; });
  const radius = (k) => (k.id === zentrumId ? 14 : k.typ === "datensatz" ? 7 : Math.min(14, 6 + Math.sqrt(grad[k.id] || 1) * 1.5));
  const sim = d3.forceSimulation(knoten)
    .force("link", d3.forceLink(kanten).id((k) => k.id).distance((k) => (k.art === "aehnlich" ? 60 : radial ? 140 : 110)).strength(radial ? 0.6 : 0.35))
    .force("charge", d3.forceManyBody().strength(radial ? -260 : -420).distanceMax(500))
    .force("center", d3.forceCenter(breite / 2, hoehe / 2))
    .force("x", d3.forceX(breite / 2).strength(0.05)).force("y", d3.forceY(hoehe / 2).strength(0.07))
    .force("collide", d3.forceCollide().radius((k) => radius(k) + 16));
  // Vor dem ersten Zeichnen einschwingen: sonst startet der Graph als Knäuel.
  sim.stop();
  for (let i = 0; i < 260; i++) sim.tick();
  sim.alpha(0.05).restart();
  const linie = ebene.append("g").selectAll("line").data(kanten).join("line").attr("class", (k) => `kante-l ${k.klasse}`);
  linie.append("title").text((k) => `${k.klasse}: ${ART_NAME[k.art] || k.art}${k.beleg ? ` — «${k.beleg}»` : ""}`);
  const punkt = ebene.append("g").selectAll("circle").data(knoten).join("circle")
    .attr("r", radius).attr("fill", (k) => TYP_FARBE(k.typ))
    .attr("stroke", (k) => (k.id === zentrumId ? farbe("text") : null)).attr("stroke-width", (k) => (k.id === zentrumId ? 3 : 2))
    .call(d3.drag()
      .on("start", (ev, k) => { if (!ev.active) sim.alphaTarget(0.3).restart(); k.fx = k.x; k.fy = k.y; })
      .on("drag", (ev, k) => { k.fx = ev.x; k.fy = ev.y; })
      .on("end", (ev, k) => { if (!ev.active) sim.alphaTarget(0); k.fx = null; k.fy = null; }))
    .on("click", (ev, k) => graphInfo(k, kanten))
    .on("dblclick", (ev, k) => { location.hash = `#/graph/${encodeURI(k.id)}`; });
  punkt.append("title").text((k) => `${TYP_NAME[k.typ] || k.typ}: ${k.label}`);
  const schrift = ebene.append("g").selectAll("text")
    .data(knoten.filter((k) => k.typ !== "datensatz" || k.id === zentrumId || knoten.length < 40)).join("text")
    .text((k) => (k.label.length > 34 ? k.label.slice(0, 32) + "…" : k.label)).attr("dx", (k) => radius(k) + 4).attr("dy", 4);
  sim.on("tick", () => {
    linie.attr("x1", (k) => k.source.x).attr("y1", (k) => k.source.y).attr("x2", (k) => k.target.x).attr("y2", (k) => k.target.y);
    punkt.attr("cx", (k) => k.x).attr("cy", (k) => k.y);
    schrift.attr("x", (k) => k.x).attr("y", (k) => k.y);
  });
}

function graphInfo(k, kanten) {
  const info = document.getElementById("graphinfo");
  const eigene = kanten.filter((e) => e.source.id === k.id || e.target.id === k.id);
  info.style.display = "block";
  info.innerHTML = `<span class="typ">${esc(TYP_NAME[k.typ] || k.typ)}</span><h3 style="margin:4px 0 8px">${esc(k.label)}</h3>
    <p><a href="${knotenHref(k.id)}">Steckbrief →</a> · <a href="#/graph/${encodeURI(k.id)}">Hier zentrieren</a></p>
    <ul class="liste-schlicht">${eigene.slice(0, 25).map((e) => {
      const n = e.source.id === k.id ? e.target : e.source;
      return `<li>${klasseMarke(e.klasse)} ${esc(ART_NAME[e.art] || e.art)}: ${esc(n.label)}${e.beleg ? `<br><span class="leise">«${esc(e.beleg)}»</span>` : ""}</li>`;
    }).join("")}</ul>`;
}

// ---------- Fragen ------------------------------------------------------------

const BEISPIELFRAGEN = ["Wo wird Lärm gemessen?", "Welche Daten gibt es zu Tieren?", "Was wissen wir über Wohnungen in Zug?", "Wie entwickelt sich die Lufttemperatur?", "Wasserqualität in Seen und Flüssen"];

async function frage(_, p) {
  const vorgabe = p.get("q") || "";
  $inhalt.innerHTML = `
    <h1 class="frage-titel">Was möchten Sie wissen?</h1>
    <form class="suche" id="frageform" role="search"><label class="sr" for="fragefeld">Frage</label>
      <input type="text" id="fragefeld" value="${esc(vorgabe)}" placeholder="z. B. Welche Daten gibt es zu erneuerbarer Energie in Gemeinden?"><button>Fragen</button></form>
    <div class="chips">${BEISPIELFRAGEN.map((q) => `<a class="chip" href="#/frage?q=${encodeURIComponent(q)}">${esc(q)}</a>`).join("")}</div>
    <div id="frageantwort" aria-live="polite"></div>`;
  document.getElementById("frageform").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = document.getElementById("fragefeld").value.trim();
    if (q) location.hash = `#/frage?q=${encodeURIComponent(q)}`;
  });
  if (vorgabe) await frageStellen(vorgabe);
}

async function frageStellen(text) {
  const ziel = document.getElementById("frageantwort");
  const knopf = document.querySelector("#frageform button");
  knopf.disabled = true;
  ziel.innerHTML = `<p class="laden" role="status">Sucht in den Daten …</p>`;
  try {
    const d = await post("/api/frage", { frage: text });
    const begriffTreffer = d.treffer.filter((t) => t.typ === "begriff");
    const folge = [];
    for (const b of begriffTreffer.slice(0, 6)) {
      if (folge.length >= 2) break;
      if (!text.toLowerCase().includes(b.label.toLowerCase())) folge.push([`Welche Daten gibt es zu ${b.label}?`, `#/frage?q=${encodeURIComponent(`Welche Daten gibt es zu ${b.label}?`)}`]);
    }
    if (begriffTreffer.length >= 2) {
      const [a, b] = [begriffTreffer[0], begriffTreffer[1]];
      folge.push([`Wie hängt ${a.label} mit ${b.label} zusammen?`, `#/pfad?von=${encodeURIComponent(a.id)}&nach=${encodeURIComponent(b.id)}`]);
    }
    ziel.innerHTML = `
      ${d.erzaehlung ? `<p class="antwort-satz">${esc(d.erzaehlung)}</p>` : d.datensaetze.length ? "" : `<p class="antwort-satz">Dazu ist nichts verknüpft.</p>`}
      ${folge.length ? `<div class="chips" aria-label="Folgefragen">${folge.map(([t, h]) => `<a class="chip" href="${h}">${esc(t)}</a>`).join("")}</div>` : ""}
      <div class="frage-raster">
        <section aria-labelledby="h-grafik"><h2 id="h-grafik" class="sr">Grafik zur Antwort</h2><div id="antwortgrafik"><div class="laden-block" style="min-height:320px"></div></div></section>
        <aside aria-labelledby="h-quellen"><h2 id="h-quellen" style="margin-top:0">Quellen dieser Antwort · ${d.datensaetze.length}</h2>
          ${d.datensaetze.map((x) => `<a class="quelle" href="${knotenHref(x.id)}">${esc(x.label)}<small>${klasseMarke("abgeleitet")} über ${[...new Set(x.ueber)].slice(0, 3).map(esc).join(", ")}</small></a>`).join("")}</aside>
      </div>`;
    if (d.datensaetze.length) {
      await brauche("diagramm");
      await antwortGrafik(document.getElementById("antwortgrafik"), d.datensaetze);
    } else document.getElementById("antwortgrafik").innerHTML = "";
  } catch (e) { ziel.innerHTML = `<p class="fehler" role="alert">${esc(e.message)}</p>`; }
  knopf.disabled = false;
}

// ---------- Ausgelagerte Seiten -------------------------------------------------

async function entdecken(_, p) { laden(); await brauche("diagramm", "entdecken"); await entdeckenSeite(p); }
async function methode() { laden(); await brauche("markdown.js", "methode"); await methodeSeite(); }
