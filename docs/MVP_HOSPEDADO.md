# MVP hospedado: como funciona e como colocar no ar

Este documento descreve a versão do Assistente Currículo que roda em um servidor, com acesso por login, e o passo a passo para você (Felipe) subir no VPS. O código está pronto e testado; o que falta é a parte do servidor: VPS, domínio, e-mail, HTTPS e o endurecimento do host.

## Visão geral

```
Navegador ──HTTPS──> Caddy (80/443)
                      ├─ /, /login, /entrar, /termos, /privacidade, /go/*, /static/*  ──> servidor de acesso (127.0.0.1:8081)
                      └─ /app/*  ── forward_auth ──> servidor de acesso confere a sessão
                                      │ sessão válida: devolve a identidade assinada (X-CV-Sessao)
                                      └──> Streamlit (127.0.0.1:8501, baseUrlPath=app)
```

- **Landing** (`site/index.html`): uma página estática. Os botões de contratar vão para `/go/semanal` e `/go/mensal`, que contam o clique (sem cookie) e redirecionam para o WhatsApp com a mensagem do plano.
- **Login** (`/login`): e-mail, link mágico de uso único (15 minutos), sem senha. A resposta é sempre a mesma, tenha o e-mail acesso ou não.
- **Termos** (`/termos`): aceite obrigatório no primeiro acesso e a cada nova versão (`CV_VERSAO_TERMOS`). O aceite grava conta, versão, data e hora e IP.
- **App**: o mesmo Streamlit de antes, em modo hospedado (`CV_MODO=hospedado`). Cada usuário enxerga só a própria pasta, derivada da identidade assinada. Sem identidade válida, nenhuma pasta é aberta.
- **Pagamento**: Pix direto na sua conta, combinado pelo WhatsApp. Você libera o acesso com um comando (abaixo). Não há gateway.

## Como liberar e administrar acessos

No servidor, na pasta do projeto:

```bash
python -m servidor.admin liberar maria@exemplo.com --plano mensal     # 30 dias, teto de 60 gerações
python -m servidor.admin liberar joao@exemplo.com --plano semanal     # 7 dias, teto de 15 gerações
python -m servidor.admin liberar ana@exemplo.com --plano mensal --teto 100   # teto diferente para um cliente
python -m servidor.admin listar
python -m servidor.admin revogar maria@exemplo.com      # derruba as sessões na hora
python -m servidor.admin excluir maria@exemplo.com      # LGPD: apaga conta, sessões, aceite e a pasta de dados
python -m servidor.admin metricas                       # visitas, cliques no WhatsApp, uso agregado e custo de IA
```

Renovar é liberar de novo o mesmo e-mail (a contagem de uso recomeça).

## Planos e limites

Definidos em `config.yaml` (`planos` e `limites_uso`) e lidos pelo app e pela landing, então o número que a landing mostra é o que o app aplica:

| Plano | Preço (landing) | Janela | Gerações na janela |
|---|---|---|---|
| mensal | `PRECO_MENSAL` (R$ 15) | 30 dias | 60 (aviso aos 50) |
| semanal | `PRECO_SEMANAL` (R$ 7) | 7 dias | 15 (aviso aos 12) |

Regerar a mesma vaga conta como geração, até 3 vezes além da primeira. Limite de 10 gerações por hora. Editar o texto à mão não conta. A geração só entra na conta se der certo. O app local não tem teto.

## Passo a passo no VPS (Ubuntu, a parte que fica com você)

Faça nesta ordem. Os arquivos de apoio estão em `deploy/`.

1. **Domínio e DNS.** Aponte `app.seudominio.com.br` para o IP do VPS.
2. **Firewall e acesso.** Só as portas 22 (SSH por chave, senha desligada), 80 e 443 abertas. Instale `fail2ban` e ligue as atualizações automáticas de segurança (`unattended-upgrades`).
3. **Disco criptografado.** Os dados dos usuários ficam em `/var/lib/assistente`. Prefira um volume criptografado (LUKS) para essa pasta. Se o provedor só oferece disco comum, registre isso como risco aceito em `docs/SEGURANCA.md`.
4. **Usuário sem privilégio.** `sudo useradd --system --home /opt/assistente --shell /usr/sbin/nologin assistente` e `sudo install -d -o assistente -g assistente -m 700 /var/lib/assistente`.
5. **Código.** Clone o repositório em `/opt/assistente` e crie o ambiente:
   ```bash
   cd /opt/assistente && python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt -r requirements-hospedado.txt
   ```
   Depois do primeiro deploy, fixe as versões com `.venv/bin/pip freeze > requirements-lock.txt` e instale a partir dele nas atualizações.
