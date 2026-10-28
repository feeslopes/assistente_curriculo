"""Evals: rodam o pipeline REAL (análise, geração, conferência) num conjunto fixo de casos e devolvem notas comparáveis.

Servem para decidir com dados antes de trocar modelo, prompt ou política de regeneração:
    python -m evals.rodar --rotulo base                       # roda tudo e grava evals/resultados/base-<data>.json
    python -m evals.rodar --rotulo flash --etapas analisador=deepseek-flash,verificador=deepseek-flash
    python -m evals.comparar evals/resultados/base-*.json evals/resultados/flash-*.json
Cada rodada completa chama a IA de verdade e custa centavos (o relatório mostra o custo). Os testes automáticos não usam isto.
"""
