"""Robô da Tabela FIPE: preço médio de carros e motos.

A tabela completa tem dezenas de milhares de preços, e a FIPE limita o ritmo de
consultas. Por isso o robô trabalha em etapas: cada execução consulta durante
alguns minutos (FIPE_MINUTOS), salva o progresso e continua na próxima.
Quando a FIPE publica o mês novo, ele atualiza os preços e guarda o valor do
mês anterior para mostrar a variação.

Fonte principal: API pública do site oficial (veiculos.fipe.org.br).
Reserva: API gratuita da Parallelum (limite de 500 consultas por dia).

Uso: FIPE_MINUTOS=20 python robo/coletar_fipe.py
"""
import json
import os
import sys
import time
from datetime import date

import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from comum import DADOS, UA, ler_json, numero, salvar_json

PASTA = DADOS / "fipe"
TIPOS = {"carros": (1, "carro"), "motos": (2, "moto")}
ANO_MINIMO = 2000  # anos-modelo mais antigos ficam de fora (pouca procura)
PRIORIDADE = {
    "carros": ["Fiat", "VW - VolksWagen", "GM - Chevrolet", "Toyota", "Hyundai", "Renault", "Honda", "Jeep",
               "Nissan", "Ford", "Peugeot", "Citroën", "Caoa Chery", "BYD", "Mitsubishi", "Kia Motors", "GWM",
               "Volvo", "BMW", "Mercedes-Benz", "Audi", "Land Rover", "Suzuki", "RAM", "Chery"],
    "motos": ["HONDA", "YAMAHA", "SUZUKI", "KAWASAKI", "BMW", "HARLEY-DAVIDSON", "TRIUMPH", "ROYAL ENFIELD",
              "HAOJUE", "SHINERAY", "DAFRA", "KTM", "DUCATI", "BAJAJ"],
}


class Limite(Exception):
    """A fonte pediu para parar (limite de consultas ou bloqueio)."""


# ---------------------------------------------------------------- fontes
class FipeOficial:
    nome = "FIPE (veiculos.fipe.org.br)"
    BASE = "https://veiculos.fipe.org.br/api/veiculos/"

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": "https://veiculos.fipe.org.br/",
                               "Origin": "https://veiculos.fipe.org.br", "Accept": "application/json"})

    def _post(self, metodo, **dados):
        for tentativa in range(4):
            try:
                r = self.s.post(self.BASE + metodo, data=dados, timeout=30)
            except requests.RequestException:
                time.sleep(10 * (tentativa + 1))
                continue
            if r.status_code in (403, 429) or r.status_code >= 500:
                time.sleep(20 * (tentativa + 1))
                continue
            r.raise_for_status()
            j = r.json()
            if isinstance(j, dict) and j.get("erro"):
                if "nada encontrado" in str(j.get("erro")).lower():
                    return None
                raise ValueError(j["erro"])
            return j
        raise Limite(f"{metodo}: muitas falhas seguidas")

    def referencia(self):
        r = self._post("ConsultarTabelaDeReferencia")[0]
        return {"codigo": int(r["Codigo"]), "mes": r["Mes"].strip()}

    def marcas(self, tipo, ref):
        cod, _ = TIPOS[tipo]
        return [(str(m["Value"]), m["Label"].strip()) for m in
                self._post("ConsultarMarcas", codigoTabelaReferencia=ref, codigoTipoVeiculo=cod)]

    def modelos(self, tipo, ref, marca):
        cod, _ = TIPOS[tipo]
        j = self._post("ConsultarModelos", codigoTipoVeiculo=cod, codigoTabelaReferencia=ref, codigoMarca=marca)
        return [(str(m["Value"]), m["Label"].strip()) for m in (j or {}).get("Modelos", [])]

    def anos(self, tipo, ref, marca, modelo):
        cod, _ = TIPOS[tipo]
        j = self._post("ConsultarAnoModelo", codigoTipoVeiculo=cod, codigoTabelaReferencia=ref,
                       codigoMarca=marca, codigoModelo=modelo) or []
        return [(a["Value"], a["Label"].strip()) for a in j]

    def preco(self, tipo, ref, marca, modelo, ano):
        cod, nome_tipo = TIPOS[tipo]
        ano_m, comb = ano.split("-")
        j = self._post("ConsultarValorComTodosParametros", codigoTabelaReferencia=ref, codigoTipoVeiculo=cod,
                       codigoMarca=marca, codigoModelo=modelo, anoModelo=ano_m, codigoTipoCombustivel=comb,
                       tipoVeiculo=nome_tipo, modeloCodigoExterno="", tipoConsulta="tradicional")
        if not j:
            return None
        return {"valor": numero(j.get("Valor")), "codigo_fipe": j.get("CodigoFipe", ""),
                "combustivel": j.get("Combustivel", "")}


