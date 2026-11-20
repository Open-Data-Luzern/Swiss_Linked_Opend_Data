// Diagramme aus den Tabellen: Datentafel im Steckbrief, Diagramm-Baukasten,
// Vergleich zweier Tabellen über die BFS-Gemeindenummer, Grafik zur Antwort.
// Jede Zahl im Bild kommt per Abfrage aus der Tabelle; Abfrage und Herkunft
// stehen in der Tabellenansicht jeder Grafik.
"use strict";

// Spalten, deren Zahlen Kennungen sind und keine Mengen: kein Tausendertrenner.
const KENNUNG = /jahr|year|annee|anno|bfs|code|nr$|nummer|_id$|^id$|plz|npa|egid|egrid/i;
const ZEITACHSE = /jahr|year|annee|anno|datum|date|monat|month|quartal|zeit|time|periode/i;
const AGG_WAHL = [["anzahl", "Anzahl Zeilen"], ["summe", "Summe"], ["mittel", "Mittelwert"], ["max", "Maximum"], ["min", "Minimum"]];

const optionen = (liste, gewaehlt) => liste.map(([w, t]) => `<option value="${esc(w)}"${w === gewaehlt ? " selected" : ""}>${esc(t)}</option>`).join("");
const q = (o) => new URLSearchParams(o).toString();

function zahlKurz(v) {
  if (v == null) return "–";
  const a = Math.abs(v);
  const f = (x, s) => x.toLocaleString("de-CH", { maximumFractionDigits: s }).replace(/’/g, "'");
  return a >= 1e9 ? f(v / 1e9, 1) + " Mrd." : a >= 1e6 ? f(v / 1e6, 1) + " Mio." : f(v, a < 10 ? 2 : 0);
}

