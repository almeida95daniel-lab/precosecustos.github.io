/* Bolso Hoje — interações leves: dica nos gráficos e busca de cidade. */
(function () {
  // ---- gráficos: mira + dica no ponto mais próximo
  document.querySelectorAll(".g-area").forEach(function (area) {
    var pts;
    try { pts = JSON.parse(area.dataset.pontos); } catch (e) { return; }
    var svg = area.querySelector("svg");
    var linha = area.querySelector(".g-linha");
    var mira = area.querySelector(".g-mira");
    var foco = area.querySelector(".g-foco");
    var dica = area.querySelector(".g-dica");
    var L = +area.dataset.largura, me = +area.dataset.me, md = +area.dataset.md;
    var coords = [];
    var d = linha.getAttribute("d").match(/[ML][^ML]+/g) || [];
    d.forEach(function (seg) {
      var p = seg.slice(1).split(",");
      coords.push([+p[0], +p[1]]);
    });
    // Em linhas em degrau há segmentos extras; usa só as posições dos pontos reais.
    var reais = [];
    var n = pts.length;
    for (var i = 0; i < n; i++) {
      var x = me + (L - me - md) * i / (n - 1);
      var achado = coords.filter(function (c) { return Math.abs(c[0] - x) < 0.2; }).pop();
      reais.push([x, achado ? achado[1] : 0]);
    }
    function mostrar(ev) {
      var r = svg.getBoundingClientRect();
      var cx = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left) * L / r.width;
      var i = Math.round((cx - me) / (L - me - md) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      var p = reais[i];
      mira.setAttribute("x1", p[0]); mira.setAttribute("x2", p[0]); mira.setAttribute("visibility", "visible");
      foco.setAttribute("cx", p[0]); foco.setAttribute("cy", p[1]); foco.setAttribute("visibility", "visible");
      dica.hidden = false;
      dica.textContent = pts[i][0] + ": " + pts[i][1];
      var px = p[0] * r.width / L + 6;
      var meia = dica.offsetWidth / 2;
      dica.style.left = Math.max(meia, Math.min(r.width - meia + 12, px)) + "px";
    }
    function esconder() {
      mira.setAttribute("visibility", "hidden"); foco.setAttribute("visibility", "hidden"); dica.hidden = true;
    }
    svg.addEventListener("pointermove", mostrar);
    svg.addEventListener("pointerdown", mostrar);
    svg.addEventListener("pointerleave", esconder);
  });

  // ---- busca de cidade
  var dados = document.getElementById("cidades-dados");
  var cidades = [];
  if (dados) { try { cidades = JSON.parse(dados.textContent); } catch (e) {} }
  window.BH_CIDADES = cidades;
  function sem(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim(); }
  document.querySelectorAll("form.busca").forEach(function (f) {
    var campo = f.querySelector("input");
    var msg = f.querySelector(".busca-msg");
    f.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var q = sem(campo.value.replace(/\s*\(..\)\s*$/, "").replace(/\s*-\s*..$/, ""));
      if (!q) { campo.focus(); return; }
      var exato = cidades.find(function (c) { return sem(c.n) === q || sem(c.n + " " + c.uf) === q; });
      var parcial = exato || cidades.find(function (c) { return sem(c.n).indexOf(q) === 0; }) ||
        cidades.find(function (c) { return sem(c.n).indexOf(q) >= 0; });
      if (parcial) { location.href = parcial.u; return; }
      if (msg) msg.textContent = "A ANP não pesquisa preços em “" + campo.value + "”. Procure uma cidade próxima ou veja a média do seu estado.";
    });
  });

  // ---- números em português
  window.BH = {
    brl: function (v, c) { return (v < 0 ? "-" : "") + "R$\u00a0" + Math.abs(v).toLocaleString("pt-BR", { minimumFractionDigits: c == null ? 2 : c, maximumFractionDigits: c == null ? 2 : c }); },
    num: function (v, c) { return v.toLocaleString("pt-BR", { minimumFractionDigits: c == null ? 2 : c, maximumFractionDigits: c == null ? 2 : c }); },
    ler: function (el) {
      if (el.type === "number") return parseFloat(el.value);
      var v = String(el.value).trim();
      if (v.indexOf(",") >= 0) v = v.replace(/\./g, "").replace(",", ".");
      return parseFloat(v);
    }
  };
})();