class FipeParallelum:
    nome = "Parallelum (API FIPE)"
    BASE = "https://parallelum.com.br/fipe/api/v1/"

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})
        self.mes = None

    def _get(self, caminho):
        for tentativa in range(3):
            try:
                r = self.s.get(self.BASE + caminho, timeout=30)
            except requests.RequestException:
                time.sleep(10)
                continue
            if r.status_code == 429:
                raise Limite("limite diário da Parallelum")
            if r.status_code >= 500:
                time.sleep(15)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        raise Limite(f"{caminho}: muitas falhas")

    def referencia(self):
        # A v1 não informa a tabela; usa o mês de um preço qualquer como referência.
        j = self._get("carros/marcas/21/modelos/4828/anos/2015-1") or {}
        mes = str(j.get("MesReferencia", date.today().strftime("%m/%Y"))).strip()
        return {"codigo": mes, "mes": mes}

    def marcas(self, tipo, ref):
        return [(str(m["codigo"]), m["nome"].strip()) for m in self._get(f"{tipo}/marcas")]

    def modelos(self, tipo, ref, marca):
        j = self._get(f"{tipo}/marcas/{marca}/modelos") or {}
        return [(str(m["codigo"]), m["nome"].strip()) for m in j.get("modelos", [])]

    def anos(self, tipo, ref, marca, modelo):
        return [(a["codigo"], a["nome"].strip()) for a in (self._get(f"{tipo}/marcas/{marca}/modelos/{modelo}/anos") or [])]

    def preco(self, tipo, ref, marca, modelo, ano):
        j = self._get(f"{tipo}/marcas/{marca}/modelos/{modelo}/anos/{ano}")
        if not j:
            return None
        return {"valor": numero(j.get("Valor")), "codigo_fipe": j.get("CodigoFipe", ""),
                "combustivel": j.get("Combustivel", "")}


# ---------------------------------------------------------------- coleta
def escolher_fonte():
    for classe in (FipeOficial, FipeParallelum):
        fonte = classe()
        try:
            ref = fonte.referencia()
            print(f"[FIPE] fonte: {fonte.nome}, tabela de {ref['mes']}")
            return fonte, ref
        except Exception as e:
            print(f"[FIPE] {classe.nome} indisponível: {str(e)[:150]}")
    return None, None


def ano_util(codigo):
    try:
        a = int(codigo.split("-")[0])
    except ValueError:
        return False
    return a == 32000 or a >= ANO_MINIMO  # 32000 = zero km


def ordenar_marcas(tipo, marcas):
    pri = {n.lower(): i for i, n in enumerate(PRIORIDADE[tipo])}
    return sorted(marcas.items(), key=lambda kv: (pri.get(kv[1]["nome"].lower(), 999), kv[1]["nome"]))


def coletar(tipo, fonte, ref, prazo, contador):
    caminho = PASTA / f"{tipo}.json"
    base = ler_json(caminho, {"marcas": {}})
    rc = ref["codigo"]
    base["referencia"] = ref
    base["fonte"] = fonte.nome

    def salvar():
        salvar_json(caminho, base)

    def tempo():
        return time.time() < prazo

    def pausa():
        contador["n"] += 1
        if contador["n"] % 150 == 0:
            salvar()
            print(f"[FIPE] {contador['n']} consultas...")
        time.sleep(0.35)

    if base.get("marcas_ref") != rc:
        for cod, nome in fonte.marcas(tipo, rc):
            base["marcas"].setdefault(cod, {"nome": nome, "modelos": {}})["nome"] = nome
        base["marcas_ref"] = rc
        pausa()

    for mcod, marca in ordenar_marcas(tipo, base["marcas"]):
        if not tempo():
            break
        if marca.get("modelos_ref") != rc:
            for cod, nome in fonte.modelos(tipo, rc, mcod):
                marca["modelos"].setdefault(cod, {"nome": nome, "anos": {}})["nome"] = nome
            marca["modelos_ref"] = rc
            pausa()
        for ocod, modelo in marca["modelos"].items():
            if not tempo():
                break
            if modelo.get("anos_ref") != rc:
                for acod, rotulo in fonte.anos(tipo, rc, mcod, ocod):
                    if ano_util(acod):
                        modelo["anos"].setdefault(acod, {})["rotulo"] = rotulo
                modelo["anos_ref"] = rc
                pausa()
            for acod, ano in modelo["anos"].items():
                if not tempo():
                    break
                if ano.get("ref") == rc:
                    continue
                p = fonte.preco(tipo, rc, mcod, ocod, acod)
                pausa()
                if not p or not p["valor"]:
                    ano["ref"] = rc
                    continue
                if ano.get("valor") and ano.get("ref") not in (None, rc):
                    ano["anterior"] = ano["valor"]
                ano.update(p)
                ano["ref"] = rc
    salvar()
    total = sum(1 for m in base["marcas"].values() for o in m["modelos"].values()
                for a in o["anos"].values() if a.get("ref") == rc and a.get("valor"))
    print(f"[FIPE] {tipo}: {total} preços da tabela de {ref['mes']}")


def main():
    minutos = float(os.environ.get("FIPE_MINUTOS", "20"))
    prazo = time.time() + minutos * 60
    fonte, ref = escolher_fonte()
    if not fonte:
        print("[FIPE] nenhuma fonte disponível agora; tento na próxima execução.")
        return
    contador = {"n": 0}
    for tipo in ("carros", "motos"):
        try:
            coletar(tipo, fonte, ref, prazo, contador)
        except Limite as e:
            print(f"[FIPE] pausa: {e}. O progresso foi salvo.")
            break
        if time.time() >= prazo:
            break
    salvar_json(PASTA / "estado.json", {"referencia": ref, "fonte": fonte.nome, "ultima_execucao": date.today().isoformat(),
                                        "consultas": contador["n"]})
    print(f"[FIPE] fim: {contador['n']} consultas nesta execução.")


if __name__ == "__main__":
    main()
