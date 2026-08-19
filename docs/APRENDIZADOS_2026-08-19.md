# Aprendizados 2026-08-19 — RAGs, Mandados e Intimação (consolidado)

Sessão completa: sentença de execução, localizador na mesma movimentação,
mandado só-expedição, prazo 10 dias, layout do modelo #9, endereço limpo,
encoding UTF-8 na observação. **Tudo num lugar só.**

## 1. Novo campo `servidor` (Secretário Judicial) no `_gerar_html`
- `expedir_rapido._gerar_html(..., servidor=None)` ganhou o campo `servidor`
  default **`MAURO EMILIO VIANA DA SILVA MOREIRA`**.
- É o nome do Secretário Judicial — placeholder para trocar quando preciso.
- O modelo #9 assina: data → **SECRETÁRIO JUDICIAL** ({{ servidor }}) → **JUIZ
  DE DIREITO** ({{ despacho_autor }}, Martinho Ferraz da Nóbrega Júnior), uma
  abaixo da outra.

## 2. `_limpar_endereco` — endereço limpo no mandado
- Novo helper `_limpar_endereco(endereco)` em `expedir_rapido.py`.
- Remove: vírgulas com segmentos vazios, `<br>`, sufixos `- BA`/`- BRASIL`,
  o bloco `CEP xxxxx-xxx` (isola numa linha própria), pontuação residual.
- Ex: `RUA Campo Grande, , 113, , APTO SANDES CONSTRUCOES, , Perpétuo
  Socorro, , , , PAULO AFONSO, , , - BA, , BRASIL, <br>CEP 48603-190`
  → `RUA Campo Grande - 113 - APTO SANDES CONSTRUCOES - Perpétuo Socorro -
  PAULO AFONSO<br>CEP 48603-190`.
- Aplicado no ctx `parte.endereco`/`partes[].endereco` do `_gerar_html`.

## 3. TEOR DO DESPACHO = texto REAL do processo (não o da RAG)
- Ramo `mandado` de `_executar_sequencia_rapido` (duas subidas: polo geral e
  individual): `rag_ctx.despacho_observacao` agora usa o **`texto` real** da
  movimentação/processo quando `len > 15`, senão o texto-âncora da RAG.
- Isso faz o mandado pegar QUALQUER teor de despacho real (com detalhes da
 quele processo: parte, valores, condicionantes), não o texto genérico da RAG.
- Mantém `_preencher_observacao_eventos` p/ `{{evento}}`.

## 4. Layout do modelo #9 (Mandado de Intimação com TEOR)
Ajustado via `DocumentTemplate id=9`:
- **TEOR DO DESPACHO** → `text-align:center`.
- **Cumpra-se.** → `text-align:left`.
- **Data** (Paulo Afonso/BA) → `text-align:center`.
- **Endereço do destinatário** → à esquerda, alinhado ao corpo
  (`max-width:750px; margin:12px auto 6px`).
- **Assinaturas** uma abaixo da outra: Secretário Judicial → Juiz.
- **CPF/CNPJ do destinatário REMOVIDO** do bloco destinatário (não aparece).

## 5. RAG #2560 — SÓ expedição de mandado (FONAJE 142, parte específica)
`criar_rag_fonaje_mandado_fonaje.py` (idempotente).
```json
[{"tipo":"mandado","template_id":9,"polo":"reu_especifico","subtipo":"11",
  "observacao":"Conforme enunciado 142 do FONAJE, intimem-se... Expedição de mandado."}]
```
- `tipo: mandado` puro → confecciona completo SEM intimação eletrônica em
  passo separado. Distinguir de `intimacao_completa` (2528) que intima + soli.
- Validado ao vivo 41020221551907: eventos 260-262, destinatário PAULO MIGUEL.

## 6. RAG #2559 — Sentença de execução (intimação + localizador na mesma mov)
`criar_rag_sentenca_execucao_transferencia.py`.
```json
[{"polo":"todos","tipo":"intimacao_eletronica","fluxo":"analisar",
  "fallback":"solicitar_expedicao","codigo_mov":"581","fallback_ar":true,
  "descricao_mov":"Intimação","fallback_polo":"autores","fluxo_fallback":true,
  "prazo_intimacao":"10","tipo_localizador":"10492","localizador":"",
  "observacao":"Intimem-se as partes da Sentença de Extinta da Fase de Execução... SCR. P. R. I."}]
```
- `prazo_intimacao: "10"` → sentença = 10 dias (código 3). A extração do texto
  pegaria o "15 dias das custas"; o prazo no JSON tem precedência.
