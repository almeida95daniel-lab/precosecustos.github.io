"""Funções compartilhadas pelos coletores e pelo gerador do site."""
import json
import os
import re
import time
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = Path(os.environ.get("BH_DADOS", RAIZ / "dados"))
SAIDA_SITE = Path(os.environ.get("BH_SAIDA", RAIZ / "public"))
CONFIG = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

UFS = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí",
    "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul",
    "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins",
}

# Nomes dos produtos como aparecem no site, na ordem em que são exibidos.
PRODUTOS = {
    "gasolina": {"nome": "Gasolina comum", "unidade": "litro"},
    "gasolina_aditivada": {"nome": "Gasolina aditivada", "unidade": "litro"},
    "etanol": {"nome": "Etanol", "unidade": "litro"},
    "diesel_s10": {"nome": "Diesel S10", "unidade": "litro"},
    "diesel": {"nome": "Diesel S500", "unidade": "litro"},
    "gnv": {"nome": "GNV", "unidade": "m³"},
    "glp": {"nome": "Gás de cozinha (13 kg)", "unidade": "botijão"},
}


def sem_acento(txt) -> str:
    txt = unicodedata.normalize("NFKD", str(txt or ""))
    return "".join(c for c in txt if not unicodedata.combining(c))


def normalizar(txt) -> str:
    """Maiúsculas, sem acento e com espaços simples — para comparar cabeçalhos."""
    return re.sub(r"\s+", " ", sem_acento(txt).upper()).strip()


def slug(txt) -> str:
    txt = sem_acento(txt).lower()
    txt = re.sub(r"[^a-z0-9]+", "-", txt)
    return txt.strip("-")


_MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "d"}


def titulo(txt) -> str:
    """'SAO JOSE DOS CAMPOS' -> 'Sao Jose dos Campos'; preserva acentos existentes."""
    palavras = str(txt or "").strip().lower().split()
    saida = []
    for i, p in enumerate(palavras):
        if i > 0 and p in _MINUSCULAS:
            saida.append(p)
        elif "'" in p:  # d'oeste, d'alho
            a, b = p.split("'", 1)
            saida.append(a + "'" + b.capitalize())
        elif "-" in p:
            saida.append("-".join(x.capitalize() for x in p.split("-")))
        else:
            saida.append(p.capitalize())
    return " ".join(saida)


def uf_de(valor) -> str | None:
    """Aceita sigla ('SC') ou nome ('SANTA CATARINA') e devolve a sigla."""
    v = normalizar(valor)
    if v in UFS:
        return v
    for sigla, nome in UFS.items():
        if normalizar(nome) == v:
            return sigla
    return None


def produto_de(valor) -> str | None:
    v = normalizar(valor)
    if "GASOLINA" in v:
        return "gasolina_aditivada" if "ADITIVADA" in v else "gasolina"
    if "ETANOL" in v:
        return "etanol"
    if "DIESEL" in v:
        return "diesel_s10" if "S10" in v or "S-10" in v else "diesel"
    if "GNV" in v or "GAS NATURAL" in v:
        return "gnv"
    if "GLP" in v or "LIQUEFEITO" in v:
        return "glp"
    return None


def numero(valor) -> float | None:
    if valor is None or valor == "" or valor == "-":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip().replace("R$", "").strip()
    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def baixar(url: str, tentativas: int = 3, timeout: int = 60) -> bytes:
    import requests

    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR"}, timeout=timeout)
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            return r.content
        except FileNotFoundError:
            raise
        except Exception as e:  # rede instável: tenta de novo
            ultimo = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"Falha ao baixar {url}: {ultimo}")


def salvar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def ler_json(caminho: Path, padrao=None):
    if not caminho.exists():
        return padrao
    return json.loads(caminho.read_text(encoding="utf-8"))
