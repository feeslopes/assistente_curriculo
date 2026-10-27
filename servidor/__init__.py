"""Camada de acesso do modo hospedado: login por link mágico, lista de acesso, termos, cliques e eventos.

Roda separada do Streamlit (um proxy reverso pergunta a ela, a cada requisição, se a sessão é válida) e só fala com o app
por uma identidade assinada. O app local não usa nada deste pacote.
"""
