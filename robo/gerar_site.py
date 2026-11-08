"""Gera o site estático em ./public a partir dos dados coletados.

Uso: python robo/gerar_site.py
"""
import csv
import html
import re
import hashlib
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
    return f"R$\u00a0{txt}"


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
                     f'<text class="g-eixo" x="{me - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{html.escape(f(v).replace("R$\u00a0", "").replace("R$ ", ""))}</text>')
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
            s = sorted(series[k][p])
            d["var4"] = variacao(d["medio"], s[-5][1]) if len(s) >= 5 else None

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
    from datetime import timedelta
    proxima = (date.fromisoformat(fim) + timedelta(days=9)).isoformat()
    return {"inicio": ultima["semana_inicio"], "fim": fim, "anterior": anterior, "semanas": semanas, "proxima": proxima,
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


# ================================================================ trabalho (INSS, IRRF, 13º)
# Mesma conta de static/trabalho.js, para as tabelas prontas das páginas.
def _r2(x):
    return round(x + 1e-9, 2)


def calc_inss(bruto, R):
    total, ant = 0.0, 0.0
    for teto, aliq in R["inss"]["faixas"]:
        if bruto > ant:
            total += (min(bruto, teto) - ant) * aliq / 100
        ant = teto
    return _r2(total)


def calc_irrf(bruto, inss_v, R, dependentes=0):
    I = R["irrf"]
    legais = inss_v + dependentes * I["dependente"]
    deducao = max(legais, I["desconto_simplificado"])
    base = max(0.0, _r2(bruto - deducao))
    imposto = 0.0
    for lim, aliq, ded in I["faixas"]:
        if lim is None or base <= lim:
            imposto = max(0.0, _r2(base * aliq / 100 - ded))
            break
    d = I["reducao"]
    red = d["reducao_maxima"] if bruto <= d["isencao_ate"] else (d["a"] - d["b"] * bruto if bruto <= d["limite"] else 0)
    red = _r2(max(0.0, min(imposto, red)))
    return _r2(imposto - red)


def exemplos_trabalho(R):
    linhas = []
    for s in (R["salario_minimo"], 2000, 2500, 3000, 3500, 4000, 5000, 6000, 7000, 8000, 10000, 15000):
        i = calc_inss(s, R)
        ir = calc_irrf(s, i, R)
        linhas.append({"bruto": s, "inss": i, "irrf": ir, "liquido": _r2(s - i - ir),
                       "primeira": _r2(s / 2), "segunda": _r2(s / 2 - i - ir)})
    return linhas


# ================================================================ quanto rende
VALORES_RENDE = [1000, 2000, 5000, 10000, 20000, 30000, 50000, 100000, 200000, 500000, 1000000]
PRAZOS_RENDE = [(1, "1 mês"), (6, "6 meses"), (12, "1 ano"), (24, "2 anos"), (60, "5 anos")]


def _aliquota_ir(meses):
    dias = meses * 30
    return 0.225 if dias <= 180 else 0.20 if dias <= 360 else 0.175 if dias <= 720 else 0.15


def _mensal(anual):
    return (1 + anual / 100) ** (1 / 12) - 1


def simular_rende(valor, meses, bcb):
    """Rendimento líquido (sem aportes) de cada aplicação, com as taxas de hoje."""
    cdi, selic, poup = bcb["cdi"]["valor"], bcb["selic"]["valor"], bcb["poupanca"]["valor"]
    saida = []
    for nome, taxa_m, ir, custodia in (
        ("Poupança", poup / 100, False, False),
        ("CDB 100% do CDI", _mensal(cdi), True, False),
        ("LCI/LCA 90% do CDI", _mensal(cdi * 0.9), False, False),
        ("Tesouro Selic", _mensal(selic), True, True),
    ):
        bruto = valor * ((1 + taxa_m) ** meses - 1)
        if custodia:
            bruto -= max(0, valor - 10000) * 0.002 * meses / 12
        liquido = bruto * (1 - _aliquota_ir(meses)) if ir else bruto
        saida.append({"nome": nome, "ganho": round(liquido, 2), "total": round(valor + liquido, 2)})
    melhor = max(saida, key=lambda x: x["ganho"])
    for s in saida:
        s["melhor"] = s is melhor
    return saida


def nome_valor(v):
    if v >= 1000000:
        n = v // 1000000
        return f"{n} milhão" if n == 1 else f"{n} milhões"
    if v >= 1000:
        return f"{v // 1000} mil"
    return str(v)


# ================================================================ tabela FIPE
NOME_TIPO = {"carros": ("Carros", "carro"), "motos": ("Motos", "moto")}


ANO_MIN_FAMILIA = 2008


def montar_fipe():
    """{tipo: {"ref", "marcas": [ {nome, slug, url, modelos: [...]} ]}} a partir de dados/fipe/<tipo>.json."""
    saida = {}
    for tipo in ("carros", "motos"):
        base = ler_json(DADOS / "fipe" / f"{tipo}.json")
        if not base or not base.get("veiculos"):
            continue
        por_marca = defaultdict(lambda: defaultdict(list))
        for marca, modelo, cod, ano, comb, valor, anterior in base["veiculos"]:
            por_marca[marca][modelo].append({"ano": "Zero km" if ano == 32000 else str(ano), "ordem": ano,
                                             "combustivel": comb, "valor": valor, "codigo_fipe": cod,
                                             "var": variacao(valor, anterior)})
        marcas = []
        for marca, modelos_d in por_marca.items():
            nome_marca = marca.replace("VW - VolksWagen", "Volkswagen").replace("GM - Chevrolet", "Chevrolet")
            mslug = slug(nome_marca)
            modelos, usados = [], set()
            for modelo, anos in sorted(modelos_d.items(), key=lambda kv: kv[0].lower()):
                anos.sort(key=lambda x: -x["ordem"])
                oslug = slug(modelo)[:80].strip("-")
                n = 2
                while oslug in usados:
                    oslug = f"{slug(modelo)[:76]}-{n}"
                    n += 1
                usados.add(oslug)
                valores = [x["valor"] for x in anos]
                modelos.append({"nome": modelo, "slug": oslug, "anos": anos, "min": min(valores), "max": max(valores),
                                "url": f"/tabela-fipe/{tipo}/{mslug}/{oslug}/", "familia": modelo.split()[0].lower()})
            # famílias (Onix, Gol, CG...) e páginas família + ano, que são como as pessoas buscam
            fams = defaultdict(list)
            for mod in modelos:
                fams[mod["familia"]].append(mod)
            familias = []
            for fam, mods in sorted(fams.items()):
                fslug = slug(fam)
                if not fslug:
                    continue
                for mod in mods:
                    if mod["slug"] == fslug:
                        mod["slug"] = fslug + "-versao"
                        mod["url"] = f"/tabela-fipe/{tipo}/{mslug}/{mod['slug']}/"
                orig = mods[0]["nome"].split()[0]
                nome_fam = orig.title() if orig.isupper() and len(orig) > 2 and "-" not in orig and not any(ch.isdigit() for ch in orig) else orig
                anos_f = defaultdict(list)
                for mod in mods:
                    for a in mod["anos"]:
                        if a["ordem"] == 32000 or a["ordem"] >= ANO_MIN_FAMILIA:
                            anos_f[a["ordem"]].append({"mod": mod, "a": a})
                lista_anos = []
                for ordem in sorted(anos_f, reverse=True):
                    itens = sorted(anos_f[ordem], key=lambda x: x["a"]["valor"])
                    rot = "zero-km" if ordem == 32000 else str(ordem)
                    lista_anos.append({"ano": "Zero km" if ordem == 32000 else str(ordem), "slug": rot, "itens": itens,
                                       "min": itens[0]["a"]["valor"], "max": itens[-1]["a"]["valor"],
                                       "url": f"/tabela-fipe/{tipo}/{mslug}/{fslug}/{rot}/"})
                if not lista_anos:
                    continue
                f = {"nome": nome_fam, "slug": fslug, "url": f"/tabela-fipe/{tipo}/{mslug}/{fslug}/", "anos": lista_anos,
                     "versoes": len(mods), "min": min(x["min"] for x in lista_anos), "max": max(x["max"] for x in lista_anos)}
                familias.append(f)
                for mod in mods:
                    mod["fam"] = f
            marcas.append({"nome": nome_marca, "slug": mslug, "url": f"/tabela-fipe/{tipo}/{mslug}/", "modelos": modelos,
                           "familias": familias})
        marcas.sort(key=lambda x: x["nome"].lower())
        saida[tipo] = {"ref": base["referencia"], "marcas": marcas, "nome": NOME_TIPO[tipo][0],
                       "singular": NOME_TIPO[tipo][1], "total": sum(len(x["modelos"]) for x in marcas)}
    return saida


# ================================================================ moedas
def montar_moedas(bcb):
    dados = (ler_json(DADOS / "moedas.json") or {}).get("moedas", {})
    # reserva: dólar e euro da série do Banco Central já coletada
    nomes = {"USD": ("Dólar americano", "US$", "dolar-hoje", "dolar"), "EUR": ("Euro", "€", "euro-hoje", "euro")}
    for cod, (nome, simb, url, chave) in nomes.items():
        if cod not in dados and bcb and bcb["series"].get(chave):
            dados[cod] = {"nome": nome, "simbolo": simb, "url": url, "unidade": 1,
                          "fonte": "PTAX/Banco Central", "pontos": bcb["series"][chave]}
    saida = []
    for cod, d in dados.items():
        p = d["pontos"]
        if len(p) < 2:
            continue
        u = d.get("unidade", 1)
        data_ult, v = p[-1]
        alvo = (date.fromisoformat(data_ult) - __import__("datetime").timedelta(days=30)).isoformat()
        v30 = next((x for dd, x in reversed(p) if dd <= alvo), p[0][1])
        alvo_ano = (date.fromisoformat(data_ult) - __import__("datetime").timedelta(days=365)).isoformat()
        v365 = next((x for dd, x in reversed(p) if dd <= alvo_ano), None)
        saida.append({
            "codigo": cod, "nome": d["nome"], "simbolo": d["simbolo"], "unidade": u, "fonte": d.get("fonte", ""),
            "url": f"/{d['url']}/", "data": data_ult, "valor": v * u, "taxa": v,
            "var": variacao(v, p[-2][1]), "var30": variacao(v, v30), "var365": variacao(v, v365) if v365 else None,
            "grafico": [(date.fromisoformat(dd).strftime("%d/%m/%y"), x * u) for dd, x in p[-260:]],
        })
    ordem = ["USD", "EUR", "GBP", "CHF", "JPY", "CNY", "CAD", "AUD", "ARS"]
    saida.sort(key=lambda m: ordem.index(m["codigo"]) if m["codigo"] in ordem else 99)
    return saida


# ================================================================ dados da ANEEL
RESERVA_BANDEIRAS = {"Verde": 0.0, "Amarela": 1.885, "Vermelha Patamar 1": 4.463, "Vermelha Patamar 2": 7.877}
IMPOSTOS_ENERGIA = 25  # % estimado de ICMS + PIS/Cofins sobre a tarifa


def _bandeira(nome):
    from comum import normalizar
    n = normalizar(nome)
    if "ESCASSEZ" in n:
        return "Escassez Hídrica"
    if "VERMELHA" in n:
        return "Vermelha Patamar 2" if "2" in n else "Vermelha Patamar 1"
    if "AMARELA" in n:
        return "Amarela"
    if "VERDE" in n:
        return "Verde"
    return str(nome)


def montar_energia(aneel):
    from comum import normalizar
    from distribuidoras import PRINCIPAIS
    if not aneel:
        return None
    meses = [{"mes": b["mes"], "bandeira": _bandeira(b["bandeira"])} for b in aneel.get("bandeiras", [])]
    adic = {_bandeira(k): v for k, v in (aneel.get("adicional_100kwh") or {}).items()}
    adic.setdefault("Verde", 0.0)
    if not (adic.get("Amarela", 0) < adic.get("Vermelha Patamar 1", 0) < adic.get("Vermelha Patamar 2", 0)):
        adic = dict(RESERVA_BANDEIRAS)
    atual = meses[-1] if meses else None
    extra = (adic.get(atual["bandeira"], 0) / 100) if atual else 0  # R$ por kWh

    limite = date(date.today().year - 2, date.today().month, 1).isoformat()
    melhores = {}
    for t in aneel.get("tarifas", []):
        sig = str(t["distribuidora"]).strip()
        chave_n = normalizar(sig)
        if not sig or "NAO INFORMADO" in chave_n or t["vigencia"] < limite:
            continue
        if not (0.15 < t["kwh_sem_impostos"] < 2.5):
            continue
        if chave_n not in melhores or t["vigencia"] > melhores[chave_n]["vigencia"]:
            melhores[chave_n] = t
    lista = []
    for chave_n, t in melhores.items():
        nome, uf = PRINCIPAIS.get(chave_n, (t["distribuidora"], None))
        kwh = t["kwh_sem_impostos"]
        com = (kwh + extra) * (1 + IMPOSTOS_ENERGIA / 100)
        d = {"sigla": t["distribuidora"], "nome": nome, "uf": uf, "principal": chave_n in PRINCIPAIS,
             "vigencia": t["vigencia"], "kwh": kwh, "kwh_final": round(com, 4), "slug": slug(nome)}
        d["url"] = f"/conta-de-luz/{d['slug']}/" if d["principal"] else None
        lista.append(d)
    principais = sorted([d for d in lista if d["principal"]], key=lambda d: (d["uf"], d["nome"]))
    outras = sorted([d for d in lista if not d["principal"]], key=lambda d: d["nome"].lower())
    media = round(sum(d["kwh"] for d in principais) / len(principais), 5) if principais else None
    ranking = sorted(principais, key=lambda d: d["kwh"])
    for i, d in enumerate(ranking, 1):
        d["posicao"], d["total"] = i, len(ranking)
    return {"meses": meses, "atual": atual, "adicional": adic, "extra_kwh": extra, "impostos": IMPOSTOS_ENERGIA,
            "principais": principais, "outras": outras, "media": media, "ranking": ranking,
            "oficial": bool(aneel.get("adicional_oficial"))}


# ================================================================ geração
def main():
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    (SAIDA / "static").mkdir(parents=True)
    for arq in (RAIZ / "static").iterdir():
        shutil.copy(arq, SAIDA / "static" / arq.name)
    # Arquivos que precisam ficar na raiz do site (ex.: verificação do Google)
    if (RAIZ / "raiz").exists():
        for arq in (RAIZ / "raiz").iterdir():
            shutil.copy(arq, SAIDA / arq.name)

    comb = montar_combustiveis()
    bcb = montar_bcb()
    aneel = ler_json(DADOS / "aneel.json") or {}
    energia = montar_energia(aneel)
    moedas = montar_moedas(bcb)
    regras = ler_json(RAIZ / "regras.json")
    fipe = montar_fipe()
    hoje = date.today().isoformat()

    env = Environment(loader=FileSystemLoader(RAIZ / "templates"), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters.update(brl=brl, num=num, data_br=data_br, seta=seta, json=lambda o: Markup(json.dumps(o, ensure_ascii=False)))
    env.globals.update(cfg=CONFIG, PRODUTOS=PRODUTOS, UFS=UFS, grafico=grafico, serie_semanal=serie_semanal,
                       comb=comb, bcb=bcb, aneel=aneel, ano=date.today().year, regra=CONFIG["regra_etanol"],
                       tem_energia=bool(energia and (energia["atual"] or energia["principais"])), energia=energia, moedas=moedas, regras=regras, fipe=fipe,
                       exemplos_trabalho=exemplos_trabalho(regras) if regras else [],
                       calc_inss_teto=calc_inss(regras["inss"]["faixas"][-1][0], regras) if regras else 0,
                       versao=hashlib.md5(((RAIZ / "static" / "estilo.css").read_bytes() + (RAIZ / "static" / "app.js").read_bytes())).hexdigest()[:8])
    mapa = []
    prefixo = CONFIG.get("caminho_base", "").rstrip("/")

    def com_prefixo(pagina_html):
        """Enxuga o HTML (tira recuo e linhas vazias) e, se o site estiver numa subpasta, ajusta os links."""
        pagina_html = "\n".join(l.strip() for l in pagina_html.splitlines() if l.strip())
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
    (SAIDA / "static" / "cidades.json").write_text(json.dumps(cidades_js, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    env.globals["rendes"] = []

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
        tem = lambda k: bcb.get(k, {}).get("valor") is not None
        if tem("selic"):
            pagina("/selic-hoje/", "indicador.html", 0.8, ind="selic")
        if tem("cdi"):
            pagina("/cdi-hoje/", "indicador.html", 0.7, ind="cdi")
        if tem("ipca12"):
            pagina("/ipca-inflacao/", "indicador.html", 0.8, ind="ipca")
        if tem("cdi") and tem("selic"):
            pagina("/calculadoras/rendimento/", "calc_rendimento.html", 0.8)
        if tem("cdi") and tem("selic") and tem("poupanca"):
            rendes = []
            for v in VALORES_RENDE:
                url = f"/quanto-rende/{slug(nome_valor(v))}-reais/"
                rendes.append({"valor": v, "nome": nome_valor(v), "url": url})
            env.globals["rendes"] = rendes
            env.globals["simular"] = lambda v, m: simular_rende(v, m, bcb)
            for r in rendes:
                tabela = [(rot, m, simular_rende(r["valor"], m, bcb)) for m, rot in PRAZOS_RENDE]
                pagina(r["url"], "quanto_rende.html", 0.7, r=r, tabela=tabela)
            pagina("/quanto-rende/", "quanto_rende_indice.html", 0.8)
        if bcb["series"].get("ipca"):
            pagina("/calculadoras/corrigir-pela-inflacao/", "calc_inflacao.html", 0.8)
    if comb and comb["brasil"]["produtos"].get("glp"):
        pagina("/gas-de-cozinha/", "gas.html", 0.9)
    if fipe:
        pagina("/tabela-fipe/", "fipe_inicio.html", 0.9)
        busca = []
        for tipo, info in fipe.items():
            for marca in info["marcas"]:
                pagina(marca["url"], "fipe_marca.html", 0.7, tipo=tipo, info=info, marca=marca)
                for mod in marca["modelos"]:
                    irmaos = [x for x in marca["modelos"] if x["familia"] == mod["familia"] and x is not mod][:12]
                    pagina(mod["url"], "fipe_modelo.html", 0.6, tipo=tipo, info=info, marca=marca, mod=mod, irmaos=irmaos)
                    busca.append([marca["nome"], mod["nome"], mod["url"], round(mod["anos"][0]["valor"])])
                for fam in marca["familias"]:
                    pagina(fam["url"], "fipe_familia.html", 0.7, tipo=tipo, info=info, marca=marca, fam=fam)
                    for ano in fam["anos"]:
                        pagina(ano["url"], "fipe_familia_ano.html", 0.6, tipo=tipo, info=info, marca=marca, fam=fam, fa=ano)
                    busca.insert(0, [marca["nome"], fam["nome"] + " (todas as versões)", fam["url"], round(fam["anos"][0]["min"])])
        (SAIDA / "static" / "fipe-busca.json").write_text(json.dumps(busca, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if moedas:
        pagina("/moedas/", "moedas.html", 0.9)
        for m in moedas:
            pagina(m["url"], "moeda.html", 0.8, m=m)
    if comb:
        pagina("/calculadoras/custo-da-viagem/", "calc_viagem.html", 0.7)
    if env.globals["tem_energia"]:
        pagina("/conta-de-luz/", "energia.html", 0.8)
        for d in energia["principais"]:
            vizinhas = [o for o in energia["principais"] if o["uf"] == d["uf"] and o is not d]
            pagina(d["url"], "energia_dist.html", 0.7, d=d, vizinhas=vizinhas)
    if regras:
        pagina("/calculadoras/salario-liquido/", "calc_salario.html", 0.9)
        pagina("/calculadoras/decimo-terceiro/", "calc_13.html", 0.9)
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
