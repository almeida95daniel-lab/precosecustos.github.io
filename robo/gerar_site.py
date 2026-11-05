"""Gera o site estático em ./public a partir dos dados coletados.

Uso: python robo/gerar_site.py
"""
import csv
import html
import re
import json
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from comum import CONFIG, DADOS, PRODUTOS, RAIZ, SAIDA_SITE, UFS, ler_json, slug

SAIDA = SAIDA_SITE
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


# ================================================================ formatação
def brl(v, casas=2):
    if v is None:
        return "–"
    txt = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {txt}"


def num(v, casas=2):
    if v is None:
        return "–"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(iso, formato="curta"):
    d = date.fromisoformat(str(iso)[:10])
    if formato == "longa":
        return f"{d.day} de {MESES[d.month - 1]} de {d.year}"
    if formato == "mes":
        return f"{MESES[d.month - 1]} de {d.year}"
    return d.strftime("%d/%m/%Y")


def variacao(atual, anterior):
    if atual is None or not anterior:
        return None
    return round((atual / anterior - 1) * 100, 2)


def seta(v, unidade="%"):
    """Variação com seta + palavra: a cor nunca carrega o sentido sozinha."""
    if v is None:
        return Markup('<span class="var">sem comparação</span>')
    if abs(v) < 0.005:
        return Markup('<span class="var var-igual">= estável</span>')
    cls, simb, pal = ("var-alta", "▲", "subiu") if v > 0 else ("var-baixa", "▼", "caiu")
    return Markup(f'<span class="var {cls}">{simb} {pal} {num(abs(v))}{unidade}</span>')


