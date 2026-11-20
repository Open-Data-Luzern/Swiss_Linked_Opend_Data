// Gemeindekarte (Choroplethe) und Ortskarte im Steckbrief.
// Grenzen: swisstopo swissBOUNDARIES3D, Stand 1.1.2026, als TopoJSON in
// karten/gemeinden-2026.topo.json (2'110 Gemeinden, deckungsgleich mit dem
// amtlichen Gemeindeverzeichnis 1.1.2026).
"use strict";

let _kartenDaten = null;

async function gemeindeKarteDaten() {
  if (_kartenDaten) return _kartenDaten;
  await brauche("lib/topojson-client-3.1.0.min.js");
  const [topo, daten] = await Promise.all([
    fetch(new URL("karten/gemeinden-2026.topo.json", location.origin)).then((r) => r.json()),
    api("/api/karte?mass=datensaetze"),
  ]);
  _kartenDaten = {
    gemeinden: topojson.feature(topo, topo.objects.gemeinden),
    kantone: topojson.feature(topo, topo.objects.kantone),
    grenzen: topojson.mesh(topo, topo.objects.kantone),
    seen: topojson.feature(topo, topo.objects.seen),
    daten,
  };
  return _kartenDaten;
}

// Wohin «Alles zu meiner Gemeinde» führt: zur Gemeinde, wenn Datensätze sie
// nennen; sonst zu ihrem Kanton.
const gemeindeZiel = (g) => (g.wert ? `#/knoten/ort/gemeinde/${g.bfs}` : g.kanton ? `#/knoten/ort/kanton/${g.kanton}` : "#/");

