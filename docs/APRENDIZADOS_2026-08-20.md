# APRENDIZADOS — SESSÃO 2026-08-20 (RAGs, prazo dinâmico, sombreamento, TEOR)

> Backup de contexto p/ não esquecer amanhã. Espelho da referência da skill
> `projudi-movimentacoes-rag` (`references/melhores-rags-json.md`), que você mantém
> sincronizada com `docs/MELHORES_RAGS_JSON.md`. Isto aqui é o RESUMO EXECUTIVO +
> passos operacionais que importam.

Commit desta rodada: **a00519b** (último). Sessão do dia: 2026-08-20.

---

## 1) ESTRUTURA DE RAG (sequencia_cumprimento) — padrões que você usa

### Intimação eletrônica + fallback AR + fallback mandado (o "canal")
```json
[{
  "polo": "reu_especifico",
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar", "fluxo_fallback": true,
  "codigo_mov": "581", "descricao_mov": "Intimação",
  "observacao": "...",
  "motivo_intimacao": "3",
  "fallback_ar": true, "assinar_ar": true,
  "fallback": "mandado",            # OU "solicitar_mandado"
  "fallback_template_id": 9,        # p/ EXPEDIR (modelo com TEOR)
  "mandado_polo": "reu_especifico", "mandado_subtipo": "11"
}]
```
- **3 variações (toggle) que você curtiu** — o que muda é só o destino do mandado:
  1. sem chave `fallback` → só intima (e+AR se sem DJEN)
  2. `fallback:"solicitar_mandado"` → + solicita a expedição (Mov581, sem confecção)
  3. `fallback:"mandado"` + `fallback_template_id:9` → + EXPEDE o mandado completo (TEOR)
- `assinar_ar` true = expede AR assinado; false = deixa p/ assinatura manual.
- `polo` vocabulário rígido: `reu_especifico` | `autor_especifico` | `autores` | `res` |
  `exequentes` | `todos`. Fora do mapa cai no `else` (réu) — preste atenção.

### Certidão de prazo + intimação (2 passos) — RAG #2538 (modelo principal de PENHORA)
```json
[{"tipo":"movimentacao","polo_prazo":"ambos","flag_certidao":true,
  "observacao_prazo":true,"expede_certidao_prazo":true,
  "exigir_intimacao_penhora":true, "decurso_prazo":true},
 {"tipo":"intimacao_eletronica","observacao":"...",
  "json_intimacao_eletronica":{ "de":"exequente","para":"autor_e_reu","texto_base":"..." }}]
```
Flags de prazo (lidas por `_config_prazo_do_rag`, item casado por `tipo`='movimentacao'):
- `observacao_prazo` → põe a contagem na observação do Mov581.
- `expede_certidao_prazo` → expede a CERTIDÃO DE PRAZO (template id=11).
- `polo_prazo` → `autor` | `reu` | `ambos` (p/ quem corre).
- `exigir_intimacao_penhora` → **TRAVA**: só cumpre se o tracker achar intimação DA PENHORA.
- `decurso_prazo` → certidão/obs "Decorrido" só se o prazo DECORREU (`res.vencido`).

### Outros tipos úteis
- `localizar` (só altera localizador): obs "Ao loc 2", `tipo_localizador`:
  **22614=SISBAJUD, 11916=RENAJUD, 22644=SNIPER**, 10492=RECOLHIMENTO DE CUSTAS,
  22157=PARA CÁLCULO DE CUSTAS, 9376=PESQUISA DE ENDEREÇO, 15286=AGUARDAR DECURSO.
- `solicitar_expedicao` (só Mov581, sem confecção) — par toggle do `mandado`.
- `mandado` (subtipo 11, template_id 9 → TEOR do despacho).
- **BLOQUEADORAS**: `sequencia_cumprimento: []` = NÃO CUMPRIR (travamento total).

---

## 2) SOMBREAMENTO E CURADORIA — regra crítica (acho que é o mais importante)

O `_melhor_match` retorna a 1ª RAG ativa com sequência; **pra MESMO texto vence a de MENOR id**.
Logo: criar RAG nova específica com texto já coberto por uma antiga/catch-all → a NOVA É SOMBREADA
(nunca roda). A curadoria é DESATIVAR as antigas redundantes p/ as novas darem lugar.

