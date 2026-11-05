# Bolso Hoje — como colocar o site no ar

O site se atualiza sozinho: duas vezes por dia, um robô no GitHub busca os dados da ANP,
do Banco Central e da ANEEL, gera todas as páginas e publica. Você só faz a configuração
abaixo uma vez. Custo: zero (o domínio próprio, opcional, custa cerca de R$ 40 por ano).

## Parte 1 — Colocar no ar (cerca de 20 minutos)

1. **Crie uma conta gratuita** em https://github.com (se ainda não tiver).
2. **Crie o repositório**: clique em **New repository**.
   - Nome: `SEU-USUARIO.github.io` (troque pelo seu nome de usuário, exatamente assim).
   - Marque **Public**. Clique em **Create repository**.
3. **Envie os arquivos**: na página do repositório, clique em **uploading an existing file**,
   arraste **todo o conteúdo** desta pasta (não a pasta em si) e clique em **Commit changes**.
   - A pasta `.github` costuma ficar oculta no computador. Se ela não subir, crie o arquivo
     pelo site: **Add file → Create new file**, digite o nome
     `.github/workflows/atualizar.yml` e cole o conteúdo do arquivo de mesmo nome.
4. **Ajuste o `config.json`**: abra o arquivo no GitHub, clique no lápis e troque
   `SEU-USUARIO` pelo seu usuário. Salve com **Commit changes**.
5. **Ative a publicação**: **Settings → Pages → Source: GitHub Actions**.
6. **Rode o robô pela primeira vez**: aba **Actions → Atualizar dados e publicar site →
   Run workflow**. Em poucos minutos o site estará em `https://SEU-USUARIO.github.io`.

A primeira execução baixa as últimas 12 semanas da ANP. A partir daí, tudo é automático.

## Parte 2 — Domínio próprio (recomendado antes de pedir o AdSense)

1. Registre o domínio em https://registro.br (exemplo: `bolsohoje.com.br`).
2. No `config.json`, preencha:
   - `"url_base": "https://bolsohoje.com.br"`
   - `"caminho_base": ""` (vazio: com domínio próprio o site fica na raiz)
   - `"dominio_proprio": "bolsohoje.com.br"`
3. No registro.br, em DNS, crie quatro registros **A** apontando para
   `185.199.108.153`, `185.199.109.153`, `185.199.110.153` e `185.199.111.153`,
   e um **CNAME** `www` apontando para `SEU-USUARIO.github.io`.
4. Em **Settings → Pages**, digite o domínio em **Custom domain** e marque **Enforce HTTPS**
   quando a opção liberar (pode levar algumas horas).

## Parte 3 — Começar a ganhar dinheiro

1. **Google Search Console** (https://search.google.com/search-console): adicione o site
   e envie o endereço `https://seudominio/sitemap.xml`. Isso acelera a indexação.
2. **Google AdSense** (https://adsense.google.com): peça a aprovação depois que o site
   estiver no ar há algumas semanas, com domínio próprio. Quando aprovarem, copie o
   código `ca-pub-XXXXXXXXXXXXXXXX` para `"adsense_cliente"` no `config.json`. O site
   passa a exibir anúncios automáticos e gera o arquivo `ads.txt` sozinho.
3. **Google Analytics** (opcional): coloque o código `G-XXXXXXX` em `"google_analytics"`.

## Mudar o nome do site

Troque `"nome_site"` e `"descricao"` no `config.json`. Na próxima execução tudo é refeito.

## Se algo der errado

- Na aba **Actions**, um ícone vermelho mostra a execução que falhou. Abra e veja a mensagem.
- Cada fonte de dados é independente: se a ANEEL sair do ar, o resto continua funcionando
  e a seção de energia simplesmente não aparece até voltar.
- Para testar no computador: `pip install -r requirements.txt`, depois
  `python robo/coletar_anp.py`, `python robo/coletar_bcb.py` e `python robo/gerar_site.py`.
  O site sai na pasta `public/`.

## Estrutura

| Pasta/arquivo | Para que serve |
|---|---|
| `robo/coletar_anp.py` | Baixa a pesquisa semanal de combustíveis da ANP |
| `robo/coletar_bcb.py` | Baixa dólar, euro, Selic, CDI, IPCA, IGP-M, INPC e poupança |
| `robo/coletar_aneel.py` | Baixa bandeira tarifária e tarifas de energia |
| `robo/gerar_site.py` | Monta todas as páginas em `public/` |
| `templates/` | Modelos das páginas |
| `static/` | Visual (CSS) e interações (JS) |
| `dados/` | Dados coletados e histórico (o robô atualiza sozinho) |
| `teste/gerar_exemplo.py` | Gera dados fictícios para testar sem internet |
| `.github/workflows/atualizar.yml` | O agendamento automático |