function gemeindeKarte(ziel, k, { titel, ebene = "h2", werte = null, sql = "", herkunft = null, stand = "" } = {}) {
  const zaehlung = !werte;
  const liste = werte || k.daten.gemeinden.map((g) => ({ bfs: g.bfs, gemeinde: g.name, wert: g.wert, kanton: g.kanton }));
  const wert = new Map(liste.map((g) => [g.bfs, g.wert]));
  const max = d3.max(liste, (g) => g.wert) || 1, min = Math.min(0, d3.min(liste, (g) => g.wert) || 0);
  // Zählungen: Wurzelskala, sonst bestimmen Zürich und Genf allein die Farbe.
  const anteil = zaehlung ? d3.scaleSqrt().domain([0, max]).range([0, 1]) : (v) => (v - min) / (max - min || 1);
  const verlauf = d3.interpolateLab(farbe("seq-1"), farbe("seq-2"));
  const farbeVon = (v) => verlauf(Math.max(0, Math.min(1, anteil(v))));
  const leer = farbe("seq-0");
  const ziele = new Map(k.daten.gemeinden.map((g) => [g.bfs, g]));
  const mitWert = liste.filter((g) => g.wert).sort((a, b) => b.wert - a.wert);

  grafik(ziel, {
    titel: esc(titel), ebene, stand,
    rechts: `<span class="karte-skala" aria-hidden="true">${zaehlung ? "0" : zahl(min, 2)} <i style="background:linear-gradient(90deg, ${farbe("seq-1")}, ${farbe("seq-2")})"></i> ${zahl(max, 2)}</span> `,
    tabelle: () => tabelleHtml(["Gemeinde", "Kanton", zaehlung ? "Datensätze" : "Wert"],
      mitWert.map((g) => [`<a href="${zaehlung ? gemeindeZiel(ziele.get(g.bfs) || g) : `#/knoten/ort/gemeinde/${g.bfs}`}">${esc(g.gemeinde)}</a>`, esc((ziele.get(g.bfs) || {}).kanton || ""), zahl(g.wert, 2)]), [2])
      + (zaehlung ? `<p class="leise">${zahl(liste.length - mitWert.length)} Gemeinden werden in keinem Datensatz ausdrücklich genannt.</p>` : "")
      + (sql ? `<div class="sql">${esc(sql)}</div>` : "") + (herkunft && window.herkunftZeile ? herkunftZeile(herkunft) : ""),
    zeichnen: (f) => {
      const breite = Math.max(f.clientWidth, 320), hoehe = Math.min(560, Math.round(breite * 0.64));
      const proj = d3.geoMercator().fitSize([breite, hoehe], k.kantone);
      const pfad = d3.geoPath(proj);
      const svg = d3.select(f).append("svg").attr("viewBox", [0, 0, breite, hoehe]).attr("class", "karte-svg").attr("role", "img")
        .attr("aria-label", `Karte der Schweiz. Höchste Werte: ${mitWert.slice(0, 5).map((g) => `${g.gemeinde} ${zahl(g.wert, 2)}`).join(", ")}`);
      const t = tipp(f);
      svg.append("g").selectAll("path").data(k.gemeinden.features).join("path")
        .attr("class", "gemeinde").attr("d", pfad)
        .attr("fill", (g) => { const v = wert.get(g.properties.bfs); return v ? farbeVon(v) : leer; })
        .on("mousemove", (ev, g) => {
          const v = wert.get(g.properties.bfs);
          t.zeigen(ev, `<b>${esc(g.properties.name)}</b><br>${v == null ? "keine Angabe" : zaehlung ? `${zahl(v)} Datensätze` : zahl(v, 2)}`);
        })
        .on("mouseleave", t.weg)
        .on("click", (ev, g) => {
          const z = ziele.get(g.properties.bfs);
          location.hash = zaehlung || !wert.get(g.properties.bfs) ? gemeindeZiel(z || { bfs: g.properties.bfs }) : `#/knoten/ort/gemeinde/${g.properties.bfs}`;
        });
      svg.append("g").selectAll("path").data(k.seen.features).join("path").attr("class", "see").attr("d", pfad);
      svg.append("path").datum(k.grenzen).attr("class", "kanton").attr("d", pfad);
    },
  });
}

// Kleine Karte im Steckbrief eines Orts: Gemeinde oder Kanton hervorgehoben.
async function ortKarte(ziel, n) {
  if (!ziel) return;
  const k = await gemeindeKarteDaten();
  const breite = Math.max(ziel.clientWidth, 240), hoehe = Math.round(breite * 0.64);
  const proj = d3.geoMercator().fitSize([breite, hoehe], k.kantone);
  const pfad = d3.geoPath(proj);
  ziel.innerHTML = `<figure class="grafik" style="margin-top:16px"><div class="grafik-flaeche"></div><figcaption class="stand">Grenzen © swisstopo</figcaption></figure>`;
  const f = ziel.querySelector(".grafik-flaeche");
  const svg = d3.select(f).append("svg").attr("viewBox", [0, 0, breite, hoehe]).attr("class", "karte-svg").attr("role", "img")
    .attr("aria-label", `Lage von ${n.label} in der Schweiz`);
  const istGemeinde = (g) => n.bfs && g.properties.bfs === +n.bfs;
  svg.append("g").selectAll("path").data(n.bfs ? k.gemeinden.features : k.kantone.features).join("path")
    .attr("class", "gemeinde").attr("d", pfad).style("cursor", "default")
    .attr("fill", (g) => (istGemeinde(g) || (!n.bfs && g.properties.kuerzel === n.kuerzel) ? farbe("ort") : farbe("seq-0")));
  svg.append("g").selectAll("path").data(k.seen.features).join("path").attr("class", "see").attr("d", pfad);
  svg.append("path").datum(k.grenzen).attr("class", "kanton").attr("d", pfad);
  // Kleine Gemeinden: ein Ring, damit man sie überhaupt findet.
  const g = n.bfs && k.gemeinden.features.find(istGemeinde);
  if (g) {
    const [x, y] = pfad.centroid(g);
    svg.append("circle").attr("cx", x).attr("cy", y).attr("r", 9).attr("fill", "none").attr("stroke", farbe("text")).attr("stroke-width", 2);
  }
}
