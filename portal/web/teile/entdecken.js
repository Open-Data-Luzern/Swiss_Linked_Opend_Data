// Entdecken: vier Reiter. Daten vorberechnet beim Graphenbau (entdeckungen.json).
"use strict";

const ENTDECKEN_REITER = [
  ["wege", "Überraschende Wege", "Welche Wege verbinden Dinge, die nichts miteinander zu tun haben?"],
  ["kennzahlen", "Gleiche Kennzahl, mehrere Absender", "Wo publizieren mehrere Ebenen dieselbe Grösse?"],
  ["schluessel", "Gemeinsamer Schlüssel", "Welche Tabellen lassen sich heute schon direkt verbinden?"],
  ["vergleichen", "Vergleichen", "Wie hängen zwei Grössen über die Gemeinden zusammen?"],
];

async function entdeckenSeite(p) {
  const reiter = ENTDECKEN_REITER.some(([r]) => r === p.get("reiter")) ? p.get("reiter") : "wege";
  const d = await api("/api/entdeckungen");
  const [, , frageText] = ENTDECKEN_REITER.find(([r]) => r === reiter);
  $inhalt.innerHTML = `<h1 class="frage-titel">${esc(frageText)}</h1>
    <nav class="reiter" aria-label="Entdecken">${ENTDECKEN_REITER.map(([r, t]) => `<a class="knopf zweit" style="border:0;border-radius:0;${r === reiter ? `box-shadow:inset 0 -2px 0 var(--akzent);font-weight:600;color:var(--text)` : ""}" href="#/entdecken?reiter=${r}" ${r === reiter ? 'aria-current="page"' : ""}>${t}</a>`).join("")}</nav>
    <div id="entdecken-inhalt"></div>`;
  const ziel = document.getElementById("entdecken-inhalt");
  if (reiter === "wege") wegeGalerie(ziel, d);
  else if (reiter === "kennzahlen") kennzahlMatrix(ziel, d.kennzahlen);
  else if (reiter === "schluessel") schluesselNetz(ziel, d.schluessel);
  else await vergleichVerdrahten(ziel, null);
}

function wegeGalerie(ziel, d) {
  ziel.innerHTML = `<p class="unter">Kurze Wege zwischen Begriffen, die inhaltlich weit auseinander liegen. Die ersten sechs sind ausgewählt, die übrigen aus 500 Kandidaten berechnet.</p>
    <div class="galerie">${d.wege.map((w) => {
      const a = w.knoten[0], z = w.knoten[w.knoten.length - 1];
      return `<a class="karte-l" href="#/pfad?von=${encodeURIComponent(a.id)}&nach=${encodeURIComponent(z.id)}">
        <h2>${esc(a.label)} → ${esc(z.label)}</h2>${miniKette(w)}${vertrauen(w)}</a>`;
    }).join("")}</div>
    <p><button type="button" id="zufall2"><span aria-hidden="true">⚄</span> Überrasch mich</button></p>
    <h2>Verwandte Begriffe, die verschiedene Anbieter verbinden</h2>
    <p class="unter">Die Einbettung erkennt sie als verwandt, obwohl sie verschieden heissen. ${klasseMarke("abgeleitet")}</p>
    <div id="bruecken"></div>`;
  document.getElementById("zufall2").addEventListener("click", ueberraschMich);
  grafik(document.getElementById("bruecken"), {
    ebene: "h3",
    tabelle: () => tabelleHtml(["Begriff A", "Begriff B", "Ähnlichkeit", "Anbieter"], d.bruecken.map((b) => [knotenLink(b.a_id, b.a_label), knotenLink(b.b_id, b.b_label), zahl(b.gewicht, 3), zahl(b.anbieter)]), [2, 3]),
    zeichnen: (f) => horizontaleBalken(f, d.bruecken.map((b) => ({ label: `${b.a_label} ↔ ${b.b_label}`, wert: b.anbieter, href: knotenHref(b.a_id), tipp: `${zahl(b.anbieter)} Anbieter · Ähnlichkeit ${zahl(b.gewicht, 3)}` })), { namenBreite: 380, klasse: "dg-balken b" }),
    stand: "Anzahl Anbieter, deren Datensätze die beiden Begriffe zusammen verbinden",
  });
}

