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


# O portal da ANEEL às vezes fica fora do ar ou recusa conexões vindas do GitHub. Antes o robô esperava
# 120 s por conexão, 3 vezes, em cada chamada (cerca de 12 minutos por execução). Agora a conexão tem
# 15 s, há só 2 tentativas, e se o portal não responder na primeira chamada as outras nem são tentadas.
FORA_DO_AR = []


def api(acao, **params):
    if FORA_DO_AR:
        raise RuntimeError(f"portal da ANEEL fora do ar nesta execução ({FORA_DO_AR[0]})")
    qs = "&".join(f"{k}={quote(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))}" for k, v in params.items())
    try:
        bruto = baixar(f"{API}/{acao}?{qs}", tentativas=2, timeout=(15, 120))
    except RuntimeError as e:
        if "ConnectTimeout" in str(e) or "ConnectionError" in str(e) or "Max retries" in str(e):
            FORA_DO_AR.append(type(e).__name__)
        raise
    dados = json.loads(bruto)
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
        # só a tarifa comum: sem tarifa social, energia solar (SCEE), postos horários etc.
        if normalizar(r.get("DscDetalhe", "")) not in ("NAO SE APLICA", ""):
            continue
        if normalizar(r.get("NomPostoTarifario", "")) not in ("NAO SE APLICA", ""):
            continue
        sig = r.get("SigAgente")
        tusd, te = numero(r.get("VlrTUSD")), numero(r.get("VlrTE"))
        if not sig or tusd is None or te is None:
            continue
        ini = data_iso(r.get("DatInicioVigencia"))
        fator = 1000 if normalizar(r.get("DscUnidadeTerciaria", "MWh")) == "MWH" else 1
        valor = round((tusd + te) / fator, 5)
        atual = por_dist.get(sig)
        # mais recente vence; no mesmo dia, fica o maior valor (descontos ficam de fora)
        if not atual or ini > atual["vigencia"] or (ini == atual["vigencia"] and valor > atual["kwh_sem_impostos"]):
            por_dist[sig] = {"distribuidora": sig, "vigencia": ini, "kwh_sem_impostos": valor}
    return sorted(por_dist.values(), key=lambda d: d["distribuidora"])


def com_anunciadas(meses):
    """Acrescenta as bandeiras anunciadas (registro manual) que ainda não estão nos dados abertos."""
    oficiais = {m["mes"] for m in meses if not m.get("anunciada")}
    meses = [m for m in meses if not m.get("anunciada")]
    for mes, b in (ler_json(DADOS / "bandeiras_anunciadas.json") or {}).get("meses", {}).items():
        if mes not in oficiais and bandeira_canonica(b):
            meses.append({"mes": mes, "bandeira": bandeira_canonica(b), "anunciada": True})
    return sorted({m["mes"]: m for m in meses}.values(), key=lambda m: m["mes"])


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
    # Os dados abertos da ANEEL às vezes levam semanas para incluir o mês novo. A bandeira é anunciada
    # na última sexta do mês anterior; quando o dado oficial atrasa, vale o registro manual conferido
    # no anúncio da ANEEL (dados/bandeiras_anunciadas.json), até o dado aberto chegar.
    meses = com_anunciadas(meses)
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
        print(f"::warning::[ANEEL] bandeiras indisponíveis: {e}")
        # Mesmo com o portal fora do ar, a bandeira anunciada (registro manual) entra no site.
        if saida.get("bandeiras"):
            meses = com_anunciadas(saida["bandeiras"])[-24:]
            if meses != saida["bandeiras"]:
                saida["bandeiras"] = meses
                print(f"[ANEEL] bandeira pelo anúncio registrado: {meses[-1]}")
    try:
        tarifas = coletar_tarifas()
        if tarifas:
            saida["tarifas"] = tarifas
            print(f"[ANEEL] tarifas de {len(tarifas)} distribuidoras")
    except Exception as e:
        print(f"::warning::[ANEEL] tarifas indisponíveis (mantidas as da última coleta): {e}")
    if saida:
        salvar_json(destino, saida)


if __name__ == "__main__":
    main()
