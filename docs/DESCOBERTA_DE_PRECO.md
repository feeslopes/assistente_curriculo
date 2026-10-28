# Roteiro de descoberta de preço

Objetivo: achar a faixa de preço que os interessados aceitam e se preferem o plano semanal ou o mensal. Sem piloto de pré-venda: o MVP é o teste. Os números de custo vêm de `docs/economics_assistente_curriculo.xlsx` (aba Executiva).

## 1. Antes de falar com as pessoas

- Rode `python -m evals.rodar --rotulo base` uma vez, com o `.env` do DeepSeek, e leia o custo por caso no relatório. Troque as premissas de tokens da planilha pelos valores medidos. O piso de preço é o custo por geração vezes o teto de uso, mais o custo fixo por assinante.
- Defina dois pontos de preço por plano e dois grupos de interessados (A e B). Sugestão inicial:

| Grupo | Semanal | Mensal |
|---|---|---|
| A | R$ 7 | R$ 15 |
| B | R$ 9 | R$ 19 |

Em cada grupo, mostre os dois planos lado a lado. A pergunta que o teste responde: o público prefere pagar pouco e curto ou compromisso mensal, e como isso muda a vida média do assinante.

## 2. Mensagem curta para os interessados (Van Westendorp)

> Oi, [nome]! Estou fechando a primeira versão do Assistente Currículo: ele monta um currículo por vaga usando só fatos que você confirmou, e mostra o que a vaga pede e você não tem. Antes de definir o preço, quatro perguntas rápidas, respondendo com um valor por mês:
> 1. A partir de quanto você acharia caro demais para contratar?
> 2. A partir de quanto você acharia caro, mas ainda pensaria?
> 3. Até quanto você acharia barato, uma boa compra?
> 4. Abaixo de quanto você desconfiaria da qualidade?

Registre as respostas em uma planilha simples (nome, grupo, quatro valores, observação). Com 10 a 15 respostas já dá para ver a faixa: o intervalo entre "barato demais" e "caro demais" e o ponto em que "caro" e "barato" se cruzam.

## 3. Oferta real

Depois das perguntas, ofereça o acesso ao mesmo grupo, com o preço do grupo (A ou B), pelo WhatsApp, e combine o Pix. Registre por pessoa: se pagou, quando, qual formato escolheu (semanal ou mensal) e o uso na primeira semana. O uso sai de `python -m servidor.admin metricas` (gerações, entrevista concluída, vaga analisada). Anote também quem recusou e por quê, em uma frase.

## 4. Como ler o resultado

| Sinal | Leitura |
|---|---|
| Maioria escolhe o semanal | A busca é curta e intensa: reforçar o semanal e testar um passe de 15 dias |
| Maioria escolhe o mensal | Buscas mais longas: manter o mensal como principal e ajustar o teto |
| Quem paga usa perto do teto na primeira semana | Há demanda de volume: reavaliar teto e preço (a aba Teto mensal mostra o efeito na margem) |
| Quem paga usa pouco e some | Valor percebido baixo: olhar o funil (entrevista concluída, primeira geração) antes de mexer em preço |
| Recusa concentrada num preço | Testar o outro ponto de preço no próximo grupo |

## 5. Decisão

Com o mínimo de 10 pessoas por grupo, escolha o preço de cada plano e atualize três lugares: `PRECO_SEMANAL` e `PRECO_MENSAL` no `/etc/assistente.env`, `planos` no `config.yaml` (se o teto mudar) e as premissas da planilha. A landing passa a mostrar o novo preço sem mexer em código.

CAC fica fora desta rodada. Registre apenas por qual canal cada pessoa chegou (indicação, LinkedIn, comunidade) para quando for olhar aquisição.
