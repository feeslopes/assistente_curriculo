# Guidelines de escrita do currículo

Este arquivo é lido pela IA a cada geração. Edite as regras abaixo para mudar o jeito
como o currículo é escrito. Limites numéricos e ordem das seções ficam em `config.yaml`.

## Verdade acima de tudo
- Use somente fatos marcados como confirmados na base. Pode reformular, reordenar, juntar
  fatos parecidos e traduzir. Não pode acrescentar nada que a base não diga.
- Nunca invente números, ferramentas, tamanho de equipe, escopo, senioridade, prêmios ou cargos.
- Não promova o cargo. O título abaixo do nome tem que ser um cargo que a pessoa realmente
  teve (ou o título padrão dela).
- Se a vaga pede algo que a base não cobre, deixe de fora. Não "dê um jeito" de encaixar.

## Palavras-chave da vaga
- Quando a base sustenta o fato, use o vocabulário exato da vaga (por exemplo, "roadmap",
  "stakeholders", "SQL", "go-to-market"), em vez de sinônimos.
- Não repita a mesma palavra-chave mais de duas vezes no documento inteiro.
- Não crie listas soltas de palavras-chave. Cada termo precisa aparecer dentro de uma frase
  que descreve algo que a pessoa fez, ou na lista de competências com base nos fatos.

## Voz e tempo verbal
- Sem pronomes ("eu", "I"). Cada bullet começa com um verbo de ação.
- Cargos encerrados em passado. No cargo atual, presente ou passado são aceitos; o que importa é manter o mesmo
  tempo verbal em todos os bullets da mesma experiência.
- Evite adjetivos vazios (dinâmico, proativo, apaixonado, orientado a resultados).
- Não atribua traços de personalidade (organizada, detalhista, comunicativa, "attention to detail") que a base
  não diga com essas palavras. Mostre o que a pessoa fez, não como ela é.
- Não acrescente ao fato uma finalidade, um efeito ou uma tarefa a mais: "cuida da agenda de 6 médicos" não vira
  "gerenciou agendas, garantindo a eficiência dos atendimentos"; "atende na recepção" não vira "recebeu pacientes e
  resolveu dúvidas". Se o fato é curto, o bullet fica curto.
- Evite travessão longo. Use vírgula, ponto ou hífen.

## Estrutura de cada bullet
- Formato: ação + contexto + resultado. Se a base tem número, ele aparece.
- Um bullet, uma ideia. Bullet longo é aceitável quando carrega contexto e resultado que a vaga valoriza, mas
  a maioria dos bullets deve ter até 2 linhas. Em cada experiência, no máximo um ou dois bullets longos.
- Não termine bullets com ponto final se o conjunto inteiro não usar. Seja consistente.
- Prefira os bullets que mais conversam com a vaga e coloque-os primeiro em cada experiência.

## Quanto espaço cada experiência recebe
- O foco do currículo está nas experiências recentes e nas mais relevantes para a vaga. O limite de bullets de cada
  experiência vem do sistema (ver `config.yaml` e o painel de espaço na tela) e deve ser respeitado.
- Experiência com limite baixo (1 ou 2) é um resumo: uma linha densa com a função e o resultado que mais conversa
  com a vaga, sem repetir o que as experiências recentes já dizem. Limite 0: nenhum bullet.

## Resumo
- 3 a 4 linhas. Comece pelo cargo e, só se estiver na base, pelo tempo de experiência.
- Inclua 2 ou 3 diferenciais que aparecem na vaga e que a base comprova.
- Sem objetivo genérico ("busco uma oportunidade de crescer").

## Competências
- Grupos curtos, com nome claro (por exemplo, "Dados e Analytics").
- Dentro do grupo, itens separados por vírgula, do mais para o menos relevante para a vaga.
- Só inclua competência que a base sustenta.

## Idioma
- O texto inteiro sai no idioma escolhido na hora de gerar, inclusive o resumo e o nome dos grupos de
  competências. Os fatos chegam no idioma da base: traduza todos.
- Nomes de empresas e de produtos não se traduzem. Instituições de ensino usam o nome oficial no idioma
  da saída ("Federal University of São Carlos" vira "Universidade Federal de São Carlos" em português, e o
  contrário em inglês). Nomes de certificações e de programas ficam no original. Siglas e termos técnicos
  consagrados (SQL, API, OKR, LGPD) ficam como estão.
- Na tradução, mantenha o significado. Não "melhore" o fato ao traduzir.

## Formato para ATS (controlado pelo código, não precisa pedir)
- Coluna única, fonte padrão, sem tabelas, ícones, imagens ou caixas de texto.
- Títulos de seção convencionais, texto selecionável no PDF.
