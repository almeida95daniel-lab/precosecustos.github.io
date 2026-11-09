"""Robô do Banco Central: dólar, euro, Selic, CDI, IPCA, IGP-M, INPC e poupança.

Usa a API pública do Sistema Gerenciador de Séries Temporais (SGS):
https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json
"""
import json
import sys
import time
from datetime import date

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from comum import DADOS, baixar, ler_json, numero, salvar_json

SERIES = {
    # chave: (código SGS, descrição, modo)
    "dolar": (1, "Dólar comercial (PTAX venda), R$", "anos:2"),
    "euro": (21619, "Euro (PTAX venda), R$", "anos:2"),
    "selic": (432, "Meta da taxa Selic, % ao ano", "anos:4"),
    "cdi": (4389, "CDI anualizado, % ao ano", "anos:3"),
    "ipca": (433, "IPCA mensal, %", "desde:1995"),
    "ipca12": (13522, "IPCA acumulado em 12 meses, %", "anos:10"),
    "igpm": (189, "IGP-M mensal, %", "desde:1995"),
    "inpc": (188, "INPC mensal, %", "desde:1995"),
    "poupanca": (195, "Rendimento da poupança no mês, %", "anos:2"),
}


def _ler_json(url, tentativas=3):
    """Baixa e lê o JSON. A API às vezes responde 200 com corpo vazio ou HTML; tenta de novo."""
    ultimo = None
    for i in range(tentativas):
        try:
            dados = json.loads(baixar(url))
            if isinstance(dados, dict) and "erro" in str(dados).lower():
                raise ValueError(f"resposta de erro: {str(dados)[:120]}")
            return dados
        except (ValueError, json.JSONDecodeError) as e:
            ultimo = e
            time.sleep(2 * (i + 1))
    raise ValueError(f"JSON inválido após {tentativas} tentativas: {ultimo}")


def _ultimos(codigo, n=20):
    """Reserva: só os últimos pontos (consulta leve, costuma passar quando a longa falha)."""
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}?formato=json"
    pontos = {}
    for p in _ler_json(url):
        d, m, a = p["data"].split("/")
        v = numero(p["valor"])
        if v is not None:
            pontos[f"{a}-{m}-{d}"] = v
    return pontos


def _ptax_olinda(chave):
    """Reserva para dólar e euro: serviço PTAX (Olinda) do próprio Banco Central."""
    from coletar_moedas import ptax
    return dict(ptax({"dolar": "USD", "euro": "EUR"}[chave], dias=30))


def _completar(anteriores, novos):
    """Junta pontos novos aos que já tínhamos (os novos prevalecem)."""
    junto = dict(anteriores or [])
    junto.update(novos)
    return sorted(junto.items())


def _baixar_serie(codigo, modo):
    base = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
    tipo, valor = modo.split(":")
    if tipo == "anos":  # a API recusa /ultimos/N com N grande; usa intervalo de datas
        hoje = date.today()
        ini = date(hoje.year - int(valor), hoje.month, 1)
        urls = [f"{base}?formato=json&dataInicial={ini:%d/%m/%Y}&dataFinal={hoje:%d/%m/%Y}"]
    else:  # janelas de 10 anos (limite da API)
        urls, ano, hoje = [], int(valor), date.today()
        while ano <= hoje.year:
            fim = min(ano + 9, hoje.year)
            urls.append(f"{base}?formato=json&dataInicial=01/01/{ano}&dataFinal=31/12/{fim}")
            ano = fim + 1
    pontos = {}
    for url in urls:
        for p in _ler_json(url):
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
            print(f"[BCB] {chave}: consulta completa falhou ({e}); tentando reservas")
            velho = anterior.get("series", {}).get(chave, {}).get("pontos", [])
            reservas = [("últimos pontos do SGS", lambda: _ultimos(codigo))]
            if chave in ("dolar", "euro"):
                reservas.append(("PTAX/Olinda", lambda: _ptax_olinda(chave)))
            ok = False
            for nome, func in reservas:
                try:
                    novos = func()
                    if not novos:
                        raise ValueError("vazio")
                    pontos = _completar(velho, novos)
                    saida["series"][chave] = {"codigo": codigo, "descricao": desc, "pontos": pontos}
                    print(f"[BCB] {chave}: recuperado pela reserva ({nome}), último {pontos[-1]}")
                    ok = True
                    break
                except Exception as e2:
                    print(f"[BCB] {chave}: reserva {nome} falhou ({e2})")
            if not ok:
                print(f"::warning::[BCB] {chave}: todas as fontes falharam; mantendo dado anterior")
                if chave in anterior.get("series", {}):
                    saida["series"][chave] = anterior["series"][chave]
    salvar_json(destino, saida)


if __name__ == "__main__":
    main()
