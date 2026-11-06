/* Cálculos trabalhistas (INSS, IRRF, salário líquido e 13º). As tabelas vêm de regras.json. */
(function (raiz) {
  function r2(x) { return Math.round((x + 1e-9) * 100) / 100; }

  function inss(bruto, R) {
    var total = 0, anterior = 0;
    R.inss.faixas.forEach(function (f) {
      var teto = f[0], aliq = f[1] / 100;
      if (bruto > anterior) total += (Math.min(bruto, teto) - anterior) * aliq;
      anterior = teto;
    });
    return r2(total);
  }

  function tabelaIR(base, R) {
    if (base <= 0) return 0;
    var fx = R.irrf.faixas;
    for (var i = 0; i < fx.length; i++) {
      if (fx[i][0] === null || base <= fx[i][0]) return Math.max(0, r2(base * fx[i][1] / 100 - fx[i][2]));
    }
    return 0;
  }

  function reducao(brutoTributavel, imposto, R) {
    var d = R.irrf.reducao, v = 0;
    if (brutoTributavel <= d.isencao_ate) v = d.reducao_maxima;
    else if (brutoTributavel <= d.limite) v = d.a - d.b * brutoTributavel;
    return r2(Math.max(0, Math.min(imposto, v)));
  }

  /* Imposto do mês. opcoes: {dependentes, pensao, simplificado: true|false} */
  function irrf(bruto, inssValor, opcoes, R) {
    opcoes = opcoes || {};
    var legais = inssValor + (opcoes.dependentes || 0) * R.irrf.dependente + (opcoes.pensao || 0);
    var usarSimpl = opcoes.simplificado !== false && R.irrf.desconto_simplificado > legais;
    var deducao = usarSimpl ? R.irrf.desconto_simplificado : legais;
    var base = Math.max(0, r2(bruto - deducao));
    var imposto = tabelaIR(base, R);
    var red = reducao(bruto, imposto, R);
    return { base: base, deducao: r2(deducao), simplificado: usarSimpl, tabela: imposto, reducao: red, valor: r2(imposto - red) };
  }

  function salarioLiquido(o, R) {
    var bruto = o.bruto || 0;
    var i = inss(bruto, R);
    var ir = irrf(bruto, i, { dependentes: o.dependentes, pensao: o.pensao }, R);
    var vt = o.vt ? r2(bruto * 0.06) : 0;
    var outros = r2((o.outros || 0) + (o.pensao || 0));
    return { bruto: bruto, inss: i, irrf: ir, vt: vt, outros: outros, liquido: r2(bruto - i - ir.valor - vt - outros) };
  }

  /* 13º: imposto exclusivo na fonte, calculado separado do salário de dezembro. */
  function decimoTerceiro(o, R) {
    var meses = Math.max(0, Math.min(12, o.meses || 0));
    var bruto = r2((o.salario + (o.media || 0)) * meses / 12);
    var i = inss(bruto, R);
    var ir = irrf(bruto, i, { dependentes: o.dependentes, pensao: o.pensao }, R);
    var primeira = o.adiantado != null ? o.adiantado : r2(bruto / 2);
    var segunda = r2(bruto - primeira - i - ir.valor - (o.pensao || 0));
    return { bruto: bruto, meses: meses, inss: i, irrf: ir, primeira: primeira, segunda: segunda, liquido: r2(primeira + segunda) };
  }

  var api = { inss: inss, irrf: irrf, tabelaIR: tabelaIR, salarioLiquido: salarioLiquido, decimoTerceiro: decimoTerceiro };
  if (typeof module !== "undefined") module.exports = api; else raiz.Trabalho = api;
})(this);