function datenTabelle(spalten, zeilen) {
  const formatieren = (v, i) => (typeof v !== "number" ? esc(v) : KENNUNG.test(spalten[i] || "") ? String(v) : esc(zahl(v, 2)));
  return `<div class="tabelle-huelle"><table class="daten"><thead><tr>${spalten.map((s) => `<th scope="col">${esc(s)}</th>`).join("")}</tr></thead>
    <tbody>${zeilen.map((z) => `<tr>${z.map((v, i) => `<td class="${typeof v === "number" ? "zahl-zelle" : ""}" title="${esc(v)}">${formatieren(v, i)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function herkunftZeile(h) {
  if (!h) return "";
  return `<p class="herkunft">Quelle: ${esc(h.titel_de || "")} — «${esc(h.datensatz)}» · Lizenz ${esc(h.lizenz || "–")}${h.opendata_url ? ` · <a href="${esc(h.opendata_url)}" target="_blank" rel="noopener">opendata.swiss</a>` : ""}${h.url ? ` · <a href="${esc(h.url)}" target="_blank" rel="noopener">Quelldatei</a>` : ""}</p>`;
}

async function tabellenSchema(datei, tabelle) {
  const d = await api(`/api/tabelle?${q({ datei, tabelle, anzahl: 10 })}`);
  const profil = Object.fromEntries((d.profil || []).map((p) => [p.spalte, p]));
  const spalten = d.spalten.filter((s) => !/^(datensammlung_id|_|zeile$|row_?id$)/i.test(s));
  const zahlen = spalten.filter((s) => ["INTEGER", "REAL"].includes(profil[s]?.typ));
  const masse = zahlen.filter((s) => !KENNUNG.test(s) && !ZEITACHSE.test(s) && !/bfs|gemeinde|^id|nr$|code/i.test(s));
  return { spalten, zahlen, masse, profil, vorschau: d, herkunft: d.herkunft };
}

// Die wichtigste Achse: Zeit, sonst eine Textspalte mit überschaubar vielen Werten.
function standardAchse(schema) {
  const verschieden = (s) => schema.profil[s]?.anzahl_verschieden ?? 999;
  return schema.spalten.find((s) => ZEITACHSE.test(s) && verschieden(s) > 1)
    || schema.spalten.find((s) => !schema.zahlen.includes(s) && verschieden(s) >= 2 && verschieden(s) <= 40)
    || schema.spalten.find((s) => !schema.zahlen.includes(s)) || schema.spalten[0];
}

const wertBeschrieb = (agg_name, spalte, filter) =>
  `${agg_name}${spalte ? ` von «${spalte}»` : ""}${filter ? ` (nur ${filter.spalte} = ${filter.wert})` : ""}`;

// ---------- Zeichnen ----------------------------------------------------------

function rahmen(huelle, hoehe, links, unten) {
  const breite = Math.max(huelle.clientWidth, 320);
  const svg = d3.select(huelle).append("svg").attr("viewBox", [0, 0, breite, hoehe]).attr("class", "dg").attr("role", "img");
  return { svg, breite, hoehe, rand: { o: 16, r: 24, u: unten, l: links } };
}

function yAchse(svg, y, rand, breite) {
  svg.append("g").attr("class", "gitter").attr("transform", `translate(${rand.l},0)`)
    .call(d3.axisLeft(y).ticks(5).tickSize(-(breite - rand.l - rand.r)).tickFormat(""));
  svg.append("g").attr("class", "achse").attr("transform", `translate(${rand.l},0)`).call(d3.axisLeft(y).ticks(5).tickSize(0).tickPadding(8).tickFormat(zahlKurz))
    .call((g) => g.select(".domain").remove());
}

function balkenDiagramm(huelle, punkte, xName) {
  const lang = punkte.length > 12 || punkte.some((p) => String(p[0]).length > 8);
  const { svg, breite, hoehe, rand } = rahmen(huelle, 360, 64, lang ? 104 : 36);
  svg.attr("aria-label", punkte.slice(0, 40).map((p) => `${p[0]}: ${zahlKurz(p[1])}`).join("; "));
  const x = d3.scaleBand().domain(punkte.map((p) => String(p[0]))).range([rand.l, breite - rand.r]).paddingInner(0.12);
  const ys = punkte.map((p) => p[1] ?? 0);
  const y = d3.scaleLinear().domain([Math.min(0, d3.min(ys)), Math.max(0, d3.max(ys))]).nice().range([hoehe - rand.u, rand.o]);
  yAchse(svg, y, rand, breite);
  const t = tipp(huelle);
  const band = Math.max(1, x.bandwidth());
  svg.append("g").selectAll("path").data(punkte).join("path").attr("class", "dg-balken")
    .attr("d", (p) => {
      const v = p[1] ?? 0, x0 = x(String(p[0])), y0 = y(0), y1 = y(v), r = Math.min(4, band / 2, Math.abs(y1 - y0));
      return v >= 0 ? `M${x0},${y0}V${y1 + r}q0,-${r} ${r},-${r}h${band - 2 * r}q${r},0 ${r},${r}V${y0}Z`
        : `M${x0},${y0}V${y1 - r}q0,${r} ${r},${r}h${band - 2 * r}q${r},0 ${r},-${r}V${y0}Z`;
    })
    .on("mousemove", (ev, p) => t.zeigen(ev, `<b>${esc(p[0])}</b><br>${esc(zahlKurz(p[1]))}`)).on("mouseleave", t.weg);
  const ax = svg.append("g").attr("class", "achse").attr("transform", `translate(0,${hoehe - rand.u})`)
    .call(d3.axisBottom(x).tickSize(0).tickPadding(8).tickFormat((v) => (v.length > 18 ? v.slice(0, 17) + "…" : v)));
  if (lang) ax.selectAll("text").attr("transform", "rotate(-40)").style("text-anchor", "end");
  if (punkte.length > 40) ax.selectAll(".tick").filter((_, i) => i % Math.ceil(punkte.length / 40)).remove();
}

function linienDiagramm(huelle, punkte, xName) {
  const { svg, breite, hoehe, rand } = rahmen(huelle, 340, 64, 36);
  const daten = punkte.filter((p) => p[1] != null);
  svg.attr("aria-label", daten.slice(0, 60).map((p) => `${p[0]}: ${zahlKurz(p[1])}`).join("; "));
  const xZahl = daten.every((p) => typeof p[0] === "number");
  const x = xZahl ? d3.scaleLinear().domain(d3.extent(daten, (p) => p[0])).range([rand.l, breite - rand.r])
    : d3.scalePoint().domain(daten.map((p) => String(p[0]))).range([rand.l, breite - rand.r]);
  const xv = (p) => x(xZahl ? p[0] : String(p[0]));
  const ys = daten.map((p) => p[1]);
  const y = d3.scaleLinear().domain([Math.min(0, d3.min(ys)), d3.max(ys)]).nice().range([hoehe - rand.u, rand.o]);
  yAchse(svg, y, rand, breite);
  svg.append("path").datum(daten).attr("class", "dg-linie").attr("d", d3.line().x(xv).y((p) => y(p[1])));
  const ax = d3.axisBottom(x).tickSize(0).tickPadding(8);
  if (xZahl) ax.tickFormat((v) => (KENNUNG.test(xName) || ZEITACHSE.test(xName) ? String(v) : zahlKurz(v))).ticks(Math.min(daten.length, 10));
  else if (daten.length > 14) ax.tickValues(x.domain().filter((_, i) => i % Math.ceil(daten.length / 14) === 0));
  svg.append("g").attr("class", "achse").attr("transform", `translate(0,${hoehe - rand.u})`).call(ax).call((g) => g.select(".domain").attr("stroke", farbe("raster")));
  // Fadenkreuz: nächster Punkt zur Maus
  const fokus = svg.append("g").style("display", "none");
  fokus.append("line").attr("y1", rand.o).attr("y2", hoehe - rand.u).attr("stroke", farbe("text-3")).attr("stroke-dasharray", "3 3");
  fokus.append("circle").attr("r", 4).attr("class", "dg-punkt");
  const t = tipp(huelle);
  svg.append("rect").attr("x", rand.l).attr("y", rand.o).attr("width", breite - rand.l - rand.r).attr("height", hoehe - rand.o - rand.u)
    .attr("fill", "transparent")
    .on("mousemove", (ev) => {
      const [mx] = d3.pointer(ev);
      const p = daten.reduce((a, b) => (Math.abs(xv(b) - mx) < Math.abs(xv(a) - mx) ? b : a));
      fokus.style("display", null).attr("transform", `translate(${xv(p)},0)`);
      fokus.select("circle").attr("cy", y(p[1]));
      t.zeigen(ev, `<b>${esc(p[0])}</b><br>${esc(zahlKurz(p[1]))}`);
    })
    .on("mouseleave", () => { fokus.style("display", "none"); t.weg(); });
  if (daten.length <= 24) svg.append("g").selectAll("circle").data(daten).join("circle").attr("class", "dg-punkt").attr("cx", xv).attr("cy", (p) => y(p[1])).attr("r", 4).style("pointer-events", "none");
}

// Diagramm aus einer /api/diagramm-Antwort in eine grafik()-Fläche.
function diagrammZeigen(ziel, d, { titel, art = "auto", ebene = "h3", stand = "" } = {}) {
  const xZahl = d.punkte.every((p) => typeof p[0] === "number");
  if (art === "auto") art = (ZEITACHSE.test(d.x) || xZahl) && d.punkte.length > 2 ? "linie" : "balken";
  grafik(ziel, {
    titel: esc(titel || `${wertBeschrieb(d.agg_name, d.y, d.filter)} nach «${d.x}»`), ebene,
    stand: (d.gekuerzt ? `Die ersten ${d.punkte.length} von ${zahl(d.gruppen)} Gruppen. ` : "") + stand,
    tabelle: () => datenTabelle([d.x, d.agg_name], d.punkte) + `<div class="sql">${esc(d.sql)}</div>${herkunftZeile(d.herkunft)}`,
    zeichnen: (f) => {
      if (!d.punkte.length) { f.innerHTML = `<p class="leise">Keine Werte.</p>`; return; }
      (art === "linie" ? linienDiagramm : balkenDiagramm)(f, d.punkte, d.x);
    },
  });
}

async function standardDiagramm(ziel, datei, tabelle, { schema, titelVorsatz = "" } = {}) {
  schema = schema || (await tabellenSchema(datei, tabelle));
  const x = standardAchse(schema), y = schema.masse[0] || "";
  const d = await api(`/api/diagramm?${q({ datei, tabelle, x, y, agg: y ? "summe" : "anzahl" })}`);
  diagrammZeigen(ziel, d, { titel: titelVorsatz + `${wertBeschrieb(d.agg_name, d.y, d.filter)} nach «${d.x}»` });
  return d;
}

// ---------- Datentafel im Steckbrief eines Datensatzes ---------------------------

function datenTafel(ziel, n, kat) {
  const quelle = `<p class="herkunft">Lizenz ${esc(kat.lizenz_text || kat.lizenz || "–")}${kat.opendata_url ? ` · <a href="${esc(kat.opendata_url)}" target="_blank" rel="noopener">opendata.swiss ↗</a>` : ""}${kat.landingpage ? ` · <a href="${esc(kat.landingpage)}" target="_blank" rel="noopener">Seite des Anbieters ↗</a>` : ""}</p>`;
  if (!kat.tabellen.length) {
    ziel.innerHTML = `<h2 id="h-daten">Was steht in den Daten?</h2><p class="leise">Zu diesem Datensatz ist keine Tabelle geladen (${zahl(kat.datensammlungen)} Datensammlungen ohne Zeilen und Spalten, etwa Karten oder Dokumente).</p>${quelle}`;
    return;
  }
  ziel.innerHTML = `<div class="tafel-kopf"><h2 id="h-daten">Was steht in den Daten?</h2>
      <label class="leise">Tabelle <select id="tabwahl">${kat.tabellen.map((t, i) => `<option value="${i}">${esc(t.datensammlung)} — ${zahl(t.zeilen)} Zeilen</option>`).join("")}</select></label></div>
    <div class="reiter" role="tablist" id="tabreiter">
      ${[["ueberblick", "Überblick"], ["diagramm", "Diagramm"], ["vergleich", "Vergleich über Gemeinden"], ["frage", "Frage an die Tabelle"]].map(([r, t], i) =>
        `<button type="button" role="tab" data-reiter="${r}" aria-selected="${i === 0}">${t}</button>`).join("")}</div>
    <div data-tafel="ueberblick" role="tabpanel"><div class="raster12" style="margin:0"><div class="s6" id="vorschau"></div><div class="s6" id="standard"></div></div></div>
    <div data-tafel="diagramm" role="tabpanel" hidden></div>
    <div data-tafel="vergleich" role="tabpanel" hidden></div>
    <div data-tafel="frage" role="tabpanel" hidden>
      <form id="tabfrage" class="suche"><label class="sr" for="tabfeld">Frage an diese Tabelle</label>
        <input type="text" id="tabfeld" placeholder="z. B. Welche fünf Gemeinden haben den höchsten Wert?"><button>Fragen</button></form>
      <div id="tabantwort" aria-live="polite"></div></div>
    ${quelle}`;
  const wahl = document.getElementById("tabwahl");
  const tafel = (r) => ziel.querySelector(`[data-tafel="${r}"]`);
  let reiter = "ueberblick";
  const geladen = {};
  const tabelle = () => kat.tabellen[+wahl.value];

  const ueberblick = async () => {
    const t = tabelle();
    document.getElementById("vorschau").innerHTML = `<p class="laden">Lädt …</p>`;
    document.getElementById("standard").innerHTML = `<div class="laden-block"></div>`;
    try {
      const schema = await tabellenSchema(n.datei, t.tabelle);
      const v = schema.vorschau;
      // Technische Spalten des Ladevorgangs nicht zeigen.
      const zeigen = v.spalten.map((s, i) => [s, i]).filter(([s]) => schema.spalten.includes(s));
      document.getElementById("vorschau").innerHTML = `<h3 style="margin-top:0">Die ersten ${Math.min(10, v.zeilen.length)} von ${zahl(t.zeilen)} Zeilen</h3>`
        + datenTabelle(zeigen.map(([s]) => s), v.zeilen.map((z) => zeigen.map(([, i]) => z[i])));
      await standardDiagramm(document.getElementById("standard"), n.datei, t.tabelle, { schema });
    } catch (e) { document.getElementById("standard").innerHTML = `<p class="fehler">${esc(e.message)}</p>`; }
  };
  const zeigen = (r) => {
    reiter = r;
    ziel.querySelectorAll("#tabreiter button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.reiter === r)));
    ziel.querySelectorAll("[data-tafel]").forEach((x) => { x.hidden = x.dataset.tafel !== r; });
    const t = tabelle();
    if ((r === "diagramm" || r === "vergleich") && geladen[r] !== t.tabelle) {
      geladen[r] = t.tabelle;
      (r === "diagramm" ? diagrammBaukasten(tafel(r), n.datei, t.tabelle) : vergleichVerdrahten(tafel(r), { datei: n.datei, tabelle: t.tabelle }))
        .catch((e) => { tafel(r).innerHTML = `<p class="fehler">${esc(e.message)}</p>`; });
    }
  };
  document.getElementById("tabreiter").addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (b) zeigen(b.dataset.reiter); });
  wahl.addEventListener("change", () => { ueberblick(); if (reiter !== "ueberblick" && reiter !== "frage") zeigen(reiter); });
  ueberblick();

  document.getElementById("tabfrage").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const frageText = document.getElementById("tabfeld").value.trim();
    if (!frageText) return;
    const aus = document.getElementById("tabantwort"), knopf = ev.target.querySelector("button");
    knopf.disabled = true;
    aus.innerHTML = `<p class="laden" role="status">Schreibt die Abfrage …</p>`;
    try {
      const d = await post("/api/frage_tabelle", { datei: n.datei, tabelle: tabelle().tabelle, frage: frageText });
      aus.innerHTML = `<p>${esc(d.erklaerung)}</p>${datenTabelle(d.spalten, d.zeilen)}<details><summary class="leise">Abfrage</summary><div class="sql">${esc(d.sql)}</div></details>`;
    } catch (e) { aus.innerHTML = `<p class="fehler">${esc(e.message)}</p>`; }
    knopf.disabled = false;
  });
}

// Ein Wertblock: Zusammenfassung, Wertspalte, optionaler Filter.
function wertBlock(ziel, schema, datei, tabelle, praefix, vorgabe = {}) {
  const wertSpalten = [...schema.masse, ...schema.zahlen.filter((s) => !schema.masse.includes(s)), ...schema.spalten.filter((s) => !schema.zahlen.includes(s))];
  const id = (r) => `${praefix || "d"}-${r}-${Math.random().toString(36).slice(2, 7)}`;
  const ids = { agg: id("agg"), y: id("y"), fs: id("fs"), fw: id("fw") };
  ziel.innerHTML = `<div class="formzeile">
      <label for="${ids.agg}">Wert</label><select id="${ids.agg}" data-r="agg">${optionen(AGG_WAHL, vorgabe.agg || (schema.masse.length ? "summe" : "anzahl"))}</select>
      <span data-r="ywrap"><label for="${ids.y}">von Spalte</label> <select id="${ids.y}" data-r="y">${optionen(wertSpalten.map((s) => [s, s + (schema.zahlen.includes(s) ? "" : " (Text)")]), vorgabe.y || schema.masse[0] || schema.zahlen[0])}</select></span>
    </div>
    <div class="formzeile">
      <label for="${ids.fs}">Nur Zeilen mit</label><select id="${ids.fs}" data-r="fs"><option value="">— kein Filter —</option>${optionen(schema.spalten.map((s) => [s, s]))}</select>
      <span data-r="fwwrap" hidden><label for="${ids.fw}">=</label> <select id="${ids.fw}" data-r="fw"></select></span>
    </div>`;
  const el = (r) => ziel.querySelector(`[data-r="${r}"]`);
  const ywrap = () => { el("ywrap").hidden = el("agg").value === "anzahl"; };
  el("agg").addEventListener("change", ywrap); ywrap();
  el("fs").addEventListener("change", async () => {
    const s = el("fs").value;
    el("fwwrap").hidden = !s;
    if (!s) return;
    el("fw").innerHTML = `<option>Lädt …</option>`;
    const w = await api(`/api/werte?${q({ datei, tabelle, spalte: s })}`);
    el("fw").innerHTML = w.filter((x) => x.wert !== null).map((x) => `<option value="${esc(x.wert)}">${esc(x.wert)} (${zahl(x.anzahl)} Zeilen)</option>`).join("");
  });
  // Vergleich je Gemeinde: über mehrere Jahre zu summieren ist meist sinnlos —
  // darum das neueste Jahr vorwählen (änderbar).
  if (vorgabe.zeitFilter) {
    const z = schema.spalten.find((s) => ZEITACHSE.test(s));
    if (z) { el("fs").value = z; el("fs").dispatchEvent(new Event("change")); }
  }
  return () => ({ [praefix + "agg"]: el("agg").value, [praefix + (praefix ? "wert" : "y")]: el("agg").value === "anzahl" ? "" : el("y").value,
    [praefix + "filter_spalte"]: el("fs").value, [praefix + "filter_wert"]: el("fs").value ? el("fw").value : "" });
}

async function diagrammBaukasten(ziel, datei, tabelle) {
  ziel.innerHTML = `<p class="laden">Lädt …</p>`;
  const schema = await tabellenSchema(datei, tabelle);
  const xid = "dg-x-" + Math.random().toString(36).slice(2, 7), aid = xid + "a";
  ziel.innerHTML = `<div class="formzeile"><label for="${xid}">Achse (gruppiert nach)</label> <select id="${xid}">${optionen(schema.spalten.map((s) => [s, s]), standardAchse(schema))}</select>
      <label for="${aid}">Darstellung</label> <select id="${aid}"><option value="auto">automatisch</option><option value="balken">Balken</option><option value="linie">Linie</option></select></div>
    <div data-r="wert"></div><p><button type="button" data-r="los">Diagramm zeichnen</button></p><div data-r="bild"></div>`;
  const wert = wertBlock(ziel.querySelector('[data-r="wert"]'), schema, datei, tabelle, "");
  ziel.querySelector('[data-r="los"]').addEventListener("click", async () => {
    const bild = ziel.querySelector('[data-r="bild"]');
    bild.innerHTML = `<p class="laden">Rechnet …</p>`;
    try {
      const d = await api(`/api/diagramm?${q({ datei, tabelle, x: document.getElementById(xid).value, ...wert() })}`);
      diagrammZeigen(bild, d, { art: document.getElementById(aid).value });
    } catch (e) { bild.innerHTML = `<p class="fehler">${esc(e.message)}</p>`; }
  });
}

// ---------- Vergleich über die BFS-Gemeindenummer --------------------------------

async function tabellenWahl(ziel, praefix, beiWahl, vorgabe) {
  const liste = await api("/api/vergleichbar");
  const dsid = `vg-ds-${praefix}${Math.random().toString(36).slice(2, 6)}`;
  ziel.innerHTML = `<div class="formzeile"><label for="${dsid}">Datensatz</label> <select id="${dsid}" data-r="ds"><option value="">— wählen (${liste.length} mit Gemeindenummer) —</option>
      ${liste.map((x, i) => `<option value="${i}"${vorgabe && x.id === vorgabe ? " selected" : ""}>${esc(x.label.slice(0, 90))}</option>`).join("")}</select></div>
    <div class="formzeile" data-r="tabwrap" hidden><label for="${dsid}t">Tabelle</label> <select id="${dsid}t" data-r="tab"></select></div><div data-r="wert"></div>`;
  const el = (r) => ziel.querySelector(`[data-r="${r}"]`);
  let tabellen = [], ds = null, holen = null;
  const tabelleGewaehlt = async () => {
    const t = tabellen[+el("tab").value];
    el("wert").innerHTML = `<p class="laden">Lädt …</p>`;
    const schema = await tabellenSchema(ds.datei, t.tabelle);
    const s = await api(`/api/schluesselspalte?${q({ datei: ds.datei, tabelle: t.tabelle })}`);
    if (!s.spalte) { el("wert").innerHTML = `<p class="leise">Diese Tabelle hat keine Spalte mit BFS-Gemeindenummern — bitte eine andere wählen.</p>`; holen = null; beiWahl(); return; }
    const box = document.createElement("div");
    el("wert").innerHTML = `<p class="leise">Verbunden über die Spalte «${esc(s.spalte)}» ${klasseMarke("gemessen")}</p>`;
    el("wert").appendChild(box);
    const w = wertBlock(box, schema, ds.datei, t.tabelle, praefix, { zeitFilter: true });
    holen = () => ({ [praefix + "datei"]: ds.datei, [praefix + "tabelle"]: t.tabelle, ...w() });
    beiWahl();
  };
  el("ds").addEventListener("change", async () => {
    ds = liste[+el("ds").value]; holen = null; el("wert").innerHTML = ""; beiWahl();
    if (!ds) { el("tabwrap").hidden = true; return; }
    const n = await api("/api/knoten?id=" + encodeURIComponent(ds.id));
    tabellen = n.katalog?.tabellen || [];
    el("tab").innerHTML = tabellen.map((t, i) => `<option value="${i}">${esc(t.datensammlung)} — ${zahl(t.zeilen)} Zeilen</option>`).join("");
    el("tabwrap").hidden = !tabellen.length;
    if (tabellen.length) tabelleGewaehlt();
  });
  el("tab").addEventListener("change", tabelleGewaehlt);
  if (vorgabe && el("ds").value) el("ds").dispatchEvent(new Event("change"));
  return () => (holen ? holen() : null);
}

async function vergleichVerdrahten(ziel, a) {
  // a: feste Seite A {datei, tabelle} (aus dem Steckbrief) oder null (Entdecken)
  ziel.innerHTML = `<div class="raster12" style="margin:16px 0">
      <div class="tafel s6"><h3 style="margin-top:0">A${a ? " · diese Tabelle" : ""}</h3><div data-r="a"></div></div>
      <div class="tafel s6"><h3 style="margin-top:0">B · vergleichen mit</h3><div data-r="b"></div></div></div>
    <p><button type="button" data-r="los" disabled>Vergleichen</button> <span class="leise">Nur Gemeinden, die in beiden Tabellen vorkommen.</span></p>
    <div data-r="bild"></div>`;
  const el = (r) => ziel.querySelector(`[data-r="${r}"]`);
  const knopf = el("los");
  let holeA, holeB;
  const pruefen = () => { knopf.disabled = !(holeA && holeA() && holeB && holeB()); };
  if (a) {
    const box = el("a");
    const s = await api(`/api/schluesselspalte?${q(a)}`);
    if (!s.spalte) { ziel.innerHTML = `<p class="leise">Diese Tabelle hat keine Spalte mit gültigen BFS-Gemeindenummern; ein Vergleich über Gemeinden ist nicht möglich. Zwei andere Tabellen vergleichen: <a href="#/entdecken?reiter=vergleichen">Entdecken → Vergleichen</a>.</p>`; return; }
    const schema = await tabellenSchema(a.datei, a.tabelle);
    box.innerHTML = `<p class="leise">Verbunden über die Spalte «${esc(s.spalte)}» ${klasseMarke("gemessen")}</p><div></div>`;
    const w = wertBlock(box.lastElementChild, schema, a.datei, a.tabelle, "a_", { zeitFilter: true });
    holeA = () => ({ a_datei: a.datei, a_tabelle: a.tabelle, ...w() });
  } else {
    holeA = await tabellenWahl(el("a"), "a_", pruefen);
  }
  holeB = await tabellenWahl(el("b"), "b_", pruefen);
  pruefen();
  knopf.addEventListener("click", async () => {
    const bild = el("bild");
    bild.innerHTML = `<p class="laden">Rechnet …</p>`;
    try {
      const d = await api("/api/vergleich?" + q({ ...holeA(), ...holeB() }));
      const na = wertBeschrieb(d.a.agg_name, d.a.wert, d.a.filter), nb = wertBeschrieb(d.b.agg_name, d.b.wert, d.b.filter);
      bild.innerHTML = `<div class="werkzeuge" role="group" aria-label="Darstellung">
          <button type="button" class="zweit" data-art="streu" aria-pressed="true">Streudiagramm</button>
          <button type="button" class="zweit" data-art="balken" aria-pressed="false">Je Gemeinde, zwei Grafiken</button></div><div data-r="grafik"></div>`;
      const zeichne = (art) => {
        bild.querySelectorAll("[data-art]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.art === art)));
        grafik(bild.querySelector('[data-r="grafik"]'), {
          titel: `Wie hängen A und B in ${zahl(d.punkte.length)} Gemeinden zusammen?`, ebene: "h3",
          stand: `A: ${esc(na)} — ${esc(d.a.herkunft?.datensatz || "")} · B: ${esc(nb)} — ${esc(d.b.herkunft?.datensatz || "")}`,
          tabelle: () => datenTabelle(["BFS-Nr.", "Gemeinde", "A", "B"], d.punkte.map((p) => [p.bfs, p.gemeinde, p.a, p.b]))
            + `<div class="sql">A: ${esc(d.a.sql)}</div><div class="sql">B: ${esc(d.b.sql)}</div>${herkunftZeile(d.a.herkunft)}${herkunftZeile(d.b.herkunft)}`,
          zeichnen: (f) => {
            if (!d.punkte.length) { f.innerHTML = `<p class="leise">Keine gemeinsamen Gemeinden.</p>`; return; }
            (art === "streu" ? streuDiagramm : zweiBalken)(f, d.punkte, na, nb);
          },
        });
      };
      bild.querySelectorAll("[data-art]").forEach((b) => b.addEventListener("click", () => zeichne(b.dataset.art)));
      zeichne("streu");
    } catch (e) { bild.innerHTML = `<p class="fehler">${esc(e.message)}</p>`; }
  });
}

function streuDiagramm(huelle, punkte, na, nb) {
  const { svg, breite, hoehe, rand } = rahmen(huelle, 440, 72, 48);
  svg.attr("aria-label", `Streudiagramm, ${punkte.length} Gemeinden`);
  const x = d3.scaleLinear().domain(d3.extent(punkte, (p) => p.a)).nice().range([rand.l, breite - rand.r]);
  const y = d3.scaleLinear().domain(d3.extent(punkte, (p) => p.b)).nice().range([hoehe - rand.u, rand.o]);
  yAchse(svg, y, rand, breite);
  svg.append("g").attr("class", "achse").attr("transform", `translate(0,${hoehe - rand.u})`).call(d3.axisBottom(x).ticks(8).tickSize(0).tickPadding(8).tickFormat(zahlKurz));
  const t = tipp(huelle);
  svg.append("g").selectAll("circle").data(punkte).join("circle").attr("class", "dg-punkt")
    .attr("cx", (p) => x(p.a)).attr("cy", (p) => y(p.b)).attr("r", punkte.length > 300 ? 4 : 5)
    .on("mousemove", (ev, p) => t.zeigen(ev, `<b>${esc(p.gemeinde)}</b> (${p.bfs})<br>A: ${esc(zahlKurz(p.a))}<br>B: ${esc(zahlKurz(p.b))}`)).on("mouseleave", t.weg);
  if (punkte.length <= 30) svg.append("g").selectAll("text").data(punkte).join("text").attr("class", "dg-schrift")
    .attr("x", (p) => x(p.a) + 8).attr("y", (p) => y(p.b) + 4).text((p) => p.gemeinde);
  svg.append("text").attr("class", "dg-achse").attr("x", breite - rand.r).attr("y", hoehe - 8).attr("text-anchor", "end").text("A: " + na);
  svg.append("text").attr("class", "dg-achse").attr("x", rand.l).attr("y", 12).text("B: " + nb);
}

// Zwei Grössen mit verschiedenen Einheiten: zwei Grafiken nebeneinander, je eine Achse.
function zweiBalken(huelle, punkte, na, nb) {
  const liste = [...punkte].sort((p, q2) => q2.a - p.a).slice(0, 40);
  huelle.innerHTML = `<div class="raster12" style="margin:0"><div class="s6"><h4>A: ${esc(na)}</h4><div data-r="a"></div></div><div class="s6"><h4>B: ${esc(nb)}</h4><div data-r="b"></div></div></div>
    ${punkte.length > liste.length ? `<p class="leise">Die ${liste.length} Gemeinden mit dem höchsten Wert A; alle ${punkte.length} stehen in der Tabellenansicht.</p>` : ""}`;
  horizontaleBalken(huelle.querySelector('[data-r="a"]'), liste.map((p) => ({ label: p.gemeinde, wert: p.a, href: `#/knoten/ort/gemeinde/${p.bfs}`, tipp: zahlKurz(p.a) })), { namenBreite: 140 });
  horizontaleBalken(huelle.querySelector('[data-r="b"]'), liste.map((p) => ({ label: p.gemeinde, wert: p.b, href: `#/knoten/ort/gemeinde/${p.bfs}`, tipp: zahlKurz(p.b) })), { namenBreite: 140, klasse: "dg-balken b" });
}

// ---------- Grafik zur Antwort einer Frage ---------------------------------------

async function antwortGrafik(ziel, datensaetze) {
  // Alle Quellen gleichzeitig abfragen; die erste mit geladener Tabelle liefert die Grafik.
  const knoten = (await Promise.all(datensaetze.map((ds) => api("/api/knoten?id=" + encodeURIComponent(ds.id)).catch(() => null))))
    .filter((n) => n?.katalog?.tabellen?.[0]?.zeilen);
  // Tabellen mit einer echten Messgrösse zuerst; ein reiner Zeilenzähler beantwortet kaum eine Frage.
  const kandidaten = [];
  for (const n of knoten.slice(0, 6)) {
    const schema = await tabellenSchema(n.datei, n.katalog.tabellen[0].tabelle).catch(() => null);
    if (schema?.spalten.length) kandidaten.push([n, schema]);
  }
  kandidaten.sort((a, b) => (b[1].masse.length > 0) - (a[1].masse.length > 0));
  for (const [n, schema] of kandidaten) {
    const t = n.katalog.tabellen[0];
    const vorsatz = "";
    const unter = `<p class="leise" style="margin-top:8px">Aus ${knotenLink(n.id, n.label)}</p>`;
    // Gemeinden → Karte; sonst Zeit → Linie; sonst Kategorien → Balken.
    const s = await api(`/api/schluesselspalte?${q({ datei: n.datei, tabelle: t.tabelle })}`).catch(() => ({}));
    if (s.spalte) {
      const zeit = schema.spalten.find((x) => ZEITACHSE.test(x));
      let filter = {};
      if (zeit) {
        const w = await api(`/api/werte?${q({ datei: n.datei, tabelle: t.tabelle, spalte: zeit })}`);
        if (w[0]?.wert != null) filter = { filter_spalte: zeit, filter_wert: String(w[0].wert) };
      }
      const y = schema.masse[0] || "";
      const d = await api(`/api/je_gemeinde?${q({ datei: n.datei, tabelle: t.tabelle, wert: y, agg: y ? "summe" : "anzahl", ...filter })}`);
      if (d.punkte.length >= 3) {
        await brauche("karte");
        const k = await gemeindeKarteDaten();
        const box = document.createElement("div");
        ziel.innerHTML = "";
        ziel.appendChild(box);
        gemeindeKarte(box, k, {
          titel: `${wertBeschrieb(d.agg_name, d.wert, d.filter)} je Gemeinde`, ebene: "h3",
          werte: d.punkte, sql: d.sql, herkunft: d.herkunft, stand: "Grenzen © swisstopo",
        });
        ziel.insertAdjacentHTML("beforeend", unter);
        return;
      }
    }
    const box = document.createElement("div");
    ziel.innerHTML = "";
    ziel.appendChild(box);
    await standardDiagramm(box, n.datei, t.tabelle, { schema, titelVorsatz: vorsatz });
    ziel.insertAdjacentHTML("beforeend", unter);
    return;
  }
  ziel.innerHTML = `<p class="leise">Unter den gefundenen Datensätzen ist keine Tabelle geladen, aus der sich eine Grafik rechnen liesse.</p>`;
}