function kennzahlMatrix(ziel, m) {
  ziel.innerHTML = `<p class="unter">Kennzahlen, die mehrere Anbieter messen — aufgeteilt nach Ebene. Jede Zelle zählt die Anbieter.</p><div id="matrix"></div>`;
  grafik(document.getElementById("matrix"), {
    titel: "Anbieter je Kennzahl und Ebene", ebene: "h2",
    tabelle: () => tabelleHtml(["Kennzahl", ...m.ebenen], m.zeilen.map((z) => [knotenLink(z.id, z.label), ...z.werte.map((v) => zahl(v))]), [1, 2, 3, 4]),
    zeichnen: (f) => {
      const breite = Math.max(f.clientWidth, 320), zelleH = 32, kopf = 32, namen = Math.min(240, breite * 0.4);
      const zelleB = (breite - namen) / m.ebenen.length, hoehe = kopf + m.zeilen.length * zelleH;
      const max = d3.max(m.zeilen, (z) => d3.max(z.werte)) || 1;
      const c = d3.scaleSequential([0, max], d3.interpolateLab(farbe("seq-1"), farbe("seq-2")));
      const svg = d3.select(f).append("svg").attr("viewBox", [0, 0, breite, hoehe]).attr("role", "img")
        .attr("aria-label", m.zeilen.map((z) => `${z.label}: ${m.ebenen.map((e, i) => `${e} ${z.werte[i]}`).join(", ")}`).join("; "));
      svg.append("g").selectAll("text").data(m.ebenen).join("text").attr("class", "dg-achse")
        .attr("x", (_, i) => namen + i * zelleB + zelleB / 2).attr("y", 20).attr("text-anchor", "middle").text((e) => e);
      const t = tipp(f);
      const zeile = svg.append("g").selectAll("a").data(m.zeilen).join("a").attr("href", (z) => knotenHref(z.id))
        .attr("transform", (_, i) => `translate(0,${kopf + i * zelleH})`);
      zeile.append("text").attr("class", "dg-schrift").attr("x", namen - 8).attr("y", zelleH / 2 + 4).attr("text-anchor", "end")
        .text((z) => (z.label.length > 32 ? z.label.slice(0, 31) + "…" : z.label));
      const zellen = zeile.selectAll("g").data((z) => z.werte.map((v, i) => ({ v, e: m.ebenen[i], z }))).join("g")
        .attr("transform", (_, i) => `translate(${namen + i * zelleB},0)`)
        .on("mousemove", (ev, x) => t.zeigen(ev, `<b>${esc(x.z.label)}</b><br>${esc(x.e)}: ${zahl(x.v)} Anbieter`)).on("mouseleave", t.weg);
      zellen.append("rect").attr("class", "hm-zelle").attr("width", zelleB).attr("height", zelleH).attr("rx", 4)
        .attr("fill", (x) => (x.v ? c(x.v) : farbe("seq-0")));
      zellen.append("text").attr("class", "hm-zahl").attr("x", zelleB / 2).attr("y", zelleH / 2 + 4).attr("text-anchor", "middle")
        .attr("fill", (x) => (x.v > max * 0.55 ? "#fff" : farbe("text"))).text((x) => (x.v ? x.v : "–"));
    },
  });
}

