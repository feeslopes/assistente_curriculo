# Currículo sob medida: briefing do projeto

Este arquivo é o briefing completo. Leia inteiro antes de escrever código. Ele foi montado a partir
de uma conversa longa com o responsável pelo projeto, então as decisões da seção 2 já foram tomadas e os fatos da
seção 3 já foram verificados em 12/10/2026 (confira de novo o que está marcado como "verificar").

## 1. Objetivo

O responsável pelo projeto está ajudando uma pessoa próxima a conseguir emprego. Precisamos de um app
que rode **local, na máquina dela**, em duas fases:

1. **Entrevista.** Um chat que conversa com ela, descobre com precisão o que ela fez na vida
   profissional e guarda isso numa base de conhecimento pessoal em Markdown.
2. **Currículo por vaga.** Ela cola ou sobe uma job description. O app cruza a vaga com a base,
   mostra o que está coberto e o que é lacuna, pergunta o que falta, e gera um currículo
   personalizado em Markdown, no idioma que ela escolher (PT ou EN), totalmente amigável a ATS,
   exportado em PDF e DOCX.

Quem vai usar: uma pessoa que provavelmente **não usa terminal**. A área profissional dela
não foi informada, então o app tem que ser agnóstico de área. Os currículos do responsável pelo
projeto servem só como referência de formato.

O repositório pode ir para o GitHub com README. **Nunca versionar dado pessoal** (base, saídas, .env).

## 2. Decisões já tomadas (não reabrir sem motivo forte)

- Só ela usa. Sem login, sem banco de dados, sem servidor. Tudo em arquivos locais.
- Interface web local com **Streamlit**. Entrega com README passo a passo e script de duplo clique
  (`iniciar.bat` no Windows, `iniciar.command` no Mac, `iniciar.sh` genérico).
- Modelos via API compatível com OpenAI, escolhidos no `.env`: **Gemini** (plano gratuito),
  **DeepSeek** (pago, muito barato) e **OpenRouter** (modelos `:free`). Um único cliente HTTP.
- Duas fases separadas: primeiro a entrevista que cria a base, depois a geração por vaga.
- Idiomas: PT-BR e EN. O app **recomenda** o idioma (detectado pela vaga) mas ela **escolhe antes de gerar**.
- ATS friendly de ponta a ponta (seção 8).
- A base é Markdown local. Cada fato carrega a marca `[confirmado]` ou `[sugerido]`.
- A IA pode **sugerir** formulações com base na experiência dela, mas só entra no currículo o que
  ela **confirmar de forma explícita**. Esta é a regra central do produto.
- O currículo atual dela está cru e será melhorado à parte. A ferramenta não depende dele, mas deve
  permitir importá-lo (opcional) para acelerar a entrevista.
- Nome, telefone, e-mail, links e endereço ficam em `base/contato.yaml` e **nunca entram em prompt**.
  O cabeçalho do currículo é montado por código, depois da geração.

## 3. Fatos verificados sobre os provedores (12/10/2026)

Os modelos e preços mudam rápido. O primeiro passo do trabalho (seção 12, M0) é reconfirmar o que
está marcado como "verificar".

**Gemini**
- Endpoint compatível com OpenAI: base `https://generativelanguage.googleapis.com/v1beta/openai/`,
  rota `/chat/completions`, cabeçalho `Authorization: Bearer <chave>`. Chave em https://aistudio.google.com/apikey
- A documentação oficial já usa `gemini-3.8-flash` nos exemplos. Fontes secundárias (checadas em 08/10/2026)
  dizem que o plano gratuito cobre Flash e Flash-Lite (os modelos Pro saíram do gratuito em abril de 2026).
  **Verificar:** não foi confirmado que `gemini-3.8-flash` está no plano gratuito. Até confirmar, usar
  `gemini-2.5-flash` como padrão e listar os modelos que a chave enxerga com `GET /models`.
- Limite gratuito de cerca de 10 requisições por minuto nos Flash (fonte secundária). Por isso, **minimize
  chamadas por currículo** (uma de análise, uma de geração, mais as pontuais) e implemente espera com retry no 429.
