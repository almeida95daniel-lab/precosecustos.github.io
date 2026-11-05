"""Robô da ANP: baixa o Levantamento de Preços de Combustíveis semanal.

Fluxo:
1. Lê a página "últimas semanas pesquisadas" e acha os links das planilhas
   resumo_semanal_lpc_AAAA-MM-DD_AAAA-MM-DD.xlsx e revendas_lpc_....xlsx.
   Se a página falhar, tenta adivinhar o endereço das últimas semanas.
2. Processa cada semana ainda não vista e acrescenta ao histórico.
3. Da semana mais recente, guarda também os postos mais baratos de cada cidade.

Uso:
  python robo/coletar_anp.py                       # coleta normal
  python robo/coletar_anp.py --resumo a.xlsx --revendas b.xlsx   # arquivos locais (teste)
"""
import argparse
import csv
import io
import re
import sys
from datetime import date, timedelta

import openpyxl

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from comum import (CONFIG, DADOS, baixar, ler_json, normalizar, numero, produto_de,
                   salvar_json, titulo, uf_de)

PAGINA = ("https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/"
          "levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas")
BASE = "https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/arquivos-lpc"
PASTA = DADOS / "anp"
RE_SEMANA = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})[_-](\d{4})-(\d{1,2})-(\d{1,2})\.xlsx", re.I)
CAMPOS_HIST = ["semana_fim", "nivel", "uf", "municipio", "produto", "postos", "medio", "minimo", "maximo"]


# ---------------------------------------------------------------- descoberta
def semana_do_nome(url):
    m = RE_SEMANA.search(url)
    if not m:
        return None
    a = date(int(m[1]), int(m[2]), int(m[3]))
    b = date(int(m[4]), int(m[5]), int(m[6]))
    return a, b


def descobrir_semanas():
    """Devolve {(inicio, fim): {"resumo": url, "revendas": url}} das semanas publicadas."""
    semanas = {}
    try:
        html = baixar(PAGINA).decode("utf-8", "ignore")
        for tipo in ("resumo_semanal_lpc", "revendas_lpc"):
            padrao = re.compile(r"""(?:href\s*=\s*["'])?((?:https?:)?//?[^\s"'<>]*%s_[^\s"'<>]+?\.xlsx)""" % tipo, re.I)
            for url in padrao.findall(html):
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = "https://www.gov.br" + url
                s = semana_do_nome(url)
                if s:
                    semanas.setdefault(s, {})["resumo" if tipo.startswith("resumo") else "revendas"] = url
    except Exception as e:
        print(f"[ANP] página de listagem indisponível ({e}); vou tentar adivinhar os endereços.")

    # A semana da ANP vai de domingo a sábado. Além dos links da página (que às vezes
    # demora a ser atualizada), testa o endereço padrão das semanas mais recentes.
    achadas = [s for s, v in semanas.items() if "resumo" in v]
    mais_nova = max((s[1] for s in achadas), default=date(2000, 1, 1))
    hoje = date.today()
    sabado = hoje - timedelta(days=(hoje.weekday() - 5) % 7)
    for k in range(0, 16 if not achadas else 8):
        fim = sabado - timedelta(weeks=k)
        ini = fim - timedelta(days=6)
        if fim <= mais_nova or (ini, fim) in semanas:
            continue
        nome = f"{ini:%Y-%m-%d}_{fim:%Y-%m-%d}.xlsx"
        semanas[(ini, fim)] = {
            "resumo": f"{BASE}/{fim.year}/resumo_semanal_lpc_{nome}",
            "revendas": f"{BASE}/{fim.year}/revendas_lpc_{nome}",
            "adivinhado": True,
        }
    print(f"[ANP] semanas na página: {len(achadas)} (mais recente {mais_nova}); testando também {sum(1 for v in semanas.values() if v.get('adivinhado'))} endereços prováveis")
    return semanas


# ---------------------------------------------------------------- leitura das planilhas
def _linhas_com_cabecalho(ws, obrigatorios):
    """Acha a linha de cabeçalho (que contém todos os termos obrigatórios) e
    devolve dicionários {cabecalho_normalizado: valor} das linhas seguintes."""
    cab = None
    for linha in ws.iter_rows(values_only=True):
        if cab is None:
            norm = [normalizar(c) for c in linha]
            if all(any(t in c for c in norm) for t in obrigatorios):
                cab = norm
            continue
        if not any(v not in (None, "") for v in linha):
            continue
        yield dict(zip(cab, linha))
    if cab is None:
        raise ValueError(f"Cabeçalho não encontrado na aba {ws.title} (procurando {obrigatorios})")