function schluesselNetz(ziel, liste) {
  const themen = [...new Set(liste.map((x) => x.thema))].sort();
  ziel.innerHTML = `<p class="unter">${zahl(liste.length)} Datensätze enthalten eine Spalte, deren Werte gültige Gemeindenummern oder Kantone sind — geprüft an den Daten. Diese Tabellen lassen sich ohne weitere Arbeit verbinden. ${klasseMarke("gemessen")}</p>
    <div id="schluesselnetz"></div>`;
  grafik(document.getElementById("schluesselnetz"), {
    titel: "Datensätze am gemeinsamen Schlüssel, gruppiert nach Thema", ebene: "h2",
    tabelle: () => tabelleHtml(["Datensatz", "Thema", "Schlüssel", "Beleg"], liste.map((x) => [knotenLink(x.id, x.label), esc(x.thema), x.schluessel.endsWith("kanton") ? "Kanton" : "Gemeinde", esc(x.beleg)])),
    zeichnen: (f) => {
      f.innerHTML = `<div class="netz" id="sn" style="height:680px"></div>`;
      const huelle = f.firstElementChild;
      const breite = huelle.clientWidth || 900, hoehe = huelle.clientHeight || 560;
      const mitte = [breite / 2, hoehe / 2];
      // Gruppen auf einer Ellipse; grosse Gruppen bekommen mehr Bogen, damit sie sich nicht berühren.
      const anzahl = Object.fromEntries(themen.map((t) => [t, liste.filter((x) => x.thema === t).length]));
      const gewicht = themen.map((t) => Math.sqrt(anzahl[t]) + 2), summe = d3.sum(gewicht);
      const rx = breite * 0.3, ry = hoehe * 0.33;
      let lauf = -Math.PI / 2;
      const zentren = {}, winkel = {};
      themen.forEach((t, i) => {
        const w = lauf + (gewicht[i] / summe) * Math.PI;
        lauf += (gewicht[i] / summe) * 2 * Math.PI;
        winkel[t] = w;
        zentren[t] = [mitte[0] + rx * Math.cos(w), mitte[1] + ry * Math.sin(w)];
      });
      const gruppenRadius = (t) => Math.sqrt(anzahl[t]) * 6 + 6;
      const schluessel = [...new Set(liste.map((x) => x.schluessel))].map((s, i) => ({ id: s, label: s.endsWith("kanton") ? "Kanton" : "Gemeinde (BFS-Nr.)", typ: "schluessel", fx: mitte[0] + (i ? 60 : -60), fy: mitte[1] }));
      const knoten = [...schluessel, ...liste.map((x) => ({ ...x, typ: "datensatz" }))];
      const kanten = liste.map((x) => ({ source: x.id, target: x.schluessel }));
      const sim = d3.forceSimulation(knoten)
        .force("link", d3.forceLink(kanten).id((k) => k.id).strength(0.02))
        .force("x", d3.forceX((k) => (zentren[k.thema] || mitte)[0]).strength(0.25))
        .force("y", d3.forceY((k) => (zentren[k.thema] || mitte)[1]).strength(0.25))
        .force("collide", d3.forceCollide(7)).stop();
      for (let i = 0; i < 300; i++) sim.tick();
      const svg = d3.select(huelle).append("svg").attr("viewBox", [0, 0, breite, hoehe]).attr("role", "img").attr("aria-label", `${liste.length} Datensätze in ${themen.length} Themen`);
      svg.append("g").selectAll("line").data(kanten).join("line").attr("class", "kante-l gemessen").attr("stroke-width", 1).attr("stroke-opacity", 0.25)
        .attr("x1", (k) => k.source.x).attr("y1", (k) => k.source.y).attr("x2", (k) => k.target.x).attr("y2", (k) => k.target.y);
      const t = tipp(huelle);
      svg.append("g").selectAll("a").data(knoten).join("a").attr("href", (k) => knotenHref(k.id))
        .append("circle").attr("cx", (k) => k.x).attr("cy", (k) => k.y).attr("r", (k) => (k.typ === "schluessel" ? 16 : 5))
        .attr("fill", (k) => (k.typ === "schluessel" ? farbe("gemessen") : farbe("datensatz")))
        .on("mousemove", (ev, k) => t.zeigen(ev, `<b>${esc(k.label)}</b>${k.thema ? `<br>${esc(k.thema)}` : ""}`)).on("mouseleave", t.weg);
      // Beschriftung nach aussen, weg von der Mitte
      svg.append("g").selectAll("text").data(themen).join("text").attr("class", "gruppe")
        .attr("x", (th) => zentren[th][0] + Math.cos(winkel[th]) * (gruppenRadius(th) + 12))
        .attr("y", (th, i) => zentren[th][1] + Math.sin(winkel[th]) * (gruppenRadius(th) + 12) + 4 + (Math.abs(Math.cos(winkel[th])) <= 0.3 && Math.sin(winkel[th]) > 0 ? (i % 2) * 18 : 0))
        .attr("text-anchor", (th) => (Math.cos(winkel[th]) > 0.3 ? "start" : Math.cos(winkel[th]) < -0.3 ? "end" : "middle"))
        .text((th) => `${th.length > 26 ? th.slice(0, 25) + "…" : th} · ${anzahl[th]}`).append("title").text((th) => th);
      svg.append("g").selectAll("text").data(schluessel).join("text").attr("x", (k) => k.x).attr("y", (k) => k.y + 30).attr("text-anchor", "middle").text((k) => k.label);
    },
  });
}