- Os modelos de raciocínio gastam tokens de saída pensando. **Não defina `max_tokens` baixo**, ou a resposta
  pode vir vazia.
- **Privacidade (importante para currículo):** no plano gratuito, prompts e respostas podem ser usados pelo
  Google para melhorar produtos fora de UK/CH/EEA. O Brasil está fora. O README deve dizer isso com clareza.

**DeepSeek**
- Base `https://api.deepseek.com` (formato OpenAI). Modelo padrão: `deepseek-flash` (DeepSeek-V4.1-Flash).
  Os nomes antigos `deepseek-v4-flash` ainda são aceitos. **Não usar `deepseek-chat` nem `deepseek-reasoner`**,
  que foram anunciados como descontinuados em 24/07/2026. Existe também `deepseek-v4-pro`.
- Preço por 1M de tokens no Flash: entrada (cache miss) US$ 0,15 fora do pico e US$ 0,30 no pico; saída
  US$ 0,60 e US$ 1,20. Pico: 01h-04h e 06h-10h UTC, de segunda a sexta. Um currículo custa bem menos de 1 centavo.
- Suporta saída JSON. O modo de raciocínio é o padrão e pode deixar a resposta mais lenta.
  **Verificar** na doc ("Thinking Mode") como desligar para as tarefas de formato.
- Os servidores ficam na China. Registrar no README.

**OpenRouter**
- Base `https://openrouter.ai/api/v1`. Modelos gratuitos têm sufixo `:free` e o conjunto muda toda hora.
  Fontes secundárias falam em 20 requisições por minuto e limite diário maior com um crédito mínimo na conta.
  Qualidade irregular, e **modelo mais fraco inventa mais**, que é justamente o risco do projeto.
  Sem modelo padrão: exigir `MODELO` no `.env` e explicar isso na mensagem de erro.
- Alguns modelos rejeitam `response_format`. Faça fallback sem esse parâmetro.

Fontes: https://ai.google.dev/gemini-api/docs/openai , https://api-docs.deepseek.com/quick_start/pricing

## 4. Arquitetura sugerida

Os arquivos marcados com (semente) já existem neste kit. O resto é para você criar.

```
curriculo-ia/
  CLAUDE.md                  este briefing
  README.md                  para quem vai usar, não técnico
  requirements.txt           (semente)
  .env.example  .gitignore   (semente)
  config.yaml                (semente) limites e ordem das seções
  guidelines.md              (semente) regras de escrita lidas pela IA
  app.py                     interface Streamlit, fina: sem lógica de negócio
  verificar.py               diagnóstico para rodar na máquina dela
  iniciar.bat  iniciar.command  iniciar.sh
  prompts/                   entrevistador.md  extrator.md  analisador.md  gerador.md
  src/
    config.py                caminhos, leitura de config.yaml, guidelines e prompts
    llm.py                   cliente único, retry, JSON mode, erros em português
    kb.py                    base de conhecimento em Markdown
    texto.py                 idioma, extração de JSON, leitura de PDF/DOCX, máscara de contato
    interview.py             entrevistador e extração de propostas
    tailor.py                análise da vaga, perguntas de lacuna, geração
    render.py                JSON da geração para Markdown, com validações
    verify.py                checagem de números, cobertura de palavras-chave, alertas
    mdparse.py               parser do subconjunto de Markdown que usamos
    export.py                PDF (reportlab) e DOCX (python-docx)
  base/                      dados dela (gitignored)
  saidas/                    currículos gerados (gitignored)
  exemplo/                   base fictícia + vaga de exemplo, para testar e demonstrar
  tests/                     unittest com LLM falso
  referencia/cv.css          (semente) aparência de um currículo de referência, só como referência visual
```

Stack: Python 3.10+, `streamlit`, `requests` (sem o pacote `openai`: o contrato é simples e fica testável
com sessão falsa), `reportlab`, `python-docx`, `pypdf`, `pyyaml`, `python-dotenv`.

## 5. Regras anti-invenção (o núcleo do produto)

Uma IA que reescreve currículo para bater com palavras-chave tende a exagerar. Em entrevista isso derruba
a candidata. Cada regra abaixo deve ser **imposta por código**, não só pedida no prompt:

