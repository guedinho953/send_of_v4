# 📚 Melhores JSONs de RAG (sequencia_cumprimento) — curadoria 2026-08-20

Catálogo dos JSONs de `RAGExample.sequencia_cumprimento` mais **completos e
validados em processo real** do Projudi (2ª VSJ Paulo Afonso). Copie, adapte o
`despacho_ato`/`despacho_observacao` (texto de matching) e a `observacao`
(texto da movimentação) por caso.

> **Regras globais (vale para TODAS):**
> - Nome de parte NUNCA vai no JSON (vem do processo). Remover banco/CNJ/evento
>   fixo do texto de matching para generalizar.
> - `polo` no vocabulário do executor: ATIVO = `autores`/`autoras`/`promoventes`/
>   `exequentes`/`autor_especifico`; PASSIVO = `res`/`reus`/`executados`/
>   `promovidos`/`reu_especifico`; `todos`/`ambos`. Valor fora do mapa cai no
>   `else` (= busca réu → lado errado).
> - `fluxo: analisar` SEMPRE com `fluxo_fallback: true` (senão → "cumprido sem
>   ação").
> - AR/mandado só materializam para parte que NÃO recebeu eletrônica (sem DJEN)
>   — fallback automático.
> - `fallback` correto é `solicitar_expedicao` (NÃO `solicitar_expecidao` — typo).
> - ⚠️ **Recall do matching exige ≥2 tokens** (`if len(intersecao) >= 2`). Uma RAG
>   de âncora ÚNICA (ex.: só "reitere") é **descartada do recall** e nunca disputa —
>   o despacho cai em RAG errada. Bloqueios genéricos precisam de **2 tokens**
>   (ver seção bloqueio nacional abaixo).

## 0) RAG BLOQUEADORA (NÃO CUMPRIR) — reiteração de diligência/ofício/intimação
**Uso:** despachos que só REITERAM uma diligência anterior ("Diante do informado
no evento 226, reitere-se a diligência de evento 218"). Sem comando novo de
juntada/expedição → NÃO executar nada. `sequencia_cumprimento = []` = BLOQUEIO.
**Uma RAG por objeto** (cada uma 2 tokens: `reitere-se` + objeto) → jaccard 1.00
e recall ≥2; não se sombreiam (objeto diff). Só o nº do evento é removido
(ruído); "reitere-se" + objeto ficam.
```json
[
  { "despacho_ato": "REITERE-SE DILIGÊNCIA", "obs": "Reitere-se a diligência.",
    "seq": [] },
  { "despacho_ato": "REITERE-SE OFÍCIO",     "obs": "Reitere-se o ofício.", "seq": [] },
  { "despacho_ato": "REITERE-SE INTIMAÇÃO",  "obs": "Reitere-se a intimação.", "seq": [] },
  { "despacho_ato": "REITERE-SE COMUNICAÇÃO","obs": "Reitere-se a comunicação.", "seq": [] }
]
```
> ✅ RAGs #2562/#2563/#2564/#2565 (2026-08-20): cada reiteração bloqueia a jaccard
> 1.00; um despacho real de intimação ("evento" sem "reitere-se") NÃO é bloqueado
> (segue para a RAG de cumprimento). Validação: `buscar_cumprimentos_similares` + loop de bloqueio.

### Outras bloqueadoras (2026-08-20) — `seq = []`
- **#2566 INTIMAÇÃO ELETRÔNICA REALIZADA** (certidão informativa "intimo a parte em 15 dias")
  e **#2567 EXPEDIR NOTIFICAÇÃO** — pendentes sem match viram bloqueio até ajeitar.
- **#2572 DESPACHO COM FORÇA DE MANDADO E OFÍCIO — JUÍZO DEPRECADO / DEVOLUÇÃO DE CARTA
  PRECATÓRIA**: ofício ao juízo deprecado (30d) + "Em caso de insucesso, conclusos" → bloqueia.
  j=0.92.
- **#2573 CARTA PRECATÓRIA SEM CUMPRIMENTO — CERTIFICAR CUMPRIMENTO DE DESPACHO ANTERIOR**:
  condicional "Em caso positivo, intime-se a parte exequente..." (exige certidão prévia do
  cumprimento do despacho anterior) → bloqueia. j=0.92.

---

## 1) INTIMAÇÃO COMPLETA + MANDADO (En. 142 FONAJE) — RAG #2528
**Uso:** intimar executado(s) na pessoa do advogado (ou pessoal) acerca do
bloqueio SISBAJUD + renovar ordem de penhora + expedir mandado. Mandado com
TEOR DO DESPACHO (`fallback_template_id: 9`).
```json
{
  "polo": "reu_especifico",
  "tipo": "intimacao_completa",
  "fluxo": "analisar",
  "fallback": "solicitar_expedicao",
  "assinar_ar": false,
  "codigo_mov": "581",
  "expedir_ar": false,
  "observacao": "Intimem-se o(a)(s) executado(a)(s) na pessoa de seu advogado(a) ou, não o tendo, pessoalmente, para, querendo, no prazo de 15 (quinze) dias, apresentar manifestação/impugnação/embargos à execução acerca do bloqueio efetivado (SISBAJUD).",
  "fallback_ar": true,
  "mandado_polo": "reu_especifico",
  "nao_concluir": false,
  "descricao_mov": "Intimação",
  "fallback_polo": "res",
  "fluxo_fallback": true,
  "mandado_subtipo": "11",
  "prazo_intimacao": "4",
  "motivo_intimacao": "3",
  "solicitar_mandado": true,
  "fallback_template_id": 9
}
```

## 2) INTIMAÇÃO ELETRÔNICA + AR ASSINADO + MANDADO (parte exequente) — RAG #2548
**Uso:** intimar parte exequente a cumprir o art. 524 CPC com memorial de
cálculo. Referência para o padrão "intimação eletrônica + fallback AR assinado
+ solicitar mandado" corrigido em processo real.
```json
{
  "polo": "exequentes",
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar",
  "fallback": "solicitar_mandado",
  "assinar_ar": true,
  "codigo_mov": "581",
  "observacao": "Intime-se a parte exequente, através de seu Advogado, para no prazo de 05 dias cumprir o disposto no art. 524 do CPC, instruindo a petição com memorial de cálculo.",
  "fallback_ar": true,
  "mandado_polo": "exequentes",
  "descricao_mov": "Intimação",
  "fallback_polo": "exequentes",
  "fluxo_fallback": true,
  "mandado_subtipo": "11",
  "prazo_intimacao": "5",
  "motivo_intimacao": "3",
  "solicitar_mandado": true
}
```
> ⚠️ `polo: exequentes` (plural) — `exequente_especifico` NÃO existe no mapa e
> cai no `else`.

## 3) INTIMAÇÃO ELETRÔNICA + fallback AR/mandado (FONAJE 142) — RAG #2560
**Uso:** despacho FONAJE 142 (intimar executado(s) na pessoa do advogado /
pessoalmente, embargos/manifestação acerca do bloqueio SISBAJUD, 15 dias).
Intimação eletrônica primeiro; se a parte não tem DJEN e última comunicação é
AR → expede AR **SEM assinar**; senão → solicita mandado (modelo #9 com TEOR).
```json
{
  "polo": "reu_especifico",
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar",
  "fluxo_fallback": true,
  "codigo_mov": "581",
  "descricao_mov": "Intimação",
  "observacao": "Conforme enunciado 142 do FONAJE, intimem-se o(a)(s) executado(a)(s) na pessoa de seu advogado(a) ou, não o tendo, pessoalmente, para, querendo, no prazo de 15 (quinze) dias, apresentar(em) manifestação/impugnação/embargos à execução acerca do bloqueio efetivado (SISBAJUD). Expedição de mandado.",
  "prazo_intimacao": "4",
  "motivo_intimacao": "3",
  "fallback_ar": true,
  "assinar_ar": false,
  "fallback": "solicitar_mandado",
  "solicitar_mandado": true,
  "mandado_polo": "reu_especifico",
  "mandado_subtipo": "11",
  "fallback_template_id": 9,
  "parte_na_observacao": false
}
```
> (2026-08-20: era "mandado puro"; convertida p/ intimação eletrônica + fallback AR/mandado.
> ⚠️ #2528 (intimacao_completa) também casa FONAJE 142 a j=1.00 — a #2560 vence no ranking.)
> **TEOR SEM CABEÇALHO (2026-08-20):** no modelo #9/`{{despacho_observacao}}`, o TEOR
> usa o texto real da movimentação, e o novo helper `expedir_rapido._limpar_teor_para_mandado`
> remove o cabeçalho "PODER JUDICIÁRIO.../vara", começando a partir do TÍTULO
> (DESPACHO/DECISÃO/SENTENÇA/ACÓRDÃO/MANDADO/EDITAL/OFÍCIO ± ¹). Aplica-se a TODOS os
> mandados/ofícios que injetam o teor real (ambos os ramos de `_executar_sequencia_rapido`).

## 4) MANDADO VIA OFICIAL DE JUSTIÇA com {{evento}} — TOGGLE #2555 (expedir) / #2556 (solicitar)
**Uso:** "intime-se o autor do fato através de Oficial de Justiça para comparecer
à assentada" (criminal: autor do fato = RÉU). `{{evento}}` é substituído pelo
executor. **Par complementar** — alterna `active` conforme a conveniência:
- **#2555 (expedir mandado)** — `tipo: mandado`, confeciona o mandado completo.
- **#2556 (solicitar expedição)** — `tipo: solicitar_expedicao`, só Mov581, SEM fallback.
Ambos com `fluxo: analisar` + `fluxo_fallback: true`.
```json
{ "polo": "reu_especifico", "tipo": "mandado", "subtipo": "11",
  "observacao": "Intime-se o autor do fato, atraves de Oficial de Justica, para comparecer a assentada, diante do resultado da comunicacao (evento {{evento}}).",
  "template_id": 9, "parte_na_observacao": false, "fluxo": "analisar", "fluxo_fallback": true }
```
```json
{ "polo": "reu_especifico", "tipo": "solicitar_expedicao", "codigo_mov": "581",
  "descricao_mov": "Solicitada a Expedicao de Mandado",
  "observacao": "... (evento {{evento}}) ... Solicitada a expedicao de mandado para o autor do fato.",
  "parte_na_observacao": false, "fluxo": "analisar", "fluxo_fallback": true }
```

## 5) INDEFERIMENTO LEVANTAMENTO DA SUSPENSÃO / TEMAS REPETITIVOS (réu) — RAG #2561
**Uso:** despacho "INDEFIRO o pedido de levantamento da suspensão... permanece
suspenso... Temas Repetitivos... Intimem-se" (RMC). Intima o RÉU específico;
AR assinado + mandado SÓ se o réu não recebeu a eletrônica (DJEN).
```json
{
  "polo": "reu_especifico",
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar",
  "assinar_ar": true,
  "codigo_mov": "581",
  "observacao": "Intime-se a parte promovida (réu) para ciência do indeferimento do pedido de levantamento da suspensão, permanecendo o feito suspenso até ulterior deliberação do STJ sobre os Temas Repetitivos n.º 1.328 e n.º 1.414.",
  "fallback_ar": true,
  "mandado_polo": "reu_especifico",
  "descricao_mov": "Intimação",
  "fallback_polo": "res",
  "fluxo_fallback": true,
  "mandado_subtipo": "11",
  "prazo_intimacao": "5",
  "motivo_intimacao": "3",
  "solicitar_mandado": true
}
```
> ✅ Validação 2026-08-20: `buscar_cumprimentos_similares(texto_real)` → jaccard
> 0.96, vence sozinha (2º candidato 0.50, abaixo do corte 0.70). Nenhuma RAG
> antiga sombreia.
- **TOGGLE PAREADO (2026-08-20):** #2561 fica na variante **SOLICITAR** mandado
  (`solicitar_mandado:true`) e a #2571 (inativa) na variante **EXPEDIR** mandado
  (`fallback:"mandado"` + `fallback_template_id:9`, confecciona o mandado com
  TEOR). Alterna `active` conforme a conveniência — mesmo padrão de #2555/#2556.

## 6) 2 PASSOS: CERTIDÃO DE PRAZO + INTIMAÇÃO ELETRÔNICA (json_intimacao_eletronica) — RAG #2538
**Uso:** "Certifique-se o decurso do prazo para impugnação à penhora; em caso
positivo intime-se a parte exequente..." — combina certidão de prazo com
intimação parametrizada (de/para/texto_base).
```json
[
  {
    "tipo": "movimentacao",
    "polo_prazo": "ambos",
    "flag_certidao": true,
    "observacao_prazo": true,
    "expede_certidao_prazo": true
  },
  {
    "tipo": "intimacao_eletronica",
    "observacao": "Decorrido o prazo reu/autor/ambos especifico em 00/00/00. Intimação(DJEN OU adv ou email, ou ar) em 00/00/00, início do prazo 00/00/00 ultimo dia do prazo 00/00/00",
    "json_intimacao_eletronica": {
      "de": "exequente",
      "para": "autor_e_reu",
      "texto_base": "intime-se a parte autora, através de sua defesa, para requerer o que de direito no prazo de 05 dias. Caso sinalize interesse, intime-se o executado para tomar ciência acerca do pedido de adjudicação formulado pela exequente, para manifestação no prazo de 5 dias, na forma do art. 876, §1º, do CPC."
    }
  }
]
```

## 7) 2 PASSOS: LOCALIZAR (SNIPER) + INTIMAÇÃO — RAG #2542
**Uso:** juntar resultado de busca SNIPER e depois intimar a parte exequente para
manifestação. Bom exemplo de passo `localizar` + passo `intimacao_eletronica`.
```json
[
  {
    "tipo": "localizar",
    "fluxo": "analisar",
    "codigo_mov": "581",
    "observacao": "Ao loc sniper",
    "localizador": "",
    "descricao_mov": "Intimação",
    "tipo_documento": "CUMPRIMENTO",
    "tipo_localizador": "22644"
  },
  {
    "polo": "autor_especifico",
    "tipo": "intimacao_eletronica",
    "fluxo": "analisar",
    "fallback": "solicitar_expedicao",
    "codigo_mov": "581",
    "observacao": "Intime-se a parte exequente para manifestação sobre o resultado da busca SNIPER, no prazo de 05 dias.",
    "fallback_ar": true,
    "descricao_mov": "Intimação",
    "prazo_intimacao": "5",
    "motivo_intimacao": "3"
  }
]
```

## 8) SÓ LOCALIZADOR (SISBAJUD teimosinha) — RAG #2549
**Uso:** "sigam os autos ao localizador SISBAJUD para penhora... na modalidade
teimosinha". Só mexe no localizador.
```json
{
  "tipo": "solicitar_expedicao",
  "fluxo": "analisar",
  "codigo_mov": "581",
  "observacao": "Ao loc 1",
  "localizador": "",
  "descricao_mov": "Intimação",
  "tipo_documento": "CUMPRIMENTO",
  "tipo_localizador": "22614"
}
```

## 9) SENTENÇA DE EXECUÇÃO + CUSTAS + LOCALIZADOR — RAG #2559
**Uso:** sentença que extingue fase de execução (arts. 925/924 II), custas pela
executada, prazo e localizador de recolhimento de custas. Exemplo de identificar
localizador dentro da própria intimação.
```json
{
  "polo": "todos",
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar",
  "fallback": "solicitar_expedicao",
  "codigo_mov": "581",
  "observacao": "Intimem-se as partes para ciência da Sentença (Extinta da Fase de Execução de Sentença) - CUSTAS da execução pela parte EXECUTADA, com prazo de 15 dias para pagamento, sob pena de inscrição na dívida ativa, através do sistema SCR. Ao loc RECOLHIMENTO DE CUSTAS",
  "fallback_ar": true,
  "localizador": "",
  "descricao_mov": "Intimação",
  "fallback_polo": "autores",
  "fluxo_fallback": true,
  "prazo_intimacao": "10",
  "tipo_localizador": "10492"
}
```

## 10) CATCH-ALL DE EVENTOS (evento genérico) — RAG #2533
**Uso:** capturar despachos com "evento XX" (qualquer número), intimando autora
e réus. Usa placeholders `{{evento_autora}}` / `{{eventos_reus}}`.
```json
{
  "polo": "todos",
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar",
  "fallback": "mandado",
  "assinar_ar": false,
  "codigo_mov": "581",
  "observacao": "Intime-se a parte autora para ciência do evento {{evento_autora}}. Intime-se a(s) parte(s) ré(s) para ciência dos eventos indicados nos autos {{eventos_reus}}",
  "fallback_ar": true,
  "descricao_mov": "Intimação",
  "fluxo_fallback": true,
  "mandado_subtipo": "11",
  "prazo_intimacao": "3",
  "motivo_intimacao": "3"
}
```

## 11) LIMINAR CONCEDIDA → MANDADO IMEDIATO — RAG #2529 (e irmã #2530 Não Concedida)
**Uso:** decisão com força de mandado. A irmã #2530 repete a estrutura com obs
"(LIMINAR NÃO CONCEDIDA / INDEFERIDA)".
```json
{
  "polo": "todos",
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar",
  "fallback": "mandado",
  "assinar_ar": false,
  "codigo_mov": "581",
  "observacao": "Intimem-se as partes para ciência da Decisão (LIMINAR CONCEDIDA), valendo a presente como mandado de intimação.",
  "fallback_ar": true,
  "mandado_polo": "reu_especifico",
  "descricao_mov": "Intimação",
  "fluxo_fallback": true,
  "mandado_subtipo": "11",
  "prazo_intimacao": "3",
  "motivo_intimacao": "3",
  "solicitar_mandado": true
}
```

---

## 12) CERTIDÃO COM INTIMAÇÃO — 1 movimentar (modelo RAG #2569, toggle da #2568)
**Uso:** quando o despacho pede intimação com prazo E você quer confeccionar a
CERTIDÃO na hora de movimentar, preenchendo no MESMO fluxo a intimação eletrônica
(+ MP, localizador, mandado). **UM movimentar, não dois.** Regra do Ivan:
"certidão primeiro, depois as intimações/preenchimentos — mantendo o mesmo fluxo
da certidão, só preenchendo os campos da intimação eletrônica".
```json
{
  "tipo": "intimacao_completa",
  "fluxo": "analisar",
  "fluxo_fallback": true,
  "codigo_mov": "581",
  "descricao_mov": "Intimação",
  "observacao": "Intime a parte. Prazo de 10 dias.",
  "motivo_intimacao": "3",
  "prazo_intimacao": "3",
  "polo": "todos",
  "fallback": "solicitar_expedicao",
  "fallback_ar": false,
  "assinar_ar": false,
  "expedir_ar": false,
  "fallback_template_id": 9,
  "observacao_prazo": true,
  "expede_certidao_prazo": true,
  "flag_certidao": true,
  "polo_prazo": "ambos",
  "envia_mp": false,
  "cod_nucleo_mp": "31",
  "tipo_parecer_mp": "6",
  "prazo_mp": "5",
  "promotor_mp": "",
  "tipo_localizador": "",
  "localizador": "",
  "solicitar_mandado": false,
  "mandado_polo": "reu_especifico",
  "mandado_subtipo": "11"
}
```
- **Relação com #2568:** são DUAS RAGs com o MESMO texto de matching ("Intime a
  parte. Prazo de 10 dias.") — uma "certidão com movimentação" (#2568, 2 passos
  executáveis hoje) e esta "certidão com intimação" (#2569, 1 passo). Alternam
  `active` (como o par mandado ↔ solicitar_expedicao).
- ⚠️ **WIRE PENDENTE (2026-08-20):** o executor `intimacao_completa`
  (`executar_com_intimacao`) AINDA NÃO injeta a certidão de prazo no FCKeditor —
  ela só existe no caminho `cumprimento_service` (`_html_certidao_prazo` →
  `certidao_html`). Até essa wire ser feita, o passo executa a intimação mas a
  certidão NÃO é confeccionada. Manter #2568 ativa enquanto #2569 estiver sem a
  wire.
- **OBSERVAÇÃO JUNTADA (2026-08-20):** em `cumprimento_service.observacao_para_movimentacao`,
  quando `expede_certidao_prazo=true` E `observacao_prazo=true`, a observação do
  Mov581 = `{snippet/trecho da decisão} | {observacao_prazo/decurso}` — primeiro a
  observação ("Intimem-se as partes xxxxx"), depois o decurso do prazo. Trunca a
  ~500 chars. Sem snippet → só o decurso.

---

## SÓ LOCALIZADOR — SISBAJUD / RENAJUD / SNIPER (#2549 / #2546 / #2542)
Despacho que manda APENAS remeter ao localizador — **sem intimação** anexa. JSON
de 1 passo `localizar` (2026-08-20: #2546 e #2542 foram reduzidos de 2 passos
localizar+intimação → 1 só `localizar`):
```json
{
  "tipo": "localizar",
  "fluxo": "analisar",
  "fluxo_fallback": true,
  "codigo_mov": "581",
  "observacao": "Ao loc 2",          // #2546 Renajud; "Ao loc sniper" p/ #2542; "Ao loc 1" p/ #2549
  "localizador": "",
  "descricao_mov": "Intimação",
  "tipo_documento": "CUMPRIMENTO",
  "tipo_localizador": "22614"        // 22614=SISBAJUD | 11916=RENAJUD | 22644=SNIPER
}
```
> Conversão: remova o passo `intimacao_eletronica`, deixe só o `localizar`.
> Valide com `buscar_cumprimentos_similares(texto_real)` ainda pegando a RAG (j~0.93-0.94).

## Observação combinada — obs + certidão de prazo (2026-08-20)
Implementado em `projudi/cumprimento_service.py::observacao_para_movimentacao`:
quando a RAG tem `expede_certidao_prazo=true` **e** `observacao_prazo=true`, a
observação do Mov581 vira `"{obs} | Certidão de Prazo: {obs}"` (truncada a ~500
chars). Só certidão sem obs → observação vazia. Flujo do Ivan: "certidão
primeiro, depois a intimação — mantendo o mesmo fluxo da certidão, preenchendo
os campos da intimação eletrônica".
⚠️ **Wire-gap:** os flags de certidão (`expede_certidao_prazo`/`observacao_prazo`/
`polo_prazo`/`flag_certidao`) só são honrados no caminho `cumprimento_service`
(CumprimentoRecord/#2538). O passo `movimentacao` e o `intimacao_completa` do
`expedir_rapido` NÃO injetam certidão no FCKeditor — a #2569 (certidão+intimação
1 mov) fica dependente dessa wire para realmente confeccionar a certidão.

---

## 13) INADMISSIBILIDADE DO PROCEDIMENTO SUMARÍSSIMO (incompetência por valor) — RAG #2570
**Uso:** sentença que julga extinto sem mérito por inadmissibilidade do
procedimento sumaríssimo — aqui por incompetência do Juizado pois o valor
excede o teto (art. 51, II, c/c art. 3º, I, Lei 9.099/95); sem custas/honorários
(art. 55); "Transitada em julgado, arquive-se. P.R.I." Comando de secretaria =
**intimar as partes** da sentença.
```json
{
  "polo": "todos",
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar",
  "fluxo_fallback": true,
  "fallback": "solicitar_expedicao",
  "fallback_ar": true,
  "codigo_mov": "581",
  "descricao_mov": "Intimação",
  "observacao": "Intimem-se as partes da Sentença de extinção sem resolução do mérito (Incompetência do Juizado Especial por valor excedente ao teto - art. 51, II, c/c art. 3º, I, da Lei nº 9.099/95), para ciência.",
  "prazo_intimacao": "3",
  "motivo_intimacao": "3"
}
```
- Matching GENERALIZADO (remove o valor fixo "R$ 101.553,25" e "corrigido
  acima" — ruído; mantém as palavras-chave).
- ✅ Validação: jaccard 0.89, vence, 1 passo; supera #2484 (incompetência
  absoluta — outra base, 0.62).

## 13) INDEFIRO LIMINAR COM FORÇA DE MANDADO — 3 MODELOS TOGGLE — RAGs #2574/#2575/#2576
**Uso:** "DECISÃO COM FORÇA DE MANDADO¹ ... INDEFIRO O PEDIDO LIMINAR ... FICA
VALENDO A PRESENTE COMO MANDADO. Cumpra-se com urgência." Três modelos para
escolher conforme a necessidade (alterna `active`), TODOS com base em
`intimacao_eletronica` + `fallback_ar:true` + `assinar_ar:true`, mudando só o
destino do mandado:
- **#2574 (ativa)** — só a intimação eletrônica (sem mandado fallback).
- **#2575 (inativa)** — intimação + `fallback:"solicitar_mandado"` (só solicita a expedição do mandado).
- **#2576 (inativa)** — intimação + `fallback:"mandado"` + `fallback_template_id:9` (confecciona o mandado).
Todos: `polo reu_especifico`, `fluxo analisar` + `fluxo_fallback:true`.
- **PRAZO DINÂMICO (2026-08-20):** sem `prazo_intimacao` fixo, o executor extrai o
  prazo da decisão (`extrair_prazo_dias`: "N dias" + horas→dias, mín 1 — ex.: 48h→"2")
  e mapeia pro código do painel via `prazo_dias_map` (1–30 diário + 35…180 dias),
  confirmado no dropdown `codPrazoAutor/codPrazoReu`. Sem prazo citado → sentença=10 (3) /
  despacho=5 (2).

### Curaderia das famílias de liminar (2026-08-20) — quem é o dono de cada texto
Desativadas as catch-alls antigas que produziam o mesmo comportamento pior
(intimação pura) e sombreavam os trios: #2487, #2452, #2529, #2480, #2478,
#2486, #2458, #2447, #2451, #2449, #2525. Mantidas:
- **#2574** (trio, ativo) — INDEFIRO liminar art.300 com força de mandado.
- **#2577** (trio, ativo) — CONCEDIDA liminar energia (mandado e ofício); prazo dinâmico.
- **#2583** (trio, ativo) — DECISÃO INDEFIRO + inversão do ônus.
- **#2568** (dona) — INTIME-SE a parte demandada sobre o pedido liminar (certidão→intimação, prazo 10 fixo, consistente).
- Toggle: as trios #2574/#2577/#2583 têm os pares "solicitar"/"expedir mandado"
  (#2575-2576, #2578-2579, #2584-2585) inativos — ativa conforme a necessidade.
- #2580-2582 (trio "intime-se pedido liminar") desativados como redundantes.

## Códigos de localizador (2ª VSJ PA)
| tipo_localizador | descrição |
|------------------|-----------|
| `22614` | SISBAJUD (loc 1) / penhora teimosinha |
| `11916` | RENAJUD (loc 2) |
| `22644` | SNIPER |
| `9376` | pesquisa de endereço |
| `10492` | RECOLHIMENTO DE CUSTAS |
| `22157` | PARA CALCULO DE CUSTAS |

## Polo × mandado_subtipo
| valor mandado_subtipo | significado |
|----------------------|-------------|
| `11` | Citação/Penhora/Avaliação (padrão) |
| `3` | (variação usada em RAG 2545) |

> Dump completo das 67 RAGs ativas: `python _dump_rags_json.py` no repo.