# ================================================================ gráfico SVG
def grafico(pontos, fmt="brl", casas=2, titulo="", degrau=False):
    """Linha única em SVG com camada de hover (ver static/app.js) e tabela de dados."""
    pontos = [(r, v) for r, v in pontos if v is not None]
    if len(pontos) < 2:
        return Markup("")
    L, A, me, md, mt, mb = 680, 240, 52, 16, 14, 30
    vs = [v for _, v in pontos]
    lo, hi = min(vs), max(vs)
    folga = (hi - lo) * 0.12 or abs(hi) * 0.02 or 1
    lo, hi = lo - folga, hi + folga
    w, h = L - me - md, A - mt - mb
    n = len(pontos)

    def x(i):
        return me + w * i / (n - 1)

    def y(v):
        return mt + h * (1 - (v - lo) / (hi - lo))

    def f(v):
        return brl(v, casas) if fmt == "brl" else (num(v, casas) + ("%" if fmt == "pct" else ""))

    traco = []
    for i, (_, v) in enumerate(pontos):
        if degrau and i:
            traco.append(f"L{x(i):.1f},{y(pontos[i - 1][1]):.1f}")
        traco.append(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}")
    grade = []
    for k in range(4):
        v = lo + (hi - lo) * (k + 0.5) / 4
        grade.append(f'<line class="g-grade" x1="{me}" x2="{L - md}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                     f'<text class="g-eixo" x="{me - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{html.escape(f(v).replace("R$ ", ""))}</text>')
    marcas = sorted({0, n - 1, *[round((n - 1) * k / 4) for k in range(1, 4)]})
    eixo_x = "".join(f'<text class="g-eixo" x="{x(i):.1f}" y="{A - 8}" text-anchor="{"start" if i == 0 else "end" if i == n - 1 else "middle"}">{html.escape(pontos[i][0])}</text>' for i in marcas)
    ux, uy = x(n - 1), y(vs[-1])
    dados = json.dumps([[r, f(v)] for r, v in pontos], ensure_ascii=False)
    linhas_tabela = "".join(f"<tr><td>{html.escape(r)}</td><td>{html.escape(f(v))}</td></tr>" for r, v in reversed(pontos))
    svg = (f'<figure class="grafico"><figcaption>{html.escape(titulo)}</figcaption>'
           f'<div class="g-area" data-pontos="{html.escape(dados)}" data-me="{me}" data-md="{md}" data-largura="{L}">'
           f'<svg viewBox="0 0 {L} {A}" role="img" aria-label="{html.escape(titulo)}">'
           f'{"".join(grade)}<path class="g-linha" d="{"".join(traco)}"/>'
           f'<circle class="g-ponto" cx="{ux:.1f}" cy="{uy:.1f}" r="4.5"/>'
           f'<line class="g-mira" x1="0" x2="0" y1="{mt}" y2="{mt + h}" visibility="hidden"/>'
           f'<circle class="g-foco" r="5" visibility="hidden"/>'
           f'{eixo_x}</svg><div class="g-dica" hidden></div></div>'
           f'<details class="g-tabela"><summary>Ver os números em tabela</summary>'
           f'<table><thead><tr><th>Período</th><th>Valor</th></tr></thead><tbody>{linhas_tabela}</tbody></table></details></figure>')
    return Markup(svg)


# ================================================================ dados da ANP
def montar_combustiveis():
    ultima = ler_json(DADOS / "anp" / "ultima.json")
    caminho = DADOS / "anp" / "historico.csv"
    if not ultima or not caminho.exists():
        return None
    with caminho.open(encoding="utf-8") as f:
        hist = list(csv.DictReader(f))
    semanas = sorted({h["semana_fim"] for h in hist})
    fim = ultima["semana_fim"]
    anterior = max((s for s in semanas if s < fim), default=None)

    def chave(h):
        return (h["nivel"], h["uf"], h["municipio"])

    series = defaultdict(lambda: defaultdict(list))  # chave -> produto -> [(semana, medio)]
    atual, previo = defaultdict(dict), defaultdict(dict)
    for h in hist:
        k = chave(h)
        medio = float(h["medio"])
        series[k][h["produto"]].append((h["semana_fim"], medio))
        if h["semana_fim"] == fim:
            atual[k][h["produto"]] = {
                "medio": medio, "postos": int(h["postos"] or 0),
                "minimo": float(h["minimo"]) if h["minimo"] else None,
                "maximo": float(h["maximo"]) if h["maximo"] else None,
            }
        elif h["semana_fim"] == anterior:
            previo[k][h["produto"]] = medio
    for k, prods in atual.items():
        for p, d in prods.items():
            d["var"] = variacao(d["medio"], previo[k].get(p))

    postos = (ler_json(DADOS / "anp" / "postos.json") or {})
    postos = postos.get("cidades", {}) if postos.get("semana_fim") == fim else {}

    from comum import normalizar
    ibge = ler_json(DADOS / "ibge_municipios.json") or {}

    def nome_oficial(uf, mun):
        return ibge.get(f"{uf}|{normalizar(mun).replace('-', ' ')}", mun)

    cidades = []
    for (nivel, uf, mun), prods in atual.items():
        if nivel != "municipio":
            continue
        c = {"uf": uf, "nome": nome_oficial(uf, mun), "slug": slug(mun), "estado": UFS[uf],
             "url": f"/combustivel/{uf.lower()}/{slug(mun)}/", "produtos": prods,
             "serie": series[(nivel, uf, mun)], "postos": postos.get(f"{uf}|{mun}", {})}
        g, e = prods.get("gasolina"), prods.get("etanol")
        c["razao"] = round(e["medio"] / g["medio"], 3) if g and e else None
        cidades.append(c)
    cidades.sort(key=lambda c: (c["uf"], c["slug"]))

    estados = {}
    for uf in UFS:
        prods = atual.get(("estado", uf, ""), {})
        lista = [c for c in cidades if c["uf"] == uf]
        if not prods and not lista:
            continue
        g, e = prods.get("gasolina"), prods.get("etanol")
        estados[uf] = {"uf": uf, "nome": UFS[uf], "url": f"/combustivel/{uf.lower()}/", "produtos": prods,
                       "serie": series[("estado", uf, "")], "cidades": lista,
                       "razao": round(e["medio"] / g["medio"], 3) if g and e else None}
        # posição de cada cidade no estado (gasolina)
        com_g = sorted([c for c in lista if "gasolina" in c["produtos"]], key=lambda c: c["produtos"]["gasolina"]["medio"])
        for i, c in enumerate(com_g, 1):
            c["pos_estado"], c["total_estado"] = i, len(com_g)

    brasil = {"produtos": atual.get(("brasil", "", ""), {}), "serie": series[("brasil", "", "")]}
    return {"inicio": ultima["semana_inicio"], "fim": fim, "anterior": anterior, "semanas": semanas,
            "cidades": cidades, "estados": estados, "brasil": brasil}


def serie_semanal(serie, produto, ultimas=52):
    return [(date.fromisoformat(s).strftime("%d/%m/%y"), v) for s, v in serie.get(produto, [])[-ultimas:]]


# ================================================================ dados do BCB
def montar_bcb():
    b = ler_json(DADOS / "bcb.json")
    if not b or not b.get("series"):
        return None
    s = {k: v["pontos"] for k, v in b["series"].items()}
    out = {"atualizado": b["atualizado"], "series": s}

    def ultimo(k):
        return s[k][-1] if s.get(k) else (None, None)

    for k in ("dolar", "euro"):
        if s.get(k):
            (d1, v1), (_, v0) = s[k][-1], s[k][-2]
            out[k] = {"data": d1, "valor": v1, "var": variacao(v1, v0),
                      "grafico": [(date.fromisoformat(d).strftime("%d/%m/%y"), v) for d, v in s[k][-260:]]}
    for k in ("selic", "cdi", "ipca12", "poupanca"):
        d, v = ultimo(k)
        out[k] = {"data": d, "valor": v}
    if s.get("selic"):
        # Série diária da meta -> um ponto por mês (último dia útil)
        mensal = {}
        for d, v in s["selic"]:
            mensal[d[:7]] = v
        out["selic"]["grafico"] = [(f"{m[5:]}/{m[2:4]}", v) for m, v in list(mensal.items())[-36:]]
    if s.get("cdi"):
        mensal = {}
        for d, v in s["cdi"]:
            mensal[d[:7]] = v
        out["cdi"]["grafico"] = [(f"{m[5:]}/{m[2:4]}", v) for m, v in list(mensal.items())[-24:]]
    if s.get("ipca12"):
        out["ipca12"]["grafico"] = [(f"{d[5:7]}/{d[2:4]}", v) for d, v in s["ipca12"][-60:]]
    if s.get("ipca"):
        d, v = s["ipca"][-1]
        out["ipca_mes"] = {"data": d, "valor": v}
        out["ipca_ano"] = round((_acumular([x for dd, x in s["ipca"] if dd[:4] == d[:4]]) - 1) * 100, 2)
    return out


def _acumular(taxas):
    f = 1.0
    for t in taxas:
        f *= 1 + t / 100
    return f


# ================================================================ geração
def main():
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    (SAIDA / "static").mkdir(parents=True)
    for arq in (RAIZ / "static").iterdir():
        shutil.copy(arq, SAIDA / "static" / arq.name)

    comb = montar_combustiveis()
    bcb = montar_bcb()
    aneel = ler_json(DADOS / "aneel.json") or {}
    hoje = date.today().isoformat()

    env = Environment(loader=FileSystemLoader(RAIZ / "templates"), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters.update(brl=brl, num=num, data_br=data_br, seta=seta, json=lambda o: Markup(json.dumps(o, ensure_ascii=False)))
    env.globals.update(cfg=CONFIG, PRODUTOS=PRODUTOS, UFS=UFS, grafico=grafico, serie_semanal=serie_semanal,
                       comb=comb, bcb=bcb, aneel=aneel, ano=date.today().year, regra=CONFIG["regra_etanol"],
                       tem_energia=bool(aneel.get("bandeiras") or aneel.get("tarifas")))
    mapa = []
    prefixo = CONFIG.get("caminho_base", "").rstrip("/")

    def com_prefixo(pagina_html):
        """Site publicado numa subpasta (ex.: usuario.github.io/projeto): ajusta links internos."""
        if not prefixo:
            return pagina_html
        return re.sub(r'((?:href|src|action)=")/(?!/)', r"\1" + prefixo + "/", pagina_html)

    def pagina(url, modelo, prioridade=0.6, **ctx):
        destino = SAIDA / url.strip("/") / "index.html" if url != "/" else SAIDA / "index.html"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(com_prefixo(env.get_template(modelo).render(url=url, **ctx)), encoding="utf-8")
        mapa.append((url, prioridade))

    # Lista leve de cidades (busca e calculadoras)
    cidades_js = []
    if comb:
        cidades_js = [{"n": c["nome"], "uf": c["uf"], "u": prefixo + c["url"],
                       **{p: round(d["medio"], 2) for p, d in c["produtos"].items() if p in ("gasolina", "etanol", "diesel_s10", "diesel", "gnv")}}
                      for c in comb["cidades"]]
    env.globals["cidades_js"] = cidades_js

    pagina("/", "inicio.html", 1.0)
    if comb:
        pagina("/combustivel/", "comb_brasil.html", 0.9)
        pagina("/combustivel/etanol-ou-gasolina/", "etanol.html", 0.9)
        for uf, est in comb["estados"].items():
            pagina(est["url"], "comb_estado.html", 0.8, est=est)
            for c in est["cidades"]:
                vizinhas = sorted([o for o in est["cidades"] if o is not c and "gasolina" in o["produtos"]],
                                  key=lambda o: o["produtos"]["gasolina"]["medio"])[:6]
                pagina(c["url"], "comb_cidade.html", 0.8, c=c, est=est, vizinhas=vizinhas)
    if bcb:
        if bcb.get("dolar"):
            pagina("/dolar-hoje/", "moeda.html", 0.9, m=bcb["dolar"], nome="Dólar", simbolo="US$", codigo="USD")
        if bcb.get("euro"):
            pagina("/euro-hoje/", "moeda.html", 0.8, m=bcb["euro"], nome="Euro", simbolo="€", codigo="EUR")
        tem = lambda k: bcb.get(k, {}).get("valor") is not None
        if tem("selic"):
            pagina("/selic-hoje/", "indicador.html", 0.8, ind="selic")
        if tem("cdi"):
            pagina("/cdi-hoje/", "indicador.html", 0.7, ind="cdi")
        if tem("ipca12"):
            pagina("/ipca-inflacao/", "indicador.html", 0.8, ind="ipca")
        if tem("cdi") and tem("selic"):
            pagina("/calculadoras/rendimento/", "calc_rendimento.html", 0.8)
        if bcb["series"].get("ipca"):
            pagina("/calculadoras/corrigir-pela-inflacao/", "calc_inflacao.html", 0.8)
    if comb:
        pagina("/calculadoras/custo-da-viagem/", "calc_viagem.html", 0.7)
    if env.globals["tem_energia"]:
        pagina("/conta-de-luz/", "energia.html", 0.8)
    pagina("/calculadoras/", "calculadoras.html", 0.7)
    pagina("/sobre/", "sobre.html", 0.3)
    pagina("/privacidade/", "privacidade.html", 0.2)

    (SAIDA / "404.html").write_text(com_prefixo(env.get_template("404.html").render(url="/404")), encoding="utf-8")
    base = CONFIG["url_base"].rstrip("/")
    (SAIDA / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"<url><loc>{base}{u}</loc><lastmod>{hoje}</lastmod><priority>{p}</priority></url>\n" for u, p in mapa)
        + "</urlset>\n", encoding="utf-8")
    (SAIDA / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    if CONFIG.get("adsense_cliente"):
        pub = CONFIG["adsense_cliente"].replace("ca-", "")
        (SAIDA / "ads.txt").write_text(f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8")
    if CONFIG.get("dominio_proprio"):
        (SAIDA / "CNAME").write_text(CONFIG["dominio_proprio"] + "\n", encoding="utf-8")
    (SAIDA / ".nojekyll").write_text("", encoding="utf-8")
    print(f"[SITE] {len(mapa)} páginas geradas em {SAIDA} ({datetime.now():%H:%M})")


if __name__ == "__main__":
    main()