1. **IDs de fato.** Cada fato da base tem id `slug#n` (n é a ordem da linha marcada dentro do arquivo).
   O prompt recebe só fatos `[confirmado]`, cada um com seu id.
2. **Geração com fontes.** O gerador devolve JSON em que todo item (resumo, competência, bullet, formação...)
   traz `fontes: [ids]`.
3. **Validação das fontes.** O código confere que os ids existem e são confirmados. Item sem nenhuma fonte
   válida é removido (`bullets_sem_fonte: remover` no `config.yaml`) e aparece na lista de alertas, com o texto,
   para ela poder confirmar o fato que falta.
4. **Cabeçalho de experiência vem do código.** Empresa, cargo, datas e local saem do frontmatter da base,
   formatados por idioma. O modelo só escolhe e reescreve bullets. Ele nunca escreve um cargo ou uma data.
5. **Checagem determinística de números.** Todo número em texto gerado (`85%`, `2.000`, `7`) precisa existir na base
   (normalizar separadores; aceitar número por extenso de 2 a 10, em PT e EN). O que não existir gera aviso.
6. **Título validado.** O título abaixo do nome tem que ser um cargo da base ou o título padrão. Se o modelo
   sugerir outro (por exemplo promover para "Senior"), usar o padrão e avisar. Se ela digitar um título à mão,
   respeitar sem aviso.
7. **Experiências fora.** Se o modelo deixar uma experiência de fora, mostrar aviso (risco de buraco no histórico).
8. **Contato fora do prompt.** Além de manter `contato.yaml` separado, mascarar e-mail, telefone com DDI ou DDD
   entre parênteses, e URLs em qualquer texto enviado ao modelo (currículo importado, mensagens do chat).
   Cuidado para a máscara de telefone não pegar anos ("2016 2021") nem números como "2.000".
9. **Cobertura de palavras-chave.** Depois de gerar, comparar as palavras-chave da vaga com o texto final e mostrar
   quais foram usadas e quais ficaram de fora **por falta de base**. Esse é o retrato honesto para ATS.

## 6. Formato da base (`base/`)

```
base/
  contato.yaml          nome, titulo_padrao, titulo_padrao_en, local, telefone, email, linkedin, site
  perfil.md             objetivo, tipo de vaga que busca, resumo-base
  habilidades.md  formacao.md  certificacoes.md  idiomas.md
  experiencias/
    <empresa>-<cargo>.md
```

Arquivo de experiência (frontmatter YAML + fatos):

```markdown
---
tipo: experiencia
empresa: Empresa Exemplo
cargo: Analista de Marketing
cargo_en: Marketing Analyst        # opcional
inicio: 2022-03                    # AAAA-MM
fim: atual                         # AAAA-MM ou "atual"
local: São Paulo, Brasil
local_en: São Paulo, Brazil        # opcional
ocultar: false                     # opcional: não usar no currículo
---
- [confirmado] Estruturou o funil de aquisição de um produto com 12 mil usuários ativos.
- [sugerido] Reduziu o custo por lead em cerca de 20% (estimativa, confirmar como foi medido).
```

Regras: um fato é uma afirmação verificável e autocontida, sem pronome, no idioma em que a pessoa falou
(o gerador traduz). Linhas sem marca são ignoradas pela IA e o app avisa quantas existem. Operar sempre por
linha para **preservar texto livre** que ela escreva à mão. Deduplicar fatos pelo texto normalizado.
Ids deslocam se um fato for removido: não guardar ids entre sessões.

Formação, idiomas e habilidades seguem o mesmo padrão, por exemplo
`- [confirmado] Universidade X | Bacharelado em Engenharia | 2016 – 2021` e `- [confirmado] Inglês: Fluente`.

## 7. Fluxos

### 7.1 Entrevista

- Chat com `prompts/entrevistador.md`. Uma pergunta por vez, curta. Percorre as experiências da mais
  recente para a mais antiga e cobre: contexto, escopo (equipe, usuários, volume), o que **ela** fez, resultados
  com número, ferramentas, parceiros. Resposta vaga leva a pedido de exemplo e de número. Estimativa é aceita,
  mas fica marcada como estimativa. Quando achar que ela se subestima, propõe a formulação como hipótese e pergunta.
  Nunca escreve currículo, nunca pede contato, nunca elogia por elogiar. Fala português do Brasil, tom direto.
