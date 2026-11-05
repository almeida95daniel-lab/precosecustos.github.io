"""Cria dados de EXEMPLO (fictícios) no mesmo formato das fontes oficiais,
para testar o robô e ver o site sem acesso à internet.

Uso:
  BH_DADOS=/tmp/dados_teste BH_SAIDA=/tmp/site_teste python teste/gerar_exemplo.py
"""
import json
import os
import random
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import openpyxl

RAIZ = Path(__file__).resolve().parent.parent
DADOS = Path(os.environ["BH_DADOS"])
TMP = DADOS.parent / "planilhas_exemplo"
random.seed(7)

CIDADES = {
    "SAO PAULO": ["SAO PAULO", "CAMPINAS", "SANTOS", "RIBEIRAO PRETO", "SAO JOSE DOS CAMPOS", "SOROCABA"],
    "SANTA CATARINA": ["JOINVILLE", "FLORIANOPOLIS", "BLUMENAU", "ITAJAI", "CHAPECO", "CRICIUMA"],
    "PARANA": ["CURITIBA", "LONDRINA", "MARINGA", "PONTA GROSSA"],
    "MINAS GERAIS": ["BELO HORIZONTE", "UBERLANDIA", "JUIZ DE FORA", "MONTES CLAROS"],
    "RIO DE JANEIRO": ["RIO DE JANEIRO", "NITEROI", "PETROPOLIS"],
    "BAHIA": ["SALVADOR", "FEIRA DE SANTANA"],
    "GOIAS": ["GOIANIA", "ANAPOLIS"],
    "DISTRITO FEDERAL": ["BRASILIA"],
}
BASE = {"GASOLINA COMUM": 6.25, "GASOLINA ADITIVADA": 6.45, "ETANOL HIDRATADO": 4.35,
        "OLEO DIESEL S10": 6.05, "OLEO DIESEL": 5.95, "GNV": 4.80, "GLP": 108.0}
ETANOL_FORTE = {"SAO PAULO", "GOIAS", "MINAS GERAIS", "PARANA"}
COLS = ["DATA INICIAL", "DATA FINAL", "ESTADO", "MUNICÍPIO", "PRODUTO", "NÚMERO DE POSTOS PESQUISADOS",
        "UNIDADE DE MEDIDA", "PREÇO MÉDIO REVENDA", "DESVIO PADRÃO REVENDA", "PREÇO MÍNIMO REVENDA",
        "PREÇO MÁXIMO REVENDA", "COEF DE VARIAÇÃO REVENDA"]


def preco(prod, uf, cidade, semana):
    p = BASE[prod] * (1 + 0.04 * (hash(uf) % 7 - 3) / 3) * (1 + 0.02 * (hash(cidade) % 5 - 2) / 2)
    if prod.startswith("ETANOL") and uf in ETANOL_FORTE:
        p *= 0.92
    p *= 1 + 0.004 * semana + random.uniform(-0.006, 0.006)
    return round(p, 2)


def cabecalho(ws, titulo):
    ws.append(["AGÊNCIA NACIONAL DO PETRÓLEO, GÁS NATURAL E BIOCOMBUSTÍVEIS - ANP"])
    ws.append(["SUPERINTENDÊNCIA DE DEFESA DA CONCORRÊNCIA, ESTUDOS E REGULAÇÃO ECONÔMICA"])
    ws.append(["SISTEMA DE LEVANTAMENTO DE PREÇOS"])
    ws.append([titulo])
    ws.append([])
    ws.append([])


def resumo(ini, fim, k):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    brasil, estados = {}, {}
    ws = wb.create_sheet("MUNICIPIOS")
    cabecalho(ws, "SÍNTESE SEMANAL DOS PREÇOS PRATICADOS - MUNICÍPIOS")
    ws.append(COLS)
    for uf, cidades in CIDADES.items():
        for c in cidades:
            for prod in BASE:
                if prod in ("GNV",) and c not in ("SAO PAULO", "RIO DE JANEIRO", "CURITIBA", "BELO HORIZONTE", "SALVADOR", "NITEROI"):
                    continue
                v = preco(prod, uf, c, k)
                n = random.randint(6, 30)
                un = "R$/13kg" if prod == "GLP" else ("R$/m³" if prod == "GNV" else "R$/l")
                ws.append([ini, fim, uf, c, prod, n, un, v, 0.08, round(v * 0.96, 2), round(v * 1.05, 2), 0.013])
                estados.setdefault((uf, prod), []).append(v)
                brasil.setdefault(prod, []).append(v)
    ws = wb.create_sheet("ESTADOS")
    cabecalho(ws, "SÍNTESE SEMANAL DOS PREÇOS PRATICADOS - ESTADOS")
    ws.append(["DATA INICIAL", "DATA FINAL", "REGIÃO", "ESTADO"] + COLS[4:])
    for (uf, prod), vs in estados.items():
        m = round(sum(vs) / len(vs), 2)
        ws.append([ini, fim, "X", uf, prod, len(vs) * 12, "R$/l", m, 0.1, min(vs), max(vs), 0.02])
    ws = wb.create_sheet("BRASIL")
    cabecalho(ws, "SÍNTESE SEMANAL DOS PREÇOS PRATICADOS - BRASIL")
    ws.append(["DATA INICIAL", "DATA FINAL"] + COLS[4:])
    for prod, vs in brasil.items():
        ws.append([ini, fim, prod, len(vs) * 12, "R$/l", round(sum(vs) / len(vs), 2), 0.1, min(vs), max(vs), 0.02])
    caminho = TMP / f"resumo_semanal_lpc_{ini:%Y-%m-%d}_{fim:%Y-%m-%d}.xlsx"
    wb.save(caminho)
    return caminho


