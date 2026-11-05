"""Robô do Banco Central: dólar, euro, Selic, CDI, IPCA, IGP-M, INPC e poupança.

Usa a API pública do Sistema Gerenciador de Séries Temporais (SGS):
https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json
"""
import json
import sys
from datetime import date

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from comum import DADOS, baixar, ler_json, numero, salvar_json

SERIES = {
    # chave: (código SGS, descrição, modo)
    "dolar": (1, "Dólar comercial (PTAX venda), R$", "ultimos:500"),
    "euro": (21619, "Euro (PTAX venda), R$", "ultimos:500"),
    "selic": (432, "Meta da taxa Selic, % ao ano", "ultimos:900"),
    "cdi": (4389, "CDI anualizado, % ao ano", "ultimos:500"),
    "ipca": (433, "IPCA mensal, %", "desde:1995"),
    "ipca12": (13522, "IPCA acumulado em 12 meses, %", "ultimos:120"),
    "igpm": (189, "IGP-M mensal, %", "desde:1995"),
    "inpc": (188, "INPC mensal, %", "desde:1995"),
    "poupanca": (195, "Rendimento da poupança no mês, %", "ultimos:60"),
}


def _baixar_serie(codigo, modo):
    base = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
    tipo, valor = modo.split(":")
    if tipo == "ultimos":
        urls = [f"{base}/ultimos/{valor}?formato=json"]
    else:  # janelas de 10 anos (limite da API)
        urls, ano, hoje = [], int(valor), date.today()
        while ano <= hoje.year:
            fim = min(ano + 9, hoje.year)
            urls.append(f"{base}?formato=json&dataInicial=01/01/{ano}&dataFinal=31/12/{fim}")
            ano = fim + 1
    pontos = {}
    for url in urls:
        for p in json.loads(baixar(url)):
            d, m, a = p["data"].split("/")
            v = numero(p["valor"])
            if v is not None:
                pontos[f"{a}-{m}-{d}"] = v
    return sorted(pontos.items())


def main():
    destino = DADOS / "bcb.json"
    anterior = ler_json(destino, {})
    saida = {"atualizado": date.today().isoformat(), "series": {}}
    for chave, (codigo, desc, modo) in SERIES.items():
        try:
            pontos = _baixar_serie(codigo, modo)
            if not pontos:
                raise ValueError("série vazia")
            saida["series"][chave] = {"codigo": codigo, "descricao": desc, "pontos": pontos}
            print(f"[BCB] {chave}: {len(pontos)} pontos, último {pontos[-1]}")
        except Exception as e:
            print(f"[BCB] {chave}: falhou ({e}); mantendo dado anterior")
            if chave in anterior.get("series", {}):
                saida["series"][chave] = anterior["series"][chave]
    salvar_json(destino, saida)


if __name__ == "__main__":
    main()
