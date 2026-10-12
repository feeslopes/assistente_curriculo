#!/usr/bin/env bash
# Uso: bash iniciar.sh
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Nao encontrei o python3. Instale com o gerenciador de pacotes da sua distribuicao (por exemplo: sudo apt install python3 python3-venv python3-pip)."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Preparando o aplicativo pela primeira vez. Isso leva alguns minutos e precisa de internet..."
  python3 -m venv .venv || { echo "Nao consegui criar o ambiente. Tente: sudo apt install python3-venv"; exit 1; }
fi
if [ ! -f ".venv/.instalado" ]; then
  .venv/bin/python -m pip install -q -r requirements.txt || { echo "Falha ao instalar os pacotes. Confira a internet."; exit 1; }
  echo ok > .venv/.instalado
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Criei o arquivo .env. Abra-o em um editor de texto, cole a sua chave, salve e rode este script de novo."
  ${EDITOR:-nano} .env 2>/dev/null || true
  exit 0
fi

echo "Abrindo o aplicativo no navegador. Para encerrar, aperte Ctrl+C."
.venv/bin/python -m streamlit run app.py
