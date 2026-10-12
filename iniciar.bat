@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Curriculo sob medida

rem 1) Python
set PY=
where python >nul 2>nul && set PY=python
if not defined PY ( where py >nul 2>nul && set PY=py -3 )
if not defined PY (
  echo Nao encontrei o Python neste computador.
  echo Instale em https://www.python.org/downloads/ e marque "Add python.exe to PATH" na primeira tela.
  echo Depois de instalar, de dois cliques neste arquivo de novo.
  pause
  exit /b 1
)

rem 2) Ambiente e pacotes (so na primeira vez)
if not exist ".venv\Scripts\python.exe" (
  echo Preparando o aplicativo pela primeira vez. Isso leva alguns minutos e precisa de internet...
  %PY% -m venv .venv || ( echo Nao consegui criar o ambiente. & pause & exit /b 1 )
)
if not exist ".venv\.instalado" (
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || ( echo Falha ao instalar os pacotes. Confira a internet e tente de novo. & pause & exit /b 1 )
  echo ok> ".venv\.instalado"
)

rem 3) Chave de API
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Vai abrir o arquivo .env no Bloco de Notas. Cole a sua chave, salve e feche o Bloco de Notas.
  start /wait notepad ".env"
)

rem 4) Abrir o aplicativo
echo Abrindo o aplicativo no navegador. Para encerrar, feche esta janela.
".venv\Scripts\python.exe" -m streamlit run app.py
pause
