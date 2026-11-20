// Ein kleiner Markdown-Renderer fuer den Theorieteil: Ueberschriften,
// Absaetze, Listen, Tabellen, Codebloecke, Blockzitate, Hervorhebungen, Links.
// Bewusst klein statt einer weiteren Bibliothek; der Text ist redaktionell
// und vertrauenswuerdig, wird aber trotzdem escaped.
(function () {
  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function inline(s) {
    var codes = [];
    s = s.replace(/`([^`]+)`/g, function (_, c) { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
    s = esc(s);
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (_, t, u) {
      var sicher = /^(https?:|#|\/)/.test(u) ? u : "#";
      return '<a href="' + sicher + '"' + (/^https?:/.test(u) ? ' target="_blank" rel="noopener"' : "") + ">" + t + "</a>";
    });
    s = s.replace(/\u0000(\d+)\u0000/g, function (_, i) { return "<code>" + esc(codes[+i]) + "</code>"; });
    return s;
  }
  function zellen(z) {
    return z.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(function (c) { return c.trim(); });
  }
  function render(md) {
    var zeilen = md.replace(/\r/g, "").split("\n");
    var out = [], i = 0;
    while (i < zeilen.length) {
      var z = zeilen[i];
      if (/^```/.test(z)) {
        var code = []; i++;
        while (i < zeilen.length && !/^```/.test(zeilen[i])) { code.push(zeilen[i]); i++; }
        i++; out.push("<pre><code>" + esc(code.join("\n")) + "</code></pre>"); continue;
      }
      var h = /^(#{1,4})\s+(.*)$/.exec(z);
      if (h) {
        var n = h[1].length, text = h[2];
        var anker = text.toLowerCase().replace(/[^a-z0-9äöüéèà]+/g, "-").replace(/^-|-$/g, "");
        out.push("<h" + n + ' id="' + anker + '">' + inline(text) + "</h" + n + ">"); i++; continue;
      }
      if (/^(-{3,}|\*{3,})\s*$/.test(z)) { out.push("<hr>"); i++; continue; }
      if (/^\s*\|/.test(z) && i + 1 < zeilen.length && /^\s*\|?\s*:?-{2,}/.test(zeilen[i + 1])) {
        var kopf = zellen(z); i += 2;
        var html = "<table><thead><tr>" + kopf.map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") + "</tr></thead><tbody>";
        while (i < zeilen.length && /^\s*\|/.test(zeilen[i])) {
          html += "<tr>" + zellen(zeilen[i]).map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>"; i++;
        }
        out.push(html + "</tbody></table>"); continue;
      }
      if (/^>\s?/.test(z)) {
        var zitat = [];
        while (i < zeilen.length && /^>\s?/.test(zeilen[i])) { zitat.push(zeilen[i].replace(/^>\s?/, "")); i++; }
        out.push("<blockquote>" + render(zitat.join("\n")) + "</blockquote>"); continue;
      }
      if (/^\s*([-*]|\d+\.)\s+/.test(z)) {
        var geordnet = /^\s*\d+\./.test(z), punkte = [];
        while (i < zeilen.length && /^\s*([-*]|\d+\.)\s+/.test(zeilen[i])) {
          var p = zeilen[i].replace(/^\s*([-*]|\d+\.)\s+/, ""); i++;
          while (i < zeilen.length && /^\s{2,}\S/.test(zeilen[i]) && !/^\s*([-*]|\d+\.)\s+/.test(zeilen[i])) { p += " " + zeilen[i].trim(); i++; }
          punkte.push("<li>" + inline(p) + "</li>");
        }
        out.push((geordnet ? "<ol>" : "<ul>") + punkte.join("") + (geordnet ? "</ol>" : "</ul>")); continue;
      }
      if (!z.trim()) { i++; continue; }
      var absatz = [z]; i++;
      while (i < zeilen.length && zeilen[i].trim() && !/^(#{1,4}\s|```|>|\s*\||\s*([-*]|\d+\.)\s)/.test(zeilen[i])) { absatz.push(zeilen[i]); i++; }
      out.push("<p>" + inline(absatz.join(" ")) + "</p>");
    }
    return out.join("\n");
  }
  window.markdown = render;
})();
