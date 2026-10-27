# Segurança do modo hospedado

Hospedar muda o risco: o servidor passa a guardar currículo, histórico profissional, telefone, e-mail e vagas de terceiros. Um vazamento é incidente de LGPD com obrigação de comunicar. Este documento registra o que foi feito no código, o que foi verificado, o que depende de você no servidor e os riscos aceitos.

**Regra de ouro (gate):** nenhum dado de usuário real entra no servidor antes de os itens da seção "Antes de abrir" estarem marcados.

## Modelo de ameaças resumido

| Ameaça | Como se materializaria | Defesa |
|---|---|---|
| Um usuário lê dados de outro | Estado global compartilhado entre sessões do Streamlit, pasta errada, id forjado | Pasta do usuário só vem de identidade assinada (HMAC) por requisição; sem identidade, o app para; sem pasta padrão |
| Forjar a identidade | Mandar um cabeçalho `X-CV-Sessao` ou `X-CV-User` próprio | Assinatura HMAC com segredo só do servidor, validade de 2 minutos, uid conferido por regex; o Caddy descarta o cabeçalho do cliente |
| Entrar sem pagar | Adivinhar link ou sessão | Tokens de 256 bits, guardados só como hash, link de uso único com 15 minutos, sessão de 7 dias; acesso conferido a cada requisição na lista de acesso |
| Descobrir quem é cliente | Pedir link para vários e-mails | Resposta idêntica, envio em segundo plano, limite por e-mail e por IP |
| Path traversal | Slug vindo da saída da IA ou do cliente | `kb._caminho` só aceita `[a-z0-9-]`; a IA só pode escolher destinos existentes; testes cobrem |
| Upload hostil | PDF ou DOCX malformado, zip bomb, arquivo enorme | Limites de tamanho, de páginas e de tamanho descomprimido; erro simples sem traceback |
| Prompt injection | Texto de vaga ou de CV tentando mandar no modelo | Todo item do currículo precisa de fonte em fato confirmado; números, siglas e títulos conferidos por código; saída tratada como dado |
| Vazar conteúdo por log | Log guardando prompt e resposta | No servidor, o log guarda só metadados (etapa, modelo, tokens, custo, tamanho); teste garante que o texto não aparece |
| Vazar dado por métrica | Evento com nome, e-mail ou texto de vaga | `registrar_evento` só aceita números e rótulos curtos em minúsculas; texto livre é recusado; id da métrica é derivado e não liga à pasta |
| Abuso de custo | Automação ou compartilhamento de conta | Teto por plano, regerações por vaga, 10 gerações por hora, validade do acesso, teto de gasto no DeepSeek |
| CSRF no login e nos termos | Formulário em outro site | Checagem de Origin, cookie SameSite=Lax, `Referrer-Policy: same-origin` |
| XSS na landing e nas telas de acesso | Entrada refletida na página | Valores escapados, CSP `default-src 'none'` sem script e sem estilo inline |
| Vazamento de caminho do servidor na tela | Mensagens com `/var/lib/...` | Botões de pasta e legendas com caminho escondidos no servidor; `showErrorDetails=none` |

## O que foi verificado

- Testes automáticos novos (verdes): `tests/test_gateway.py` (login, link de uso único, expiração, limites, cookie, termos, revogação, CSP, WhatsApp), `tests/test_hospedado.py` (assinatura, expiração, isolamento, eventos sem PII, exclusão), `tests/test_app_hospedado.py` (app sem identidade não abre e não cria pasta; dois usuários isolados; cota por usuário), `tests/test_cota.py`, `tests/test_custo.py` (log sem conteúdo), `tests/test_seguranca_codigo.py` (uploads e slugs).
- Landing, login e termos verificados no navegador em desktop e em 375 px, com o envio do link em modo dev. Essa verificação achou um defeito que os testes não pegaram: `Referrer-Policy: no-referrer` faz o navegador mandar `Origin: null` e a checagem de origem recusava o próprio site. Corrigido para `same-origin`, com teste.
- Histórico do Git: sem chaves reais (só marcadores como `cole_a_chave_aqui` e valores de teste). Nenhum PDF, DOCX, `.env`, base ou saída rastreado. `dados/`, `dados_dev/`, `*.db` e `evals/resultados/` entraram no `.gitignore`.

## O que não foi verificado

- O Caddy, o systemd e o endurecimento do host não foram exercitados (a parte do servidor é sua). O `Caddyfile` e as units seguem a documentação, mas precisam do teste de ponta a ponta do passo 10 do `MVP_HOSPEDADO.md`.
- Não rodei `pip-audit`, `gitleaks` nem um scanner de baseline (por exemplo OWASP ZAP) porque não estão instalados aqui. A varredura de segredos acima foi uma busca simples por padrões no histórico, não substitui o `gitleaks`.
- Não houve revisão por pessoa de segurança externa.
- O Streamlit não foi exercitado atrás do proxy com WebSocket real; os testes usam um Streamlit falso. Confirme no passo 10.

## Antes de abrir (gate)

- [ ] Caddy no ar com HTTPS; `/auth/verificar` retorna 404 de fora; porta 8501 e 8081 inacessíveis de fora.
- [ ] Teste de isolamento no servidor real: dois e-mails, cada um vê só o seu histórico, inclusive abrindo a mesma janela em abas diferentes.
- [ ] `CV_SEGREDO` novo, gerado no servidor, fora do repositório. Arquivo `/etc/assistente.env` com permissão 600.
- [ ] Teto de gasto configurado na conta do DeepSeek.
- [ ] `pip-audit` e `gitleaks` sem achados altos (rodar no servidor ou na sua máquina).
- [ ] Disco dos dados criptografado, ou risco registrado abaixo.
- [ ] Backup criptografado com prazo e rotina de expurgo.
- [ ] Termos revisados por alguém jurídico.
- [ ] Plano de incidente lido (abaixo).

## Plano de incidente (enxuto)

1. Conter: `sudo systemctl stop assistente-app assistente-gateway` e, se houver suspeita sobre a chave, revogar a `DEEPSEEK_API_KEY` no painel do DeepSeek; trocar `CV_SEGREDO` invalida todas as sessões e identidades.
2. Avaliar: quais pastas de `usuarios/` foram expostas, por quanto tempo (logs do Caddy e do systemd).
3. Comunicar: titulares afetados e a ANPD, quando houver risco relevante, em prazo razoável conforme a LGPD.
4. Corrigir, registrar a causa e o que mudou, e só então reabrir.

## Riscos aceitos (registrar aqui o que você decidir aceitar)

| Risco | Decisão | Data |
|---|---|---|
| Texto das gerações vai ao DeepSeek (servidores na China) | Aceito e informado nos termos | |
| Disco sem criptografia no nível do provedor | (preencher) | |
| `MemoryDenyWriteExecute` desligado, se necessário | (preencher) | |
| Aceite de termos sem revisão jurídica | (preencher) | |

## Itens futuros

- Expurgo automático por inatividade (90 dias), hoje manual (`python -m servidor.admin excluir`).
- Criptografia no nível do app para `contato.yaml` e a base, com chave fora do disco de dados.
- Passkey como conveniência de login (não substitui limites de abuso).
- Mascarar também nomes de pessoas no texto enviado à IA, quando não forem necessários.