def revendas(ini, fim, k):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "POSTOS REVENDEDORES"
    cabecalho(ws, "PREÇOS POR POSTO REVENDEDOR")
    ws.append([])
    ws.append(["CNPJ", "RAZÃO", "FANTASIA", "ENDEREÇO", "NÚMERO", "COMPLEMENTO", "BAIRRO", "CEP", "MUNICÍPIO",
               "ESTADO", "BANDEIRA", "PRODUTO", "UNIDADE DE MEDIDA", "PREÇO DE REVENDA", "DATA DA COLETA"])
    ruas = ["AV BRASIL", "RUA XV DE NOVEMBRO", "AV DAS NACOES", "RUA SETE DE SETEMBRO", "ROD BR 101", "AV CENTRAL"]
    bairros = ["CENTRO", "JARDIM AMERICA", "VILA NOVA", "BOA VISTA", "INDUSTRIAL"]
    bandeiras = ["BRANCA", "IPIRANGA", "VIBRA", "RAIZEN", "ALESAT"]
    for uf, cidades in CIDADES.items():
        for c in cidades:
            for i in range(12):
                for prod in ("GASOLINA COMUM", "ETANOL HIDRATADO", "OLEO DIESEL S10"):
                    v = round(preco(prod, uf, c, k) * random.uniform(0.95, 1.05), 2)
                    ws.append([f"{random.randint(10**12, 10**13)}", f"POSTO EXEMPLO {i+1} LTDA", f"AUTO POSTO EXEMPLO {i+1}",
                               random.choice(ruas), str(random.randint(10, 3000)), "", random.choice(bairros), "00000-000",
                               c, uf, random.choice(bandeiras), prod, "R$ / litro", v, fim - timedelta(days=4)])
    caminho = TMP / f"revendas_lpc_{ini:%Y-%m-%d}_{fim:%Y-%m-%d}.xlsx"
    wb.save(caminho)
    return caminho


def bcb():
    hoje = date(2026, 11, 4)
    dias = [hoje - timedelta(days=i) for i in range(700) if (hoje - timedelta(days=i)).weekday() < 5][::-1]
    def diaria(v0, vol):
        v, out = v0, []
        for d in dias:
            v *= 1 + random.uniform(-vol, vol)
            out.append([d.isoformat(), round(v, 4)])
        return out
    selic = []
    for d in dias:
        meta = 15.0 if d < date(2026, 3, 1) else (14.5 if d < date(2026, 6, 20) else 14.25)
        selic.append([d.isoformat(), meta])
    meses = []
    m = date(1995, 1, 1)
    while m <= date(2026, 9, 1):
        meses.append(m)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    def mensal(media):
        return [[x.isoformat(), round(random.uniform(media - 0.3, media + 0.35), 2)] for x in meses]
    ipca = mensal(0.4)
    ipca12 = []
    for i in range(12, len(ipca)):
        f = 1
        for _, t in ipca[i - 11:i + 1]:
            f *= 1 + t / 100
        ipca12.append([ipca[i][0], round((f - 1) * 100, 2)])
    series = {
        "dolar": diaria(5.40, 0.006), "euro": diaria(6.20, 0.006), "selic": selic,
        "cdi": [[d, round(v - 0.10, 2)] for d, v in selic], "ipca": ipca, "ipca12": ipca12[-120:],
        "igpm": mensal(0.45), "inpc": mensal(0.4),
        "poupanca": [[x.isoformat(), 0.6712] for x in meses[-60:]],
    }
    return {"atualizado": hoje.isoformat(), "series": {k: {"codigo": 0, "descricao": "EXEMPLO", "pontos": v} for k, v in series.items()}}


def aneel():
    meses = ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]
    band = ["Verde", "Verde", "Verde", "Verde", "Verde", "Amarela", "Vermelha Patamar 1", "Vermelha Patamar 2", "Vermelha Patamar 1", "Amarela", "Amarela", "Verde"]
    return {"bandeiras": [{"mes": m, "bandeira": b} for m, b in zip(meses, band)],
            "adicional_100kwh": {"Verde": 0.0, "Amarela": 1.885, "Vermelha Patamar 1": 4.463, "Vermelha Patamar 2": 7.877},
            "adicional_oficial": False,
            "tarifas": [{"distribuidora": d, "vigencia": "2026-04-22", "kwh_sem_impostos": v} for d, v in
                        [("CELESC", 0.71234), ("COPEL", 0.68211), ("CEMIG", 0.79102), ("ENEL SP", 0.73520), ("LIGHT", 0.88310), ("NEOENERGIA COELBA", 0.81005)]]}


def main():
    TMP.mkdir(parents=True, exist_ok=True)
    (DADOS / "anp").mkdir(parents=True, exist_ok=True)
    fim = date(2026, 10, 31)
    semanas = [(fim - timedelta(weeks=k) - timedelta(days=6), fim - timedelta(weeks=k)) for k in range(10)][::-1]
    for k, (ini, f) in enumerate(semanas):
        r = resumo(ini, f, k)
        args = [sys.executable, str(RAIZ / "robo" / "coletar_anp.py"), "--resumo", str(r)]
        if k == len(semanas) - 1:
            args += ["--revendas", str(revendas(ini, f, k))]
        subprocess.run(args, check=True, env=os.environ)
    (DADOS / "bcb.json").write_text(json.dumps(bcb()), encoding="utf-8")
    (DADOS / "aneel.json").write_text(json.dumps(aneel()), encoding="utf-8")
    subprocess.run([sys.executable, str(RAIZ / "robo" / "gerar_site.py")], check=True, env=os.environ)


if __name__ == "__main__":
    main()