6. **Segredos.** Crie `/etc/assistente.env` com permissão 600 (`sudo chmod 600`, dono `root`; o systemd lê antes de baixar privilégios). Use o bloco "Modo hospedado" de `.env.example` e preencha: `CV_DADOS_DIR`, `CV_SEGREDO` (gere um novo), `CV_URL_PUBLICA`, `CV_CONFIAR_PROXY=1`, `WHATSAPP_NUMERO`, `PROVEDOR=deepseek`, `DEEPSEEK_API_KEY`, `MODELO=deepseek-v4-pro`. A chave do DeepSeek existe só aqui. Configure também um teto de gasto na conta do DeepSeek.
7. **E-mail do link de acesso.** Escolha um serviço transacional com SMTP e configure `SMTP_*` e o remetente, com SPF e DKIM no DNS do domínio. Sem isto o link não é enviado. Para testar sem e-mail, rode localmente com `python -m servidor.dev` (o link aparece no log).
8. **Serviços.** Copie `deploy/assistente-gateway.service` e `deploy/assistente-app.service` para `/etc/systemd/system/`, depois `sudo systemctl daemon-reload && sudo systemctl enable --now assistente-gateway assistente-app`. Se algum serviço não subir por causa de `MemoryDenyWriteExecute`, remova essa linha e anote como risco aceito.
9. **Caddy.** Instale o Caddy, copie `deploy/Caddyfile` para `/etc/caddy/Caddyfile` trocando o domínio, e `sudo systemctl reload caddy`. O certificado HTTPS sai sozinho.
10. **Teste de ponta a ponta.** Libere seu próprio e-mail, abra `https://app.seudominio.com.br/`, peça o link, aceite os termos, gere um currículo. Confira também: `https://app.seudominio.com.br/app/` em janela anônima volta para o login; `https://app.seudominio.com.br/auth/verificar` responde 404; a porta 8501 não responde de fora (`curl http://IP:8501` falha).
11. **Backup.** Rotina diária e criptografada de `/var/lib/assistente`, com prazo de retenção definido e expurgo (a exclusão de um usuário precisa valer também para os backups dentro desse prazo).
12. **Retenção.** Os termos dizem 90 dias de inatividade. Falta agendar o expurgo (cron que apaga pastas sem uso há mais de 90 dias); ver pendências.

## Rodar no seu computador, só para ver

```bash
python -m servidor.dev
```

Sobe a landing e o login em `http://localhost:8080` com o acesso de teste `teste@exemplo.com`. O link de acesso aparece no terminal. Para ver o app completo atrás do login é preciso o Caddy; sem ele, o app local de sempre (`iniciar`) continua funcionando como antes.

## O que mudou no código

| Área | Arquivo |
|---|---|
| Custo e tokens por chamada, modelo por etapa, log só de metadados no servidor | `src/custo.py`, `src/llm.py`, `config.yaml` |
| Teto de uso, regerações por vaga, limite por hora | `src/cota.py` |
| Pasta por usuário a partir da identidade assinada (falha fechada) | `src/config.py`, `src/hospedado.py` |
| Login, termos, sessão, cliques, eventos sem PII, exclusão | `servidor/` |
| Landing, login, termos, privacidade | `site/` |
| Itens locais escondidos no servidor (pastas, atualização, exemplo, registro) | `app.py`, `interface/` |
| Upload com limites, slug sem traversal | `src/texto.py`, `src/kb.py` |
| Avaliação de qualidade e custo | `evals/` |

## Pendências conhecidas

- Domínio e serviço de envio de e-mail (código pronto, falta configurar).
- Expurgo automático por inatividade (90 dias): ainda não implementado.
- Texto jurídico: os termos e a política são um rascunho funcional escrito sem revisão de advogado. Revisar antes de abrir ao público.
- Conferência visual do PPTX do canvas: gerado a partir do template, mas não renderizado aqui.
- Passkey: fica para uma versão seguinte (hoje, link mágico).
- Analytics: os eventos já são gravados (`ia_chamada`, `geracao_ok`, `geracao_falha`) e agregados em `metricas`. Também há eventos de funil (`cv_importado`, `entrevista_turno`, `base_atualizada`, `vaga_analisada`). Falta um painel visual; por ora, `python -m servidor.admin metricas`.