- O contexto do entrevistador inclui um resumo da base atual, para não repetir pergunta.
- **Abertura estática** (sem chamada à API ao carregar a tela), para poupar o limite gratuito.
- Botão "Encerrar rodada e revisar": chama o extrator (`prompts/extrator.md`) e devolve propostas em JSON:

```json
{"propostas": [{
  "destino": "perfil | habilidades | formacao | certificacoes | idiomas | <slug existente> | nova_experiencia",
  "meta": {"empresa": "", "cargo": "", "inicio": "AAAA-MM", "fim": "AAAA-MM ou atual", "local": "", "cargo_en": "", "local_en": ""},
  "fatos": [{"texto": "", "origem": "dito | sugerido"}]
}]}
```

- Tela de revisão em formulário: fatos `dito` vêm marcados, fatos `sugerido` (inferência da IA) vêm **desmarcados**.
  Dois botões: "Salvar marcados como confirmados" e "Salvar marcados e guardar o resto como pendente"
  (os pendentes entram como `[sugerido]` e podem ser confirmados ou removidos na aba Base).
- Importar currículo atual (PDF, DOCX, MD ou TXT): extrai o texto, mascara contato, roda o mesmo extrator.
  Preenche o formulário de contato **localmente** com regex (e-mail, telefone, LinkedIn), sem passar pelo modelo.

### 7.2 Currículo por vaga

1. **Entrada:** colar o texto da vaga ou subir arquivo. Não tentar baixar URL de vaga (sites bloqueiam, e é frágil).
2. **Análise** (1 chamada, JSON): recebe vaga e base confirmada. Devolve:

```json
{"titulo_vaga": "", "empresa": "", "idioma_vaga": "pt | en | es | outro",
 "palavras_chave": ["termos exatos da vaga, por ordem de importância, 10 a 25"],
 "requisitos": [{"requisito": "", "tipo": "obrigatorio | desejavel", "termo_na_vaga": "",
                 "status": "coberto | parcial | lacuna", "evidencias": ["slug#n"], "pergunta": ""}],
 "observacoes": ""}
```

   Pós-validação em código: ids de evidência inexistentes são descartados; `coberto` sem evidência válida cai para `parcial`.
3. **Lacunas:** para cada requisito `lacuna` ou `parcial` com pergunta, campo de resposta e caixa "Não tenho essa experiência".
   As respostas passam pelo extrator (com origem "respostas") e caem na mesma tela de revisão. Depois de salvar,
   oferecer "Reanalisar com a base atualizada".
4. **Idioma:** radio PT/EN. A recomendação vem de uma heurística local de stopwords, com o `idioma_vaga` do modelo
   como desempate. Ela escolhe **antes** de gerar. Campo opcional de título abaixo do nome.
5. **Geração** (1 chamada, JSON). System = `prompts/gerador.md` + `guidelines.md` + limites do `config.yaml`.
   User = vaga + análise + base confirmada com ids. Saída:

```json
{"titulo": "",
 "resumo": {"texto": "", "fontes": []},
 "competencias": [{"grupo": "", "itens": "", "fontes": []}],
 "experiencias": [{"id": "slug", "bullets": [{"texto": "", "fontes": []}]}],
 "formacao": [{"texto": "", "fontes": []}],
 "certificacoes": [{"texto": "", "fontes": []}],
 "idiomas": [{"texto": "", "fontes": []}]}
```

6. **Renderização** (`render.py`): monta o Markdown na ordem de `ordem_secoes`, com títulos por idioma, experiências
   em ordem cronológica reversa (a ordem da base, não a do modelo), mesma empresa agrupada quando há dois cargos
   seguidos, cabeçalho de contato do `contato.yaml`. Honra `bullets_por_experiencia`, `resumo_max_palavras` e
   `max_grupos_competencias` do `config.yaml`: injeta os limites no prompt **e** corta ou avisa em código quando o
   modelo exceder (modelos fracos ignoram limite). Aplica as regras da seção 5 e devolve
   `markdown`, `alertas`, `rastro` (item, fontes válidas e inválidas) e `removidos`. Troca travessão longo por " - ".
