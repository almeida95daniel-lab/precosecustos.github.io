"""Saúde do robô: confere se cada fonte está tão atual quanto deveria.

Escreve dados/saude.json (lido pelo site) e um resumo no GitHub Actions.
Sai com código 2 quando algo está atrasado, para o workflow abrir um alerta.
"""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from comum import DADOS, ler_json, salvar_json


def ultimo_ponto(serie):
    pts = (serie or {}).get("pontos", []) if isinstance(serie, dict) else (serie or [])
    return pts[-1][0] if pts else None


def dias_desde(iso):
    return (HOJE - date.fromisoformat(iso[:10])).days if iso else 9999


HOJE = date.fromisoformat(os.environ.get("BH_HOJE", date.today().isoformat()))
mes_atual = HOJE.strftime("%Y-%m")
mes_passado = (HOJE.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
itens = []


def item(nome, valor, ok, regra):
    itens.append({"fonte": nome, "ultimo": valor, "ok": bool(ok), "regra": regra})


anp = ler_json(DADOS / "anp" / "ultima.json") or {}
item("ANP: pesquisa semanal de combustíveis", anp.get("semana_fim"), dias_desde(anp.get("semana_fim")) <= 13,
     "semana encerrada há no máximo 13 dias (a ANP publica toda sexta)")
rev = ler_json(DADOS / "anp" / "revendas.json") or {}
item("ANP: preços por posto", rev.get("semana_fim"), rev.get("semana_fim") == anp.get("semana_fim"),
     "mesma semana da pesquisa")

bcb = (ler_json(DADOS / "bcb.json") or {}).get("series", {})
item("Banco Central: dólar PTAX", ultimo_ponto(bcb.get("dolar")), dias_desde(ultimo_ponto(bcb.get("dolar"))) <= 4,
     "último dia útil (até 4 dias corridos, por fins de semana e feriados)")
item("Banco Central: CDI", ultimo_ponto(bcb.get("cdi")), dias_desde(ultimo_ponto(bcb.get("cdi"))) <= 6, "até 6 dias")
item("Banco Central: Selic", ultimo_ponto(bcb.get("selic")), dias_desde(ultimo_ponto(bcb.get("selic"))) <= 6, "até 6 dias")
ipca = ultimo_ponto(bcb.get("ipca"))
dois_meses = (HOJE.replace(day=1) - timedelta(days=32)).strftime("%Y-%m")
item("IBGE/BCB: IPCA", ipca, (ipca or "")[:7] >= (mes_passado if HOJE.day >= 15 else dois_meses),
     "IPCA do mês anterior a partir do dia 15; antes disso, o de dois meses atrás")

moedas = (ler_json(DADOS / "moedas.json") or {}).get("moedas", {})
atrasadas = [c for c, d in moedas.items() if d.get("pontos") and dias_desde(d["pontos"][-1][0]) > 5]
item("Moedas internacionais", f"{len(moedas)} moedas", not atrasadas and len(moedas) >= 7,
     "todas com cotação dos últimos 5 dias" + (f" (atrasadas: {', '.join(atrasadas)})" if atrasadas else ""))

fipe = (ler_json(DADOS / "fipe" / "estado.json") or {}).get("referencia", {})
item("Tabela FIPE", fipe.get("codigo"), fipe.get("codigo", "") >= (mes_atual if HOJE.day >= 12 else mes_passado),
     "tabela do mês a partir do dia 12")

aneel = ler_json(DADOS / "aneel.json") or {}
band = (aneel.get("bandeiras") or [{}])[-1].get("mes")
item("ANEEL: bandeira tarifária", band, (band or "") >= (mes_atual if HOJE.day >= 8 else mes_passado),
     "bandeira do mês a partir do dia 8")
item("ANEEL: tarifas das distribuidoras", f"{len(aneel.get('tarifas', []) or [])} distribuidoras",
     len(aneel.get("tarifas", []) or []) >= 50, "pelo menos 50 distribuidoras")

problemas = [i for i in itens if not i["ok"]]
salvar_json(DADOS / "saude.json", {"verificado": HOJE.isoformat(), "itens": itens})

linhas = ["## Saúde do robô", "", "| Fonte | Último dado | Situação |", "|---|---|---|"]
for i in itens:
    linhas.append(f"| {i['fonte']} | {i['ultimo'] or '—'} | {'✅ em dia' if i['ok'] else '⚠️ atrasado: ' + i['regra']} |")
texto = "\n".join(linhas)
print(texto)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
        f.write(texto + "\n")
if problemas:
    Path("alerta.md").write_text(texto + "\n\nEste alerta fecha sozinho quando os dados voltarem a ficar em dia.\n", encoding="utf-8")
    for i in problemas:
        print(f"::warning::{i['fonte']} atrasado (último: {i['ultimo']})")
    sys.exit(2)