- `tipo_localizador: "10492"` → RECOLHIMENTO DE CUSTAS aplicado NA MESMA mov.

## 7. Localizador na MESMA movimentação (intimação)
- `executar_com_intimacao` ganhou params `tipo_localizador`/`localizador`.
- Novo helper `_preencher_localizador(page, tipo_localizador, localizador)`
  chamado ANTES do Concluir nos dois fluxos (A: MovimentarAnalise, B:
  MovimentarProcesso).
- `expedir_rapido.py` repassa `passo.get('tipo_localizador')`/`localizador`.
- **Persistência exige**: JS `sel.value=... + dispatchEvent('change')` +
  clique no botão `img[src*="bot-adicionar"]` ("Adicionar"). Só
  `select_option` NÃO salva.
- **Pre-check anti-duplicata**: `page.locator('#trTbTipoLocalizador{codigo}')`
  já existe → pula o "Adicionar". Confirmado: processo saiu
  `RECOLHIMENTO DE CUSTAS; ALVARA` sem duplicar.

## 8. Prazo de SENTENÇA = 10 dias (vs prazo das custas)
- `extrair_prazo_dias(texto)` pega o PRIMEIRO "prazo de N dias". Numa sentença
  de execução o texto traz "prazo de 15 dias para pagamento" (das CUSTAS) e a
  extração usava 15 para a INTIMAÇÃO — errado.
- Forçar `prazo_intimacao: "10"` no JSON (converte → código 3). Manter o "15
  dias das custas" na observação (são prazos distintos; o Ivan quer os dois).

## 9. Encoding UTF-8 na observação (corrigia mojibake)
- `MovimentacaoService.executar_requests` montava tudo `.encode('latin-1')`.
- Campo `observacao` agora **UTF-8** (`str(v).encode('utf-8')`); demais campos
  continuam latin-1. Corrige "intimaÃ§Ã£o" → "intimação".

## 10. RAGs bloqueadoras (1538, 4374)
- `criar_rag_bloqueio_1538_4374.py`.
- **2557** (cancelamento audiência/endereço atualizado): frases AND
  `cancelamento da audiencia de instrucao` + `endereco atualizado da referida parte`.
- **2558** (busca RENAJUD por chassi): frases AND `numero do chassi` + `renajud`.
- `sequencia_cumprimento` vazio = BLOQUEIO total; `encontrar_bloqueio` roda
  ANTES do matching por similaridade.

## 11. RAGs de intimação do autor do fato (mandado) — 2555/2556
`criar_rag_intimacao_autor_fato_mandado.py`.
- **2555** EXPEDIÇÃO de mandado: `tipo:mandado, template_id:9, polo:reu_especifico`.
- **2556** SOLICITAÇÃO de expedição: `tipo:solicitar_expedicao, polo:reu_especifico`.
- "autor do fato" em criminal = **RÉU** (polo passivo) → `reu_especifico`.
- Oficial de Justiça = MANDADO, não intimação eletrônica.
- `{{evento}}` substituído dinamicamente pelo executor.
- Textos de matching idênticos → se sombreiam; Ivan decide por vara.

## 12. Vitória do matching no `_melhor_match`
- `_melhor_match` retorna a PRIMEIRA de `similares` com `sequencia_cumprimento`.
- RAGs com texto de matching idêntico ao mesmo despacho colidem — a de menor
  id vence. Gerenciar por vara/processo.

## Arquivos desta sessão (novos)
- criar_rag_fonaje_mandado_fonaje.py
- criar_rag_sentenca_execucao_transferencia.py
- criar_rag_bloqueio_1538_4374.py
- criar_rag_intimacao_autor_fato_mandado.py
- (já existentes, re-usados: criar_rag_bloqueio_deposito_seguro.py,
  criar_rag_bloqueio_parte_condenada_credito.py)

## Arquivos modificados
- expedir_rapido.py          — servidor, _limpar_endereco, TEOR real,
                              localizador repassado, {{evento}}
- projudi/movimentacao_service.py — executar_requests UTF-8 obs,
                              executar_com_intimacao localizador,
                              _preencher_localizador
- projudi/cumprimento_service.py  — _rotulo_parte promovido(a)(s),
                              _texto_observacao_prazo novo formato,
                              _capitalizar_nome_proprio
- processes/admin.py
- DocumentTemplate id=9 (banco) — layout / assinaturas / sem CPF