7. **Revisão e exportação:** mostrar alertas, cobertura de palavras-chave, o rastro (expansível) e o Markdown em
   área editável. Botão exporta PDF, DOCX e MD **do texto editado**. Salvar em `saidas/<data>-<empresa>-<vaga>/`
   junto com a vaga e a análise. Mostrar número de páginas e avisar se passar de `max_paginas`.

Layout do Markdown gerado (é o mesmo formato dos `.qmd` do responsável pelo projeto):

```markdown
# Nome Sobrenome  
**Título**  
Cidade, País  
+55 11 90000-0000 | email@exemplo.com | linkedin.com/in/usuario

## Resumo

Texto.

## Competências

* **Grupo:** item, item, item

## Experiência Profissional

**Empresa**

_Cargo · Julho 2025 – Presente · São Paulo, Brasil_

* Bullet.

## Formação

* **Instituição** | Curso | 2016 – 2021
```

Detalhe de ATS: escrever o LinkedIn como **texto visível** (`linkedin.com/in/...`), não como `[LinkedIn](url)`.
Muitos parsers de PDF perdem o destino do link e ficam só com a palavra "LinkedIn".

## 8. Exportação ATS

- **PDF com `reportlab`** (Python puro, funciona igual em Windows e Mac, sem dependência de sistema).
  Coluna única, A4, margens de cerca de 14 mm, fonte padrão Helvetica, **texto selecionável**, bullets `•` comuns,
  sem tabela, imagem, ícone ou caixa de texto. A Helvetica padrão usa WinAnsi (cp1252): acentos do português,
  `–` e `·` funcionam, mas é preciso **sanitizar caracteres fora do cp1252** (setas, emojis) antes de desenhar.
  Título de seção com linha fina desenhada (a linha não é texto). Manter empresa e cargo juntos na quebra de página
  (`keepWithNext`). Contar páginas e devolver o número.
- **DOCX com `python-docx`**: coluna única, fonte Arial ou Calibri, estilos nativos `Heading 1`, `Heading 2`
  e `List Bullet` (os parsers de ATS reconhecem). Remover os atributos de tema de fonte dos estilos de título,
  senão a fonte do tema sobrepõe a escolhida. Preto, sem azul padrão dos títulos.
- Ambos saem do **mesmo Markdown**, via `mdparse.py`: `#`, `##`, parágrafos com quebra de linha, listas, `**negrito**`,
  `_itálico_`, links. Link `[texto](url)` vira `texto (url)` no PDF.
- Aparência de referência: `referencia/cv.css` (fonte de 11,2 pt, entrelinha 1,48, margens 14 mm por 12 mm, cargo em
  semibold cinza). Replicar o clima, não o CSS.
- Opcional, depois do MVP: motor alternativo `pandoc` + `wkhtmltopdf` (é o fluxo atual do responsável pelo projeto com Quarto). Não é o
  padrão porque é difícil de instalar para quem não é técnico.
- Teste de ATS no `verificar.py`: gerar o PDF e extrair o texto com `pypdf`. O nome e as seções têm que aparecer.

## 9. Interface (Streamlit)

Três abas e uma barra lateral. A interface é fina: toda a lógica fica em `src/`.

- **Barra lateral:** provedor e modelo em uso, botão "Testar conexão", pasta de saída, e um expander "Testar com
  dados de exemplo" que copia `exemplo/` para `base/` **só se a base estiver vazia**.
- **1. Entrevista:** aviso de privacidade (não digite telefone nem endereço), importar currículo, chat,
  botão "Encerrar rodada e revisar", formulário de revisão.
- **2. Currículo para uma vaga:** os passos da seção 7.2.
- **3. Minha base:** formulário de contato; lista de fatos pendentes com Confirmar e Remover; editor de cada arquivo
  (texto bruto, validando o frontmatter ao salvar); criar nova experiência; contagem de linhas sem marca.
