"""Robô de câmbio: cotação diária das principais moedas em reais.

Fonte principal: PTAX do Banco Central (boletim de fechamento, taxa de venda).
Reserva: taxas de referência do Banco Central Europeu (cruzadas com o real).
"""
import json
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from comum import DADOS, baixar, ler_json, salvar_json

# código ISO: (nome, símbolo, endereço da página, unidade exibida)
MOEDAS = {
    "USD": ("Dólar americano", "US$", "dolar-hoje", 1),
    "EUR": ("Euro", "€", "euro-hoje", 1),
    "GBP": ("Libra esterlina", "£", "libra-hoje", 1),
    "CHF": ("Franco suíço", "CHF", "franco-suico-hoje", 1),
    "JPY": ("Iene japonês", "¥", "iene-hoje", 100),
    "CNY": ("Yuan chinês", "¥", "yuan-hoje", 1),
    "CAD": ("Dólar canadense", "C$", "dolar-canadense-hoje", 1),
    "AUD": ("Dólar australiano", "A$", "dolar-australiano-hoje", 1),
    "ARS": ("Peso argentino", "$", "peso-argentino-hoje", 100),
}

OLINDA = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
          "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
          "?@moeda='{m}'&@dataInicial='{ini}'&@dataFinalCotacao='{fim}'&$format=json"
          "&$select=cotacaoVenda,dataHoraCotacao,tipoBoletim")


def ptax(moeda, dias=730):
    hoje = date.today()
    ini = hoje - timedelta(days=dias)
    url = OLINDA.format(m=moeda, ini=f"{ini:%m-%d-%Y}", fim=f"{hoje:%m-%d-%Y}")
    dados = json.loads(baixar(url, tentativas=2, timeout=60))["value"]
    pontos = {}
    for r in dados:
        if "FECHAMENTO" in str(r.get("tipoBoletim", "")).upper() and r.get("cotacaoVenda"):
            pontos[str(r["dataHoraCotacao"])[:10]] = round(float(r["cotacaoVenda"]), 6)
    return sorted(pontos.items())


def bce():
    """{moeda: [(data, reais por unidade)]} a partir das taxas do BCE (base euro)."""
    xml = baixar("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml", tentativas=2)
    raiz = ET.fromstring(xml)
    saida = {}
    for cubo in raiz.iter():
        data = cubo.attrib.get("time")
        if not data:
            continue
        taxas = {c.attrib["currency"]: float(c.attrib["rate"]) for c in cubo if "currency" in c.attrib}
        brl = taxas.get("BRL")
        if not brl:
            continue
        taxas["EUR"] = 1.0
        for m, por_euro in taxas.items():
            if m in MOEDAS:
                saida.setdefault(m, []).append((data, round(brl / por_euro, 6)))
    return {m: sorted(p) for m, p in saida.items()}


def main():
    destino = DADOS / "moedas.json"
    anterior = ler_json(destino, {}).get("moedas", {})
    saida, reserva = {}, None
    for codigo, (nome, simbolo, url, unidade) in MOEDAS.items():
        fonte, pontos = "PTAX/Banco Central", []
        try:
            pontos = ptax(codigo)
        except Exception as e:
            print(f"[MOEDAS] {codigo}: PTAX indisponível ({str(e)[:120]})")
        recente = pontos and pontos[-1][0] >= (date.today() - timedelta(days=7)).isoformat()
        if not recente:
            try:
                if reserva is None:
                    reserva = bce()
                if reserva.get(codigo):
                    pontos, fonte = reserva[codigo], "Banco Central Europeu (cruzada com o real)"
            except Exception as e:
                reserva = {}
                print(f"[MOEDAS] reserva do BCE indisponível ({str(e)[:120]})")
        if not pontos and codigo in anterior:
            saida[codigo] = anterior[codigo]
            print(f"[MOEDAS] {codigo}: mantendo dado anterior")
            continue
        if not pontos:
            print(f"[MOEDAS] {codigo}: sem dados")
            continue
        saida[codigo] = {"nome": nome, "simbolo": simbolo, "url": url, "unidade": unidade,
                         "fonte": fonte, "pontos": pontos}
        print(f"[MOEDAS] {codigo}: {len(pontos)} dias, último {pontos[-1]} ({fonte})")
    if saida:
        salvar_json(destino, {"atualizado": date.today().isoformat(), "moedas": saida})


if __name__ == "__main__":
    main()
