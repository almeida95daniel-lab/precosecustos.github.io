"""Robô da ANEEL: bandeira tarifária do mês e tarifa residencial de cada distribuidora.

Fonte: portal de dados abertos da ANEEL (CKAN) — https://dadosabertos.aneel.gov.br
É um módulo opcional: se falhar, o site é gerado sem a seção de energia.
"""
import json
import sys
from urllib.parse import quote

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from comum import DADOS, baixar, ler_json, normalizar, numero, salvar_json

API = "https://dadosabertos.aneel.gov.br/api/3/action"

# Usado só se o recurso com os valores das bandeiras não for encontrado (R$ por 100 kWh).
ADICIONAL_RESERVA = {"Verde": 0.0, "Amarela": 1.885, "Vermelha Patamar 1": 4.463, "Vermelha Patamar 2": 7.877}


def api(acao, **params):
    qs = "&".join(f"{k}={quote(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))}" for k, v in params.items())
    dados = json.loads(baixar(f"{API}/{acao}?{qs}", timeout=120))
    if not dados.get("success"):
        raise RuntimeError(dados.get("error"))
    return dados["result"]


def recursos(busca):
    res = []
    for pacote in api("package_search", q=busca, rows="10")["results"]:
        for r in pacote.get("resources", []):
            if r.get("datastore_active"):
                res.append((pacote["name"], r["name"], r["id"]))
    return res


def data_iso(valor) -> str:
    """Aceita '2025-07-01T00:00:00' ou '01/07/2025' e devolve '2025-07-01'."""
    s = str(valor or "").strip()
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        return f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
    return s[:10]


def bandeira_canonica(nome) -> str | None:
    n = normalizar(nome)
    if "ESCASSEZ" in n:
        return "Escassez Hídrica"
    if "VERMELHA" in n:
        return "Vermelha Patamar 2" if "2" in n else "Vermelha Patamar 1"
    if "AMARELA" in n:
        return "Amarela"
    if "VERDE" in n:
        return "Verde"
    return None


def chave(reg, *termos):
    for k in reg:
        if all(t in normalizar(k) for t in termos):
            return k
    return None


def coletar_tarifas():
    alvo = [r for r in recursos("tarifas distribuidoras energia") if "tarifa" in normalizar(r[1]).lower() or "TARIFA" in normalizar(r[1])]
    if not alvo:
        raise RuntimeError("recurso de tarifas não encontrado")
    rid = alvo[0][2]
    filtros = {"DscSubGrupo": "B1", "DscClasse": "Residencial", "DscModalidadeTarifaria": "Convencional",
               "DscBaseTarifaria": "Tarifa de Aplicação"}
    linhas = api("datastore_search", resource_id=rid, filters=filtros, limit="32000",
                 sort="DatInicioVigencia desc")["records"]
    por_dist = {}
    for r in linhas:
        if normalizar(r.get("DscSubClasse", "Residencial")) not in ("RESIDENCIAL", ""):
            continue
        sig = r.get("SigAgente")
        tusd, te = numero(r.get("VlrTUSD")), numero(r.get("VlrTE"))
        if not sig or tusd is None or te is None:
            continue
        ini = data_iso(r.get("DatInicioVigencia"))
        if sig not in por_dist or ini > por_dist[sig]["vigencia"]:
            fator = 1000 if normalizar(r.get("DscUnidadeTerciaria", "MWh")) == "MWH" else 1
            por_dist[sig] = {"distribuidora": sig, "vigencia": ini,
                             "kwh_sem_impostos": round((tusd + te) / fator, 5)}
    return sorted(por_dist.values(), key=lambda d: d["distribuidora"])


def coletar_bandeiras():
    todos = recursos("bandeira tarifaria")
    acion = [r for r in todos if "ACIONAMENTO" in normalizar(r[1])]
    adic = [r for r in todos if "ADICIONAL" in normalizar(r[1])]
    meses = []
    if acion:
        regs = api("datastore_search", resource_id=acion[0][2], limit="32000")["records"]
        if regs:
            kc, kb = chave(regs[0], "COMPETENCIA"), chave(regs[0], "BANDEIRA")
            for r in regs:
                b = bandeira_canonica(r.get(kb)) if kb else None
                if kc and b:
                    meses.append({"mes": data_iso(r[kc])[:7], "bandeira": b})
    meses = sorted({m["mes"]: m for m in meses}.values(), key=lambda m: m["mes"])
    valores = {}
    if adic:
        regs = api("datastore_search", resource_id=adic[0][2], limit="32000")["records"]
        if regs:
            kb, kv, ki = chave(regs[0], "BANDEIRA"), chave(regs[0], "VLR"), chave(regs[0], "INICIO")
            ult = {}
            for r in regs:
                nome, v, ini = bandeira_canonica(r.get(kb)), numero(r.get(kv)), data_iso(r.get(ki))
                if nome and v is not None and (nome not in ult or ini > ult[nome][0]):
                    ult[nome] = (ini, v)
            # valores vêm em R$/MWh -> R$ por 100 kWh
            valores = {k: round(v / 10, 3) for k, (_, v) in ult.items()}
            valores.setdefault("Verde", 0.0)
            # conferência de sanidade: amarela < vermelha 1 < vermelha 2
            ok = valores.get("Amarela", 0) < valores.get("Vermelha Patamar 1", 0) < valores.get("Vermelha Patamar 2", 0)
            if not ok:
                print(f"[ANEEL] valores de bandeira inconsistentes {valores}; usando a tabela de referência")
                valores = {}
    return meses[-24:], (valores or ADICIONAL_RESERVA), bool(valores)


def main():
    destino = DADOS / "aneel.json"
    anterior = ler_json(destino, {})
    saida = dict(anterior)
    try:
        meses, valores, oficial = coletar_bandeiras()
        if meses:
            saida.update({"bandeiras": meses, "adicional_100kwh": valores, "adicional_oficial": oficial})
            print(f"[ANEEL] bandeira {meses[-1]}")
    except Exception as e:
        print(f"[ANEEL] bandeiras indisponíveis: {e}")
    try:
        tarifas = coletar_tarifas()
        if tarifas:
            saida["tarifas"] = tarifas
            print(f"[ANEEL] tarifas de {len(tarifas)} distribuidoras")
    except Exception as e:
        print(f"[ANEEL] tarifas indisponíveis: {e}")
    if saida:
        salvar_json(destino, saida)


if __name__ == "__main__":
    main()
