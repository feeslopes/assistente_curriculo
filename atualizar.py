"""Chamado pelo iniciar.bat e pelo iniciar.sh antes de abrir o aplicativo: instala a versão publicada mais nova.

Nunca impede o aplicativo de abrir. Para desligar: CV_NAO_ATUALIZAR=1 no ambiente.
"""
from pathlib import Path

from src.atualizador import verificar_e_atualizar

if __name__ == "__main__":
    verificar_e_atualizar(Path(__file__).resolve().parent)