- Se a chave não estiver configurada, mostrar uma tela amigável de configuração e **continuar permitindo a aba Base**.
- Texto da interface em português do Brasil, direto, sem enfeite. Evitar o travessão longo em qualquer texto.

## 10. Testes e critérios de aceite

Use `unittest` (sem dependência extra). O LLM nos testes é falso: uma classe com fila de respostas. A camada
HTTP é testada com sessão falsa (429 com retry, 400 com fallback sem `response_format`, 401, 404, resposta vazia,
timeout). Cobrir no mínimo:

- `kb`: leitura e escrita preservando linhas livres, deduplicação, confirmar e remover, ids, ordenação por data,
  frontmatter inválido, `para_prompt` sem fatos pendentes e sem contato.
- `texto`: detecção de idioma, extração de JSON (com cerca de código e vírgula sobrando), máscara de contato
  (sem estragar "2016 2021" e "2.000"), slugify.
- `render`: item sem fonte é removido e listado; número inventado gera aviso; título promovido cai no padrão;
  experiência omitida gera aviso; limite de bullets por posição; datas em PT e EN; empresa agrupada.
- `export`: PDF gerado, extraído com `pypdf`, contém nome e seções; DOCX relido com `python-docx`;
  caractere fora do cp1252 não derruba nada; contagem de páginas.
- `tailor` ponta a ponta com LLM falso: análise, rebaixamento de `coberto` sem evidência, geração, renderização.
- Teste de fumaça do `app.py` com um módulo `streamlit` falso (stub), só para pegar erro de import, nome e desempacotamento.
  O comportamento real do Streamlit precisa ser conferido **rodando o app**.

Critérios de aceite do MVP (rodar de verdade, com chave real, na máquina do responsável pelo projeto):

1. `python verificar.py` passa do começo ao fim e `--modelos` lista modelos.
2. Importar um currículo de exemplo, rodar uma rodada de entrevista, revisar e salvar: aparecem arquivos em `base/`
   com marcas corretas e **nada** de contato dentro do prompt (confira o que é enviado: logue o payload em modo debug).
3. Colar uma vaga em inglês e outra em português: o idioma recomendado acerta, e ela consegue trocá-lo.
4. O currículo gerado não contém número, cargo, ferramenta ou data que não esteja na base. Provoque o caso
   (vaga que pede algo que a base não tem) e confirme que vira lacuna, não texto.
5. PDF de até `max_paginas`, texto selecionável, seções com nomes convencionais. DOCX abre sem aviso.
6. Um `git status` limpo mostra que `base/`, `saidas/` e `.env` não sobem.
7. Alguém sem terminal consegue seguir o README e abrir o app com duplo clique.

## 11. Armadilhas conhecidas

