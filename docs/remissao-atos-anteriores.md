# Plano (FUTURO): despachos com remissão a atos anteriores

> Documento de planejamento. Registra o problema e o desenho de solução para
> implementar **depois**. Nada aqui é urgente — compõe o bucket "decisão"
> (estimativa ~40% manual) do fluxo de automação.

## Contexto / problema

Muitos despachos não trazem instrução completa: fazem **remissão a atos
anteriores** ("conforme assentado à fl. X", "como já decidido", "despacho de
fl. ..., prossiga", "manifeste-se sobre o Evento Y"). O texto da decisão
**atual** sozinho não diz o que fazer — o contexto está num **ato anterior**.

O matcher RAG atual casa apenas o texto do despacho vigente
(`despacho_ato`/`despacho_observacao`) com a movimentação. Ele **não enxerga**
o evento referenciado. Por isso esses casos caem no manual: exige julgar o que
a remissão significa olhando o histórico.

## O modelo JÁ tem o gancho

A tabela `Movement` (processes/models.py) possui:
- `referenced_event` (CharField, rótulo do evento referenciado, ex. "fl. 45/itens")
- `referenced_event_obj` (FK → própria `Movement`, "Movimentação Referenciada")
- `event_number`, `act_description`, `act_normalized`, `document_url` (texto/doc do ato)

Ou seja: dá pra ligar a remissão ao ato concreto e puxar o **texto do ato
referenciado** pro contexto do matching. É o alicerce do plano.

## Objetivo

Fazer o robô, ao encontrar um despacho com remissão, casar um RAG **que
considere o ato referenciado** e propor a execução correta — reduzindo a
dependência manual nesse bucket (parte do ~40% estimado).

## Fases

### Fase 1 — Detecção e registro da remissão (parser)
- Criar/extender parser de movimentação para detectar padrões de remissão no
  texto da decisão:
  - `conforme`, `como já`, `tal como`, `remeto`, `remissão` (remeter),
  - `fl. <nº>`, `evento/fl <nº>`, `despacho/decisão anterior`, `já decidido`,
  - `manifestação/ato de fl.` , `prossiga conforme`, `dê-se vista do...`.
- Preencher `Movement.referenced_event` + `Movement.referenced_event_obj`
  (resolve a FK p/ o ato anterior quando possível).
- Armazenar também um **trecho citado** (`snippet`) do que a remissão aponta.

### Fase 2 — RAG contextual (matching por ato referenciado)
- Quando um processo tem `referenced_event_obj`, montar o texto de busca RAG
  como: `despacho_ato + despacho_observacao + texto_do_ato_referenciado`.
- Filtrar RAGs que tenham flag `requer_referencia: true` (novo campo) para os
  casos de remissão, evitando casar um RAG "genérico" que não considere o
  histórico.
- Se o ato anterior for de natureza diferente do despacho atual, marcar
  `prioridade_baixa` e **propor humanamente primeiro** (não executar direto).

### Fase 3 — Sequência "remissão" no JSON
- Novo passo/convenção na `sequencia_cumprimento`, ex:
  ```json
  {
    "tipo": "remissao",
    "acao": "prosseguir" | "aguardar" | "intimar" | "abster",
    "base_em": "referenciado",
    "observacao": "Conforme despacho de fl. anterior..."
  }
  ```
- Permitir que o resolvedor, ao casar um RAG de remissão, **preencha a
  observação injetando o texto do ato referenciado** (dados dinâmicos nunca
  hardcoded — vêm do `referenced_event_obj`).

### Fase 4 — Modo seguro e validação
- Rodar esses casos em **modo de decisão assistida**: robô monta a proposta
  (texto + ato referenciado puxado) com `nao_concluir`/pré-preenchido, e o
  usuário só confirma/ajusta e decide se está certo. Após N acertos confirmados do
  mesmo padrão, liberar execução direta daquele RAG.
- Critério de acionabilidade: exibir "o que a remissão efetivamente demanda"
  pro usuário; se o ato anterior **não** suporta ação → `abstenção`.

### Fase 5 — Métrica
- Classificar os records novos em `cumprido`/`falha`/`dispensado` como hoje e
  medir quantos % desse bucket passa a executar com o contexto de remissão.
- Usar o fluxo `fiscalizar_processo.py` para acompanhar o desfecho e
  identificar falsos positivos de remissão.

## Limites honestos (manter no char)
- Remissão nem sempre é acionável → **decisão continua humana** em muitos casos.
- O RAG contextual reduz a dependência, **não elimina** o julgamento.
- Precatória/edital/parte não localizada continuam fora.

## Ordem de priorização (recomendada)
1. Fase 1 (detecção + `referenced_event_obj`) — baixo custo, alto retorno,
   alicerce.
2. Fase 2 (RAG contextual) + Fase 4 (modo seguro) — principal ganho prático.
3. Fase 3 (JSON remissão) — conforme casos reais.
4. Fase 5 (métrica) — contínuo.

## Referências no código
- `processes/models.py` → `Movement` (`referenced_event`, `referenced_event_obj`,
  `act_description`, `document`)
- `processes/movimentacoes_service.py` → `buscar_cumprimentos_similares` /
  `normalizar_texto`
- `projudiProcessNavigator` → parser das movimentações e do histórico
- `docs/APRENDIZADOS.md` → seção sobre tipo documental e re-execução

---
*Criado em 2026-08-05. Plano de implementação posterior — sem impacto no fluxo atual.*