Estado curado das famílias (dono por texto):
- INDEFIRO liminar art.300 (força de mandado) → **#2574** (trio, ativa)
- CONCEDIDA liminar energia (mandado e ofício) → **#2577** (trio, prazo dinâmico)
- DECISÃO INDEFIRO + inversão do ônus → **#2583** (trio)
- INTIME-SE parte demandada sobre pedido liminar → **#2568** (certidão→intimação, dona)
- Confirmado: cada família cai no dono (validação cruzada j=1.00).

Desativadas nesta sessão (eram as que sombreavam / redundantes):
`#2487, #2452, #2529, #2546(≠? não – #2546 virou localizar), #2480, #2478, #2486, #2458,
#2447, #2451, #2449, #2525, #2580, #2581, #2582` — e a #2562-2565/2566/2567/2568/2569/2570/
2571 receberam ajustes (ver git). Sempre que criar RAG p/ texto já coberto, VERIFIQUE quem
vence (`buscar_cumprimentos_similares`) e desative a antiga se for redundante.

**NUNCA consolidar pares complementares** (expedir↔solicitar, certidão↔certidão+intimação,
#2561↔#2571, #2555↔#2556). Alterna `active` por botão/admin.

---

## 3) PRAZO DINÂMICO (extração + códigos reais do painel)

- **Tabela real `codPrazoAutor/codPrazoReu`** (dias→código) em `projudi/movimentacao_service.py`
  `prazo_dias_map`: 1→10, 2→1, 3→11, 4→47, 5→2, 6→48, 7→49, 8→50, 9→51, 10→3,
  11→52, 12→53, 13→54, 14→55, 15→4, 16→56, 17→57, 18→58, 19→59, 20→60, 21→61, 22→62,
  23→63, 24→64, 25→65, 26→66, 27→67, 28→68, 29→69, 30→5, 35→70, 40→6, 45→71, 50→7,
  55→16, 60→8, 65→17, 70→18, 75→19, 80→20, 85→21, 90→22, 95→23, 100→24, 105→25,
  110→26, 115→27, 120→9, 180→29 (6 meses). Sem prazo citado → despacho=5(cód 2)/sentença=10(cód 3).
- `extrair_prazo_dias` (`processes/movimentacoes_service.py`): suporta **horas→dias (min 1)**
  (48h→2, 24h→1, 8h→1) e normaliza `05'→'5'`. Retorna `''` se não achar.
- **Limão**: "X meses" não é extraído (só dias/horas). Se precisar, adicionar mapeamento meses.
- Sem `prazo_intimacao` na RAG → o executor EXTRAI da decisão (dinâmico). Fixo = override.

---

## 4) CALENDÁRIO / FERIADOS / SUSPENSÕES

Seeded no **tenant 1** (2025-12→2026-10), 22 registros via `popular_feriados_local_2026.py`:
- Suspensões: recesso 19/12/25–06/01/26, suspensão processual 07–20/01/26, carnaval 12–18/02/26,
  copa do mundo 29–30/06/26.
- Feriados unico: sexta santa 02–03/04, tiradentes 20–21/04, trabalhador 01/05, corpus 04–05/06,
  são joão 22–24/06, indep. BA 02–03/07, aniv. PA 27–28/07, dia do magistrado 10–11/08,
  aparecida 12/10, dia do servidor 30/10.
- `PrazoService.from_db(tenant)` já inclui nacionais fixos/móveis + lê do banco (desligando recesso
  hardcoded se houver `recesso_local`). Contagem DJEN: dia+1º útil excluídos (art. 5 §3º CPC);
  advogado: só dia do recebimento excluído (art. 219 §1º).

---

## 5) TRAVA DE PENHORA + DECURSO (fluxo seguro que você pediu)

Em `CumprimentoService`:
- `_data_intimacao_do_tracker(record)` agora retorna **`(data, origem)`** — origem `'penhora'`
  (penhora+intimação ou 'penhora realizada') vs `'sentenca'/'djen'/'leitura'/'intimacao'/'referencia'`.
- `_config_prazo_do_rag` lê `exigir_intimacao_penhora` e `decurso_prazo`.
- `gerar_observacao_prazo`:
  - TRAVA penhora vem ANTES do erro de data/prazo → sem intimação da penhora → `skip_penhora`,
    status **`dispensado`**, não cumpre.
  - `decurso_prazo` + prazo não decorrido → `decurso_pendente`, status pendente, não expede a certidão.
- `executar_cumprimento` **ABORTA** (retorna antes de rotear à intimação) se `skip_penhora` ou
  `decurso_pendente`.
- **Fluxo (regra sua):** sem intimação da penhora OU prazo não decorrido → NÃO executa mais nada e
  sai. Achou a da penhora + prazo decorreu → gera obs_decurso/certidão + intimação se houver.
- ⚠️ Se a penhora só existe em PDF anexo (não vem como ato), o tracker NÃO acha → trava pula
  (dispensado). Correto por segurança.

---

## 6) TEOR DO MANDADO — limpeza (cabeçalho + rodapé)

`_limpar_teor_para_mandado` (`expedir_rapido.py`) remove:
- **Cima:** "PODER JUDICIÁRIO.../vára" até o TÍTULO (DESPACHO/DECISÃO/SENTENÇA/ACÓRDÃO/MANDADO/
  EDITAL/OFÍCIO ± ¹).
- **Baixo:** de **"Paulo Afonso"** pra baixo (cidade/data/assinatura do juiz).
Aplica aos mandados/ofícios que injetam o teor real (2 ramos de `_executar_sequencia_rapido`).

---

## 7) OBSERVAÇÃO JUNTADA (certidão + obs do Mov581)

Em `observacao_para_movimentacao`: quando `expede_certidao_prazo` E `observacao_prazo` ativas,
a observação do Mov581 = `{snippet/trecho da decisão} | {decurso do prazo}` (primeiro a observação,
depois o decurso), truncada em 500. Sem snippet → só o decurso.

---

## 8) ADMIN — ações em lote p/ toggle

`RAGExampleAdmin` ganhou: **`⬜ Desativar RAG selecionada(s)`** e **`✅ Ativar RAG selecionada(s)`**
(`processes/admin.py`). Use no `/admin/processes/ragexample/` pra alternar pares/trios sem editar
uma a uma.

---

## 9) SYNC DE ATOS (p/ alimentar o tracker)

`scripts/pegar_atos_processo.py --interno <n>` — **corrigido o bootstrap** (agora roda direto como
script; antes faltava `django.setup()`). Requer **sessão Projudi ativa** (cookies); se expirada avisa.
Salva Process + Movement (75 movs no 41020254424576/processo 185). **É PRECISO** p/ o tracker achar
a data da intimação (senão cai na genérica). O processo 0003558 NÃO tem penhora nos atos hoje.

---

## 10) OPERACIONAL IMPORTANTE

- **Servidor roda com `--noreload`** (PID pode mudar): mudanças de `.py` SÓ valem após REINICIÁ-LO.
  Scripts avulsos (sync, manage.py) já pegam o código novo.
- **Famílias liminar** e demais RAGs novas estão no banco; scripts idempotentes no repo raiz:
  `criar_rag_*.py`, `popular_feriados_local_2026.py`, `_auditar_rags.py`, `aplicar_correcoes_rags.py`,
  `_validar_*.py`, `_dump_rags_json.py`.
- **Docs**: skill `projudi-movimentacoes-rag/references/melhores-rags-json.md` (fonte) ↔
  `docs/MELHORES_RAGS_JSON.md` (sincronizar com `cp` sempre que editar a skill).
- **Skills**: `projudi-rag-auditoria`, `projudi-prazo-service`, `mandado-expedicao-polo-fallback`,
  `rag-bloqueio-configuracao-fallback-ar`.

---

## 11) PENDÊNCIAS / O QUE TESTAR AMANHÃ

1. **Reiniciar o servidor** (roda `--noreload`) e re-processar #268/#269 (rag #2538) — devem virar
   `dispensado` (skip_penhora) com log.
2. **Prazo dinâmico meses** — decidir se adiciona "X meses" na extração (5m→28, 6m→29, ...).
3. **referenced_event** — o despacho que referencia um anterior: estender o tracker pra procurar o
   ato penhora referenciado antes do fallback (hoje a trava de skip já protege).
4. **Sincronizar um processo real em fase de PENHORA** (com despacho "certifique-se o decurso...")
   pra validar o fluxo completo de ponta a ponta.
5. **Commit agrupado** — sessão toda já comitada (sem push). Próximo passo: push quando validar.