- **JSON:** pedir `response_format: {"type": "json_object"}`. Se vier 400, repetir sem o parâmetro. Sempre passar a
  resposta por um extrator tolerante (cerca ```json, texto antes e depois, vírgula sobrando). Se ainda falhar,
  **uma** tentativa de reparo e depois erro claro em português sugerindo trocar de modelo.
- **Erros da API em português:** 401/403 (chave inválida ou sem permissão), 404 (modelo não existe: sugerir
  `python verificar.py --modelos`), 429 (esperar `Retry-After` ou recuar com backoff; depois explicar o limite do plano
  gratuito), 5xx e timeout (retry). Nunca mostrar a chave nem o payload na tela.
- **Tags de raciocínio:** remover blocos `<think>...</think>` se aparecerem no conteúdo.
- **Streamlit:** os widgets guardam estado pela `key`. Ao gerar uma nova revisão ou nova análise, **inclua um contador
  na key** (`rev_id`, `analise_id`), senão checkbox e texto antigos reaparecem. Gerar a saída antes de criar o
  `text_area` que a mostra, para poder preencher o `session_state` do widget na mesma execução. Usar `st.form` na revisão.
- **Windows:** abrir e gravar tudo com `encoding="utf-8"`. Caminhos com espaço. `start /wait notepad .env` no `.bat`.
- **Mac:** `.command` baixado de zip pode perder o bit de execução. Documentar `chmod +x iniciar.command` e `bash iniciar.sh`.
- **Python:** instalar Python é o maior obstáculo para quem não é técnico. O README precisa de um passo a passo ilustrado
  em texto (python.org, marcar "Add python.exe to PATH"). Se isso virar problema, considerar empacotar depois.
- **Falso positivo na checagem de números:** a base diz "sete" e o texto diz "7". Por isso o mapa de números por extenso.
  Trate como aviso, nunca como bloqueio.
- **Plano gratuito:** o limite por minuto é baixo. Não faça chamadas ao carregar a tela nem em loop.

## 12. Ordem de trabalho, com pontos de parada

Trabalhe em marcos pequenos. **Pare e mostre ao responsável pelo projeto ao fim de M3 e de M5.**

- **M0. Preparação (30 min).** Instalar dependências em um venv. Rodar uma chamada real em cada provedor em que o responsável tiver
  chave, listar modelos, confirmar o que está marcado como "verificar" na seção 3 e **corrigir os padrões em `llm.py`,
  `.env.example` e README**. Perguntar ao responsável só o que bloquear: ele tem chave de Gemini, de DeepSeek ou das duas?
  Ela usa Windows ou Mac?
- **M1. Núcleo testável.** `config.py`, `texto.py`, `llm.py`, `kb.py`, `verify.py` com testes.
- **M2. Entrevista e importação.** `interview.py`, prompts do entrevistador e do extrator, máscara de contato.
- **M3. Vaga e geração.** `tailor.py`, `render.py`, prompts do analisador e do gerador. Testar com a base de `exemplo/`
  e uma vaga de exemplo, **com chave real**. Mostrar ao responsável o Markdown gerado, os alertas e a cobertura.
- **M4. Exportação.** `mdparse.py`, `export.py`, `verificar.py`, testes de PDF e DOCX.
- **M5. Interface.** `app.py` e o stub de teste. Rodar de verdade e mostrar ao responsável.
- **M6. Entrega.** README para não técnicos, scripts de início, `exemplo/` completo, revisão de privacidade
  (nada pessoal no Git), passada de limpeza.

Os prompts são o ativo mais importante. Escreva-os com cuidado, versionados em `prompts/`, em português do Brasil,
e **teste cada um com modelo real**, porque modelos diferentes se comportam diferente.
Itens que cada prompt precisa cobrir:

- `entrevistador.md`: tudo da seção 7.1. Recebe o resumo da base como contexto.
- `extrator.md`: saída JSON da seção 7.1; fatos atômicos e autocontidos; números exatos preservados e estimativas
  marcadas; `dito` só quando a pessoa afirmou, `sugerido` para inferência (com parcimônia); não duplicar fatos existentes;
  nunca extrair contato; destinos válidos; para `nova_experiencia`, `meta` completo.
- `analisador.md`: schema da seção 7.2; usar só ids fornecidos; `coberto` só com evidência explícita; palavras-chave com o
  vocabulário exato da vaga e sem fluff de soft skill; perguntas específicas, respondíveis em 1 a 3 frases, em português.
- `gerador.md`: schema da seção 7.2; só fatos confirmados; pode reformular, reordenar, juntar e traduzir; **nunca** acrescentar
  número, ferramenta, escopo, senioridade ou cargo; todo item com `fontes`; usar o vocabulário da vaga só onde a base sustenta;
  idioma de saída fixo; devolver só o JSON.

## 13. Convenções

- Texto de interface, README e prompts em português do Brasil. Comentários de código em português.
- Sem o traço longo (travessão) em nenhum texto que o usuário veja. O `–` curto em intervalo de datas é o formato do currículo e pode ficar.
- Tom do README: direto, honesto sobre limites, sem prometer que "vai passar no ATS". O que funciona é usar o
  vocabulário exato da vaga onde for verdade, e um recrutador humano ainda lê o resultado.
- Commits pequenos. Nunca commitar `.env`, `base/`, `saidas/` nem qualquer currículo real.
- Quando uma decisão não estiver neste briefing, escolha o caminho mais simples que preserve a regra central
  (nada entra no currículo sem fato confirmado) e registre a escolha no README.