def _col(reg, *termos, evitar=()):
    for chave, valor in reg.items():
        if chave and all(t in chave for t in termos) and not any(e in chave for e in evitar):
            return valor
    return None


def _aba(wb, nome):
    for ws in wb.worksheets:
        if normalizar(ws.title) == nome:
            return ws
    return None


def ler_resumo(conteudo: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    registros = []
    for nivel, aba in (("municipio", "MUNICIPIOS"), ("estado", "ESTADOS"), ("brasil", "BRASIL")):
        ws = _aba(wb, aba)
        if ws is None:
            print(f"[ANP] aviso: aba {aba} não encontrada")
            continue
        for reg in _linhas_com_cabecalho(ws, ["PRODUTO", "PRECO MEDIO"]):
            prod = produto_de(_col(reg, "PRODUTO"))
            medio = numero(_col(reg, "PRECO MEDIO"))
            if not prod or medio is None:
                continue
            uf = municipio = ""
            if nivel in ("municipio", "estado"):
                uf = uf_de(_col(reg, "ESTADO") or _col(reg, "UF")) or ""
                if not uf:
                    continue
            if nivel == "municipio":
                municipio = titulo(_col(reg, "MUNICIPIO"))
                if not municipio:
                    continue
            registros.append({
                "nivel": nivel, "uf": uf, "municipio": municipio, "produto": prod,
                "postos": int(numero(_col(reg, "NUMERO DE POSTOS")) or 0),
                "medio": round(medio, 3),
                "minimo": numero(_col(reg, "PRECO MINIMO")),
                "maximo": numero(_col(reg, "PRECO MAXIMO")),
            })
    wb.close()
    return registros


def ler_revendas(conteudo: bytes, por_cidade=8):
    """Postos mais baratos por (UF, cidade, produto)."""
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    ws = _aba(wb, "POSTOS REVENDEDORES") or wb.worksheets[0]
    grupos = {}
    for reg in _linhas_com_cabecalho(ws, ["CNPJ", "PRODUTO"]):
        prod = produto_de(_col(reg, "PRODUTO"))
        preco = numero(_col(reg, "PRECO DE REVENDA") or _col(reg, "PRECO"))
        uf = uf_de(_col(reg, "ESTADO") or _col(reg, "UF"))
        cidade = titulo(_col(reg, "MUNICIPIO"))
        if not (prod and preco and uf and cidade):
            continue
        nome = str(_col(reg, "FANTASIA") or "").strip() or str(_col(reg, "RAZAO") or "").strip()
        end = " ".join(str(x).strip() for x in (_col(reg, "ENDERECO"), _col(reg, "NUMERO", evitar=("POSTOS",))) if x not in (None, ""))
        coleta = _col(reg, "DATA DA COLETA")
        grupos.setdefault((uf, cidade, prod), []).append({
            "nome": titulo(nome) or "Posto sem nome fantasia",
            "bandeira": titulo(_col(reg, "BANDEIRA") or ""),
            "endereco": titulo(end),
            "bairro": titulo(_col(reg, "BAIRRO") or ""),
            "preco": round(preco, 3),
            "coleta": coleta.strftime("%d/%m") if hasattr(coleta, "strftime") else str(coleta or "")[:10],
        })
    wb.close()
    saida = {}
    for (uf, cidade, prod), lista in grupos.items():
        lista.sort(key=lambda p: p["preco"])
        saida.setdefault(f"{uf}|{cidade}", {})[prod] = {"total": len(lista), "postos": lista[:por_cidade]}
    return saida


# ---------------------------------------------------------------- histórico
def carregar_historico():
    caminho = PASTA / "historico.csv"
    if not caminho.exists():
        return []
    with caminho.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def gravar_historico(linhas):
    PASTA.mkdir(parents=True, exist_ok=True)
    linhas.sort(key=lambda r: (r["semana_fim"], r["nivel"], r["uf"], r["municipio"], r["produto"]))
    with (PASTA / "historico.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_HIST)
        w.writeheader()
        w.writerows(linhas)


def registrar_semana(historico, fim: date, registros):
    chave = fim.isoformat()
    historico[:] = [h for h in historico if h["semana_fim"] != chave]
    for r in registros:
        historico.append({"semana_fim": chave, **{k: ("" if r[k] is None else r[k]) for k in CAMPOS_HIST[1:]}})


# ---------------------------------------------------------------- nomes oficiais (IBGE)
def garantir_nomes_ibge():
    """A ANP publica nomes sem acento; o IBGE tem a grafia oficial."""
    destino = DADOS / "ibge_municipios.json"
    if destino.exists():
        return
    try:
        import json
        lista = json.loads(baixar("https://servicodados.ibge.gov.br/api/v1/localidades/municipios", tentativas=1, timeout=20))
        nomes = {}
        for m in lista:
            uf = None
            try:
                uf = m["microrregiao"]["mesorregiao"]["UF"]["sigla"]
            except (TypeError, KeyError):
                try:
                    uf = m["regiao-imediata"]["regiao-intermediaria"]["UF"]["sigla"]
                except (TypeError, KeyError):
                    pass
            if uf:
                nomes[f"{uf}|{normalizar(m['nome']).replace('-', ' ')}"] = m["nome"]
        salvar_json(destino, nomes)
        print(f"[IBGE] {len(nomes)} nomes de municípios salvos")
    except Exception as e:
        print(f"[IBGE] API do IBGE indisponível ({e}); tentando base aberta no GitHub")
        try:
            import csv as _csv
            ufs = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
                   "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
                   "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
                   "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}
            texto = baixar("https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv").decode("utf-8")
            nomes = {}
            for m in _csv.DictReader(io.StringIO(texto)):
                uf = ufs.get(str(m.get("codigo_uf", "")).strip())
                if uf and m.get("nome"):
                    nomes[f"{uf}|{normalizar(m['nome']).replace('-', ' ')}"] = m["nome"]
            if nomes:
                salvar_json(destino, nomes)
                print(f"[IBGE] {len(nomes)} nomes de municípios salvos (base aberta)")
        except Exception as e2:
            print(f"[IBGE] nomes indisponíveis ({e2}); as cidades aparecerão como a ANP escreve")


# ---------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resumo", help="planilha resumo_semanal local (teste)")
    ap.add_argument("--revendas", help="planilha revendas local (teste)")
    args = ap.parse_args()
    garantir_nomes_ibge()

    estado = ler_json(PASTA / "estado.json", {"semanas": []})
    historico = carregar_historico()
    vistas = set(estado["semanas"])

    if args.resumo:
        ini, fim = semana_do_nome(args.resumo)
        fila = [((ini, fim), {"resumo": args.resumo, "revendas": args.revendas, "local": True})]
    else:
        semanas = descobrir_semanas()
        ordem = sorted(semanas.items(), key=lambda kv: kv[0][1], reverse=True)
        limite = CONFIG.get("semanas_iniciais_anp", 12) if not vistas else 4
        adivinhadas = [kv for kv in ordem if kv[1].get("adivinhado")]
        reais = [kv for kv in ordem if not kv[1].get("adivinhado")]
        fila = [kv for kv in adivinhadas + reais[:limite] if kv[0][1].isoformat() not in vistas]
        fila.sort(key=lambda kv: kv[0][1], reverse=True)
        fila.reverse()  # mais antiga primeiro

    nova_ultima = None
    for (ini, fim), urls in fila:
        try:
            conteudo = open(urls["resumo"], "rb").read() if urls.get("local") else baixar(urls["resumo"])
        except FileNotFoundError:
            continue  # semana adivinhada que não existe
        except Exception as e:
            if not urls.get("adivinhado"):
                print(f"[ANP] erro na semana {fim}: {e}")
            continue
        if not conteudo.startswith(b"PK"):
            if not urls.get("adivinhado"):
                print(f"[ANP] semana {fim}: o endereço não devolveu uma planilha")
            continue
        registros = ler_resumo(conteudo)
        if not registros:
            print(f"[ANP] semana {fim}: planilha sem dados reconhecíveis")
            continue
        registrar_semana(historico, fim, registros)
        vistas.add(fim.isoformat())
        print(f"[ANP] semana {ini} a {fim}: {len(registros)} registros")
        if nova_ultima is None or fim > nova_ultima[1]:
            nova_ultima = (ini, fim, urls)

    if nova_ultima:
        ini, fim, urls = nova_ultima
        atual = ler_json(PASTA / "ultima.json", {})
        if not atual or atual.get("semana_fim", "") <= fim.isoformat():
            salvar_json(PASTA / "ultima.json", {"semana_inicio": ini.isoformat(), "semana_fim": fim.isoformat()})
            if urls.get("revendas"):
                try:
                    bruto = open(urls["revendas"], "rb").read() if urls.get("local") else baixar(urls["revendas"], timeout=180)
                    postos = ler_revendas(bruto)
                    salvar_json(PASTA / "postos.json", {"semana_fim": fim.isoformat(), "cidades": postos})
                    print(f"[ANP] postos: {len(postos)} cidades")
                except Exception as e:
                    print(f"[ANP] planilha de postos indisponível ({e}); páginas sairão sem a lista de postos.")

    gravar_historico(historico)
    estado["semanas"] = sorted(vistas)
    salvar_json(PASTA / "estado.json", estado)
    print("[ANP] nada novo." if not fila else "[ANP] concluído.")


if __name__ == "__main__":
    main()
