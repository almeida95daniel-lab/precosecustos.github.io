/* Bolso Hoje — interações leves: dica nos gráficos e busca de cidade. */
(function () {
  // ---- menu no celular
  var botao = document.querySelector(".menu-btn"), menu = document.getElementById("menu-principal");
  if (botao && menu) {
    botao.addEventListener("click", function () {
      var aberto = menu.classList.toggle("aberto");
      botao.setAttribute("aria-expanded", aberto ? "true" : "false");
    });
  }

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

  // ---- lista de cidades (carregada só quando alguém usa a busca)
  var estilo = document.querySelector('link[rel="stylesheet"][href*="/static/"]');
  var RAIZ_STATIC = estilo ? estilo.getAttribute("href").replace(/estilo\.css.*$/, "") : "/static/";
  var promessaCidades = null;
  function cidades() {
    if (!promessaCidades) {
      promessaCidades = fetch(RAIZ_STATIC + "cidades.json").then(function (r) { return r.json(); })
        .then(function (d) { window.BH_CIDADES = d; return d; })
        .catch(function () { promessaCidades = null; return []; });
    }
    return promessaCidades;
  }
  window.BH_CIDADES = [];
  function sem(s) { return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim(); }
  function achar(lista, q, max) {
    var ini = [], meio = [];
    for (var i = 0; i < lista.length && ini.length < max; i++) {
      var n = lista[i]._s || (lista[i]._s = sem(lista[i].n));
      if (n.indexOf(q) === 0) ini.push(lista[i]); else if (meio.length < max && n.indexOf(q) > 0) meio.push(lista[i]);
    }
    return ini.concat(meio).slice(0, max);
  }
  document.querySelectorAll("form.busca").forEach(function (f) {
    var campo = f.querySelector("input"), msg = f.querySelector(".busca-msg"), caixa = f.querySelector(".sugestoes");
    if (!campo || !msg) return;
    var achados = [], ativo = -1;
    campo.addEventListener("focus", cidades, { once: true });
    function fechar() { if (caixa) { caixa.hidden = true; caixa.innerHTML = ""; } ativo = -1; }
    function marcar(i) {
      var itens = caixa.querySelectorAll("a");
      itens.forEach(function (a, k) { a.classList.toggle("ativo", k === i); });
      ativo = i;
    }
    if (caixa) {
      campo.addEventListener("input", function () {
        msg.textContent = "";
        var q = sem(campo.value);
        if (q.length < 2) { fechar(); return; }
        cidades().then(function (lista) {
          if (sem(campo.value) !== q) return;
          achados = achar(lista, q, 8);
          if (!achados.length) { fechar(); return; }
          caixa.innerHTML = achados.map(function (c) {
            return '<li role="option"><a href="' + c.u + '">' + c.n + " <small>" + c.uf + "</small></a></li>";
          }).join("");
          caixa.hidden = false; ativo = -1;
        });
      });
      campo.addEventListener("keydown", function (ev) {
        if (caixa.hidden) return;
        var n = achados.length;
        if (ev.key === "ArrowDown") { ev.preventDefault(); marcar((ativo + 1) % n); }
        else if (ev.key === "ArrowUp") { ev.preventDefault(); marcar((ativo - 1 + n) % n); }
        else if (ev.key === "Enter" && ativo >= 0) { ev.preventDefault(); location.href = achados[ativo].u; }
        else if (ev.key === "Escape") fechar();
      });
      document.addEventListener("click", function (ev) { if (!f.contains(ev.target)) fechar(); });
    }
    f.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var q = sem(campo.value.replace(/\s*\(..\)\s*$/, "").replace(/\s*-\s*..$/, ""));
      if (!q) { campo.focus(); return; }
      cidades().then(function (lista) {
        var exato = lista.find(function (c) { return sem(c.n) === q || sem(c.n + " " + c.uf) === q; });
        var parcial = exato || achar(lista, q, 1)[0];
        if (parcial) { location.href = parcial.u; return; }
        msg.textContent = "A ANP não pesquisa preços em \u201c" + campo.value + "\u201d. Tente uma cidade vizinha ou a média do seu estado.";
      });
    });
  });

  // ---- números em português
  window.BH = {
    cidades: cidades,
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
