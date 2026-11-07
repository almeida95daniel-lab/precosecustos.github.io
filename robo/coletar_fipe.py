"""Robô da Tabela FIPE.

Fonte: dataset público fipex-labs/dataset (licença CC0), que publica todo mês a
Tabela FIPE completa (carros, motos e caminhões) em TSV, em pastas AAAA/MM.
O robô baixa os dois meses mais recentes (o atual e o anterior, para a variação)
e grava um resumo por tipo de veículo em dados/fipe/.

Uso: python robo/coletar_fipe.py            (baixa do GitHub)
     python robo/coletar_fipe.py PASTA       (usa uma cópia local do dataset, para teste)
"""
import csv
import io
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from comum import DADOS, ler_json, salvar_json

REPO = "https://github.com/fipex-labs/dataset"
PASTA = DADOS / "fipe"
ANO_MINIMO = 2000
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]
TIPO = {"1": "carros", "carro": "carros", "carros": "carros", "automovel": "carros", "automóvel": "carros",
        "2": "motos", "moto": "motos", "motos": "motos"}


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def baixar_meses(destino: Path, quantos=2):
    """Clona só a estrutura do dataset e baixa (via LFS) os últimos meses."""
    git("clone", "--depth", "1", "--no-checkout", "--filter=blob:none", REPO, str(destino))
    arvore = git("ls-tree", "-r", "--name-only", "HEAD", cwd=destino).split()
    meses = sorted({m.group(1) for f in arvore if (m := re.match(r"^(\d{4}/\d{2})/fipex-prices\.csv$", f))})
    if not meses:
        raise RuntimeError("nenhum mês encontrado no dataset")
    escolhidos = meses[-quantos:]
    git("sparse-checkout", "set", "--no-cone", *[f"{m}/fipex-prices.csv" for m in escolhidos], cwd=destino)
    git("checkout", cwd=destino)
    try:
        git("lfs", "pull", "--include", ",".join(f"{m}/fipex-prices.csv" for m in escolhidos), cwd=destino)
    except RuntimeError as e:
        print(f"[FIPE] aviso no git lfs: {e}")
    return [(m, destino / m / "fipex-prices.csv") for m in escolhidos]


def ler_mes(caminho: Path):
    """{(tipo, marca, modelo, ano, combustível): (valor, codigo_fipe)} de um mês."""
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    if texto.startswith("version https://git-lfs"):
        raise RuntimeError(f"{caminho} veio como ponteiro LFS (arquivo não baixado)")
    amostra = texto[:2000]
    sep = "\t" if amostra.count("\t") >= amostra.count(";") and amostra.count("\t") >= amostra.count(",") else (";" if amostra.count(";") > amostra.count(",") else ",")
    saida, ref = {}, None
    for r in csv.DictReader(io.StringIO(texto), delimiter=sep):
        tipo = TIPO.get(str(r.get("tipo_veiculo", "")).strip().lower())
        if not tipo:
            continue
        zero = str(r.get("zero_km", "")).strip().lower() in ("true", "1", "t", "sim", "yes")
        try:
            ano = 32000 if zero else int(r["ano_modelo"])
            valor = int(r["valor_centavos"]) / 100
        except (KeyError, ValueError):
            continue
        if ano != 32000 and (ano < ANO_MINIMO or ano > 2100):
            continue
        if ano == 32000 and not zero:
            pass
        chave = (tipo, r["nome_marca"].strip(), r["nome_modelo"].strip(), ano, r.get("nome_combustivel", "").strip())
        saida[chave] = (valor, r.get("codigo_fipe", "").strip())
        if ref is None:
            try:
                ref = (int(r["ano_referencia"]), int(r["mes_referencia"]))
            except (KeyError, ValueError):
                pass
    return saida, ref


def main():
    with tempfile.TemporaryDirectory() as tmp:
        if len(sys.argv) > 1:
            base = Path(sys.argv[1])
            meses = sorted((f"{p.parent.parent.name}/{p.parent.name}", p) for p in base.glob("*/*/fipex-prices.csv"))[-2:]
        else:
            meses = baixar_meses(Path(tmp) / "fipex")
        print(f"[FIPE] meses: {[m for m, _ in meses]}")
        atual, ref = ler_mes(meses[-1][1])
        anterior = ler_mes(meses[-2][1])[0] if len(meses) > 1 else {}
    if not atual:
        raise SystemExit("[FIPE] arquivo do mês sem dados reconhecíveis")
    a, m = ref or tuple(int(x) for x in meses[-1][0].split("/"))
    referencia = {"codigo": f"{a}-{m:02d}", "mes": f"{MESES[m - 1]} de {a}"}
    anteriores = ler_json(PASTA / "estado.json", {}).get("referencia", {})
    por_tipo = {}
    for (tipo, marca, modelo, ano, comb), (valor, cod) in atual.items():
        ant = anterior.get((tipo, marca, modelo, ano, comb))
        por_tipo.setdefault(tipo, []).append([marca, modelo, cod, ano, comb, valor, ant[0] if ant else None])
    for tipo, linhas in por_tipo.items():
        linhas.sort(key=lambda x: (x[0].lower(), x[1].lower(), -x[3]))
        salvar_json(PASTA / f"{tipo}.json", {"referencia": referencia, "fonte": "Tabela FIPE (dataset fipex-labs, CC0)",
                                             "colunas": ["marca", "modelo", "codigo_fipe", "ano", "combustivel", "valor", "anterior"],
                                             "veiculos": linhas})
        print(f"[FIPE] {tipo}: {len(linhas)} preços de {referencia['mes']}")
    salvar_json(PASTA / "estado.json", {"referencia": referencia, "anterior": anteriores, "atualizado": date.today().isoformat()})


if __name__ == "__main__":
    main()
