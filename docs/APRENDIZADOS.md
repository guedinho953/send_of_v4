# Aprendizados Técnicos — send_of_v4 (Projudi/TJBA)

> Consolidado em 2026-08-04. Este documento reúne todos os aprendizados validados
> em processos reais, incluindo: intimação por AR digital, vistas ao MP, fluxo
> `analisar` (MovimentarAnalise), fallback de fluxo, matching RAG e expedição.

---

## 1. Fluxo da página: `analisar` vs `movimentar` (+ fallback de fluxo)

O passo de intimação/vistas escolhe a **página/fluxo de disparo** via campo `fluxo`:

| `fluxo` | Página | Quando usar |
|---|---|---|
| `analisar` (padrão) | `MovimentarAnalise?codAnalise=X` | mov está na lista de análises pendentes |
| `movimentar` | `MovimentarProcesso/MovimentarProcessoAvancado` (link genérico) | sempre funciona |

**REGRAS (Ivan):**
- Só existe fallback de fluxo **analisar → movimentar**, NUNCA o contrário.
- `"fluxo_fallback": true` → sem `codAnalise`, cai para o link genérico (Fluxo B).
- Sem `fluxo_fallback`, sem `codAnalise` → **pula a intimação** (não há análise pendente).
- `fluxo_processo: true` (antigo) = atalho para `fluxo: "movimentar"`.

**⚠️ CRÍTICO — o clique que tira da fila:**
No fluxo `analisar`, abrir `MovimentarAnalise?codAnalise=X` NÃO basta: a página
abre com um link **"Movimentar" / "movimentar genericamente"** que PRECISA ser
clicado para chegar ao formulário de movimentação. É **esse clique + Concluir**
que remove a análise da fila de pendentes. Sem ele, a movimentação acontece mas
**o processo continua na fila** (bug real encontrado no 0000386).

```python
# projudi/movimentacao_service.py — executar_requests(), fluxo A
if cod_analise:
    for sel in ['a:has-text("Movimentar Genericamente")',
                'a:has-text("Movimentar genericamente")',
                'a:has-text("Movimentar Processo Genericamente")',
                'a:has-text("Movimentar Processo")',
                'a:has-text("Movimentar")']:
        el = page.query_selector(sel)
        if el and el.is_visible():
            with page.expect_navigation(...): el.click()
            break
```

**Como obter o codAnalise:** vem no link `movimentar` da própria movimentação
pendente (`projudi_client.extrair_links_movimentacoes` → campo `movimentar` =
`https://.../cadastros/MovimentarAnalise?codAnalise=X`). Extrair com:

```python
mov_link = mov.get('movimentar', '')
if mov_link and 'codAnalise=' in mov_link:
    cod_analise = mov_link.split('codAnalise=')[1].split('&')[0]
```

**`#btnAddCumprimento`:** no fluxo A ele JÁ vem visível — clicar direto (PASSO 2).
**NUNCA repetir o clique depois** (havia um PASSO 6 redundante que travava 30s
porque o botão some após a adição do cumprimento).

---

## 2. Vistas ao MP (passo `vistas_mp` — Mov 493)

JSON validado no processo 0000386 (saiu da fila):

```json
{
  "tipo": "vistas_mp",
  "fluxo": "analisar",
  "fluxo_fallback": false,
  "codigo_mov": "493",
  "observacao": "Vistas ao Ministério Público",
  "cod_nucleo_mp": "31",
  "tipo_parecer_mp": "6",
  "prazo_mp": "5",
  "promotor_mp": "SOSTENYS MARINHO BARRETO"
}
```

- `codigo_mov` = **493** (NÃO usa tipo documental — só observação; tratado junto
  de `11383` no branch sem grid do `executar_requests`). NÃO informar
  `descricao_mov` nem `tipo_documento`.
- **Ordem de preenchimento no formulário** (importante — dependências):
  1. `codNucleoMP` = 31 (Paulo Afonso) → dispara DWR que popula o promotor
  2. `codTipoEnvioMP` = tipo de parecer (6 = Ciência, o mais usado)
  3. `codPrazoEnviaMP` = prazo (5 = 30 dias padrão)
  4. `loginPromotorNucleoMP` = promotor por NOME (procurar por "contém")
- Após escolher o núcleo, **aguardar ~0.8s** para o DWR popular a lista de promotores.

### Dicionário `codTipoEnvioMP` (tipo de parecer)
| valor | texto |
|---|---|
| 0 | Parecer genérico |
| 4 | Denúncia |
| 5 | Desistência |
| **6** | **Ciência (mais usado — default)** |
| 7 | Alegações Finais / Memoriais |
| 8 | Parte não Localizada |
| 9 | Prescrição |
| 10 | Decadência |
| 11 | Recurso/Contrarrazões |
| 12 | Acordo Cível |
| 13 | Medida Cautelar |
| 14 | Proposta de Transação Penal |
| 15 | Transação Penal Cumprida |
| 16 | Transação Penal Aceita |

### Dicionário `codPrazoEnviaMP` (prazo)
| valor | dias |
|---|---|
| 10 | 1 dia |
| 1 | 2 dias |
| 11 | 3 dias |
| 47 | 4 dias |
| 2 | 5 dias |
| 3 | 10 dias |
| 4 | 15 dias |
| **5** | **30 dias (padrão)** |

---

## 3. Intimação pelos Correios / AR digital (passo `intimacao_correio`)

```json
{
  "tipo": "intimacao_correio",
  "fluxo": "movimentar",
  "codigo_mov": "581",
  "descricao_mov": "Intimação",
  "observacao": "Intimem-se as partes pelos Correios (AR digital)",
  "motivo_intimacao": "3",
  "prazo_intimacao": "3",
  "tipo_intimacao": "geral",
  "natureza": "criminal",
  "codigo_tipo_ar": null,
  "assinar_ar": true
}
```

**Fluxo (método `executar_com_intimacao_ar`):**
1. Mov581 + painel Autoras/Rés + motivo/prazo + Concluir (como a eletrônica).
2. **2º clique**: navega `MovimentarProcessoAvancado` (link genérico) → select
   `name="tipo"` (COJE) → clica **"expedir com ar digital"** → página
   `ExpedirIntimacao?origem=...&codIntimacao=...&tipo=...&gerarar=true&arDigital=true`.
3. **Assinatura**: `_assinar_expedicao_ar()` — senha automática via
   `User.projudi_password` (admin seção Projudi); manual se vazio.
   Diálogo em iframe `popupFrame` (`/acoes/UploadDocumento`): `#senha` +
   botão assinar SÓ aparecem após o 1º clique.

**Modelos COJE AR** (select `name="tipo"`):
| natureza | geral | audiência |
|---|---|---|
| Cível | 12066 | 56061 |
| Criminal | 14032 | 55794 |

- `codigo_tipo_ar` força um código direto (ignora a tabela).
- `assinar_ar: false` = expede mas NÃO assina (modo teste); o registro fica
  `'pendente'` em vez de `'cumprido'`.

---

## 4. Intimação eletrônica (passo `intimacao_eletronica`) + fallback de mandado

```json
{
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar",
  "fluxo_fallback": true,
  "codigo_mov": "581",
  "descricao_mov": "Intimação",
  "observacao": "Intimem-se as partes para ciência da Decisão",
  "motivo_intimacao": "3",
  "prazo_intimacao": "3",
  "fallback": "mandado",
  "fallback_template_id": 8,
  "fallback_subtipo": "11",
  "fallback_prazo": "15",
  "fallback_polo": "reu_especifico",
  "mandado_explicito": false
}
```

**3 camadas de fallback (não confundir):**
1. **Fluxo da página** (`fluxo` + `fluxo_fallback`) — ver seção 1.
2. **Canal da parte** (`fallback: "mandado"`, `fallback_uf`, `fallback_polo`) —
   quando a parte NÃO tem DJEN (canal cai para mandado/AR-falho). `fallback_uf`
   restringe a UF; `fallback_polo` define o destinatário.
3. **O que fazer no fallback** — `fallback_template_id` presente → **expede o
   mandado COMPLETO** (tipoCumprimento=4 + subtipo + destinatário +
   CumprimentoCartorio → "Redigir sem AR" → FCKeditor → Registrar).
   Sem template → só Mov581 com `fallback_mov`. `mandado_explicito: true` →
   sequência já tem passo de mandado, não duplica.

**Fallback de AR** (`fallback_ar: true`) — 2026-08-06:
No passo `intimacao_eletronica`, quando a última comunicação da parte é **AR**
(não tem domicílio eletrônico), o default é **PULAR** ("fazer manualmente").
Adicionar `"fallback_ar": true` faz o fluxo, em vez de pular, **expedir pelos
CORREIOS com AR digital** (2º clique, como o passo `intimacao_correio`). Juntar
com `"assinar_ar": false` para deixar a página aberta (assinatura manual):

```json
{
  "tipo": "intimacao_eletronica",
  "fluxo": "analisar",
  "fluxo_fallback": true,
  "codigo_mov": "581",
  "descricao_mov": "Intimação",
  "observacao": "Intime-se a parte autora, através de sua defesa, para apresentar manifestação sobre a proposta de pagamento do débito",
  "motivo_intimacao": "3",
  "prazo_intimacao": "2",
  "polo": "res",
  "fallback_ar": true,
  "assinar_ar": false
}
```
- Parte com domicílio eletrônico continua intimando por DJEN
  (fallback_ar não altera esse caso).
- ⚠️ Se `expedir_ar` já vem como true no passo, o fallback_ar é irrelevante
  (o fluxo AR já está ativo).

**Controle de AR não assinado (dashboard)** — 2026-08-06:
Quando o AR é expedido mas a assinatura não é concluída (`assinar_ar: false`
ou falha na assinatura), o `CumprimentoRecord` é criado com
`status='pendente'` e `fluxo='ar'` (justificativa: "AR expedido mas
AGUARDANDO assinatura"). Esses registros aparecem:
1. **Dashboard principal** (`/`): painel "✍️ Intimações Expedidas —
   Aguardando Assinatura (AR)" com cards de cada processo + seção
   "📋 Cumprimentos Recentes" (últimos 10).
2. **Dashboard de Cumprimentos** (`/projudi/cumprimentos/`): contados em
   "Pendentes" e listados com filtro `?status=pendente`.
Filtro usado na view: `CumprimentoRecord.objects.filter(status='pendente',
fluxo='ar')`. Todas as não assinadas no automático ficam nessa lista até a
assinatura ser concluída manualmente no Projudi.

**ComunicacaoTracker ANTES do FluxoDecisor (evitar duplicidade)** — 2026-08-06:
No caminho do dashboard (`cumprimento_service.buscar_cumprimentos_pendentes`),
antes de decidir o canal com o `FluxoDecisor`, roda um **pré-check com o
`ComunicacaoTracker`**: se NENHUMA parte tem domicílio eletrônico (DJEN),
consulta o histórico de comunicações e, se o ato já foi comunicado à parte
(expedida/lida/pendente), **NÃO duplica** — cria um `CumprimentoRecord` com
`status='dispensado'` e justificativa "Comunicação já realizada". Partes com
DJEN (intimação eletrônica) pular o pré-check e seguem direto.
- Métodos novos: `_extrair_movimentacoes_tracker()` (lê Movement ou baixa
  DadosProcesso) e `_precheck_tracker()`.
- Novos campos da decisão: `tipo='ja_comunicado'`.

**⚠️ VISÃO FUTURA (proposta, NÃO implementada):** o ComunicacaoTracker deve
ser usado também para **fiscalizar prazos e cumprimentos de comunicações** e
para **fornecer contexto de eventos passados ao cumprir o evento atual** —
usar o emparelhamento expedida→lida (`_expedidas`/`_lidas`/`_pendentes` com
`data_obj`) para (a) calcular se o prazo foi respeitado e alertar comunicações
vencidas sem retorno, e (b) alimentar despachos que remetem a atos anteriores
(RAG contextual via `referenced_event_obj`, pegando o evento que originou
prazo/meio/quem já foi intimado). Proposta completa no docstring do
`projudi/comunicacao_tracker.py`.

**Matching RAG — alinhar CLI e dashboard (evitar falsos positivos)** — 2026-08-06:
Sintoma: despachos eram executados com RAG errada (ex.: a RAG de "intimar a
parte de uma ordem sobre pedido liminar" pegou um despacho de "intimem-se as
partes promovidas para ciência dos documentos"). CAUSA: o caminho do DASHBOARD
(`cumprimento_service._melhor_match`) usava `normalizar_texto` CRU (sem remover
stopwords/pontuação) e threshold sobre o TAMANHO da RAG — despachos casavam por
palavras genéricas do cabeçalho. O CLI (`expedir_rapido`) já usava o método limpo.
CORREÇÃO: `_melhor_match` agora usa o MESMO `_palavras_para_match` (remove
stopwords/pontuação) e o MESMO threshold (≥70% do MENOR texto) do CLI. As duas
caminhos ficaram consistentes. Se aparecer falso positivo de novo, checar se os
dois caminhos usam critérios iguais.

---

## 5. Matching RAG (como o sistema decide qual RAG executar)

- **NÃO casa por número do processo** — casa por **similaridade de palavras**
  (`despacho_ato` + `despacho_observacao` vs texto real da movimentação).
- RAGs de template ficam vinculadas ao processo fictício `9999999-99...`
  (âncora). O `--processo` procura por FK primeiro; **fallback por similaridade**
  quando não há FK.
- **NÃO limitar a 200 RAGs** (`[:200]` fazia RAGs recém-criadas sumirem) —
  pegar TODAS as ativas. `top_k` = 30+ (5 era baixo demais; a RAG certa ficava
  de fora).
- Threshold **≥70%** (intersecção / menor texto) aplicado NO CHAMADOR, não na busca.
- **Atenção aos CNJs parecidos:** `0000386` ≠ `0003861` ≠ `0003896`.

---

## 6. Dicionários úteis (referência rápida)

### Tipos de mandado (`subtipo` / `fallback_subtipo`)
1=Citação+Aud, 2=Aud, 3=Intimação, 4=Citação, 5=Despacho, 6=Sentença,
7=Busca e Apreensão, 8=Liminar, 9=Genérico, 10=Alvará, 11=Citação/Penhora/Avaliação
(DEFAULT), 12=Ofício, 24=Notificação, 26=Penhora, 27=Reintegração.

### Localizadores (`tipo_localizador`)
22614=SISBAJUD, 11916=RENAJUD, 24012=SERASAJUD, 22644=SNIPER,
9376=PESQUISA DE ENDEREÇO, 9205=AGUARDAR CUMPRIR TRANSAÇÃO,
30586=AGUARDAR DISTRIBUIÇÃO, 14396=AGUARDAR RETORNO DE AR,
15286=AGUARDAR DECURSO DO PRAZO, 10248=CERTIFICAÇÃO TRÂNSITO EM JULGADO,
5624=SEM LOCALIZADOR.

### Prazos do painel (`prazo_intimacao`)
2=05d, 3=10d (DEFAULT), 4=15d, 7=30d, 29=6m. Motivo: 3=conhecimento/ciência.

### Templates (`template_id`)
8=Mandado Citação/Intimação/Penhora/Avaliação, 6=Mandado Intimação TP,
2=Mandado genérico, 5=Ofício CIAP, 7=Ofício RPV, 9=Certidão (1 autor),
10=Certidão (vários autores).

### Polos destinatário (`polo` / `fallback_polo`)
`reu_especifico` (DEFAULT — histórico, senão todos réus), `autor_especifico`,
`autores`, `res`, `todos`, lista `["autor_especifico","reu_especifico"]`.
**NUNCA nome de parte solto no JSON** — nome vem do banco/processo.

### Nome da parte na observação (`parte_na_observacao`)
false (DEFAULT, sem nome), true (1º nome), 'todas'/'all' (todos os nomes).

---

## 7. AR falho no histórico (FluxoDecisor)

- `projudiProcessNavigator.analisar_movimentacao()` marca
  `situacao_comunicacao='ar_falho'` quando AR negativo/devolvido/não
  localizado/mudou-se/recusado (mantendo `meio_comunicacao='ar'`).
- FluxoDecisor usa o histórico de comunicações do banco (`Movement`):
  AR falho no histórico → **mandado (BA)** / **precatória (outro estado)**.
- Ordem de decisão: JSON força mandado → adv/DJEN/email = eletrônico →
  AR falho → AR → rural/sem AR = mandado.

---

## 8. Backup e espelhamento do banco

- Banco: **PostgreSQL 16** no container Docker `pg_send_of` (porta 5433),
  banco `sccj`, usuário `send_of` (credenciais no `.env` → `DATABASE_URL`).
- Dump: `docker exec pg_send_of pg_dump -U send_of -d sccj --no-owner --no-privileges`
  (~1.2 MB compacto; banco ~24 MB).
- Script: `scripts/backup_db.sh` — ver abaixo.

---

## 9. Tipo documental da intimação + re-execução de processos não-pendentes (2026-08-05)

### Selecionar o tipo documental "Intimação" de forma confiável
O alerta "escolha um tipo de documento" no Projudi aparece quando a grade
de tipo documental fica **sem seleção** antes do Concluir. O jeito **que
funciona** (validado ao vivo) é o MESMO do `executar_requests` (Certidão=37,
CUMPRIMENTO=55): pelo `<select name="codTipoDocumento">`, casando pelo
**LABEL** e confirmando o valor.

```python
# projudi/movimentacao_service.py — executar_com_intimacao(), PASSO 3
sel_tp = page.wait_for_selector('select[name="codTipoDocumento"]', timeout=8000)
candidatos = []
for opt in sel_tp.query_selector_all('option'):
    v = (opt.get_attribute('value') or '').strip()
    t = (opt.inner_text() or '').strip()
    tl = t.lower()
    if v and 'intima' in tl and 'videoconf' not in tl and 'telef' not in tl:
        candidatos.append((len(t), v, t))      # label mais curto primeiro
candidatos.sort()
sel_tp.select_option(candidatos[0][1])          # Intimação -> valor 5
```

**PITFALL que custou uma rodada inteira:** clicar em `a:has-text("Intimação")`
**NÃO seleciona nada** — casa com um link de menu/página e o log imprime
`✅ Tipo doc` (falso positivo), mas o grid continua sem seleção e o alerta
"escolha um tipo de documento" aparece no Concluir. **Não usar clique em
link; usar o select por label.** Também ajuda desocultar a linha
`#trTipoDocumento` (`tr.style.display='table-row'`) antes de esperar o select.

### Re-executar processos que NÃO estão mais pendentes na fila
`expedir_processo_especifico(cnj)` só encontrou RAG quando há pendência.
Processos já executados não aparecem na fila → fallback de similaridade/
varredura não acha nada. Para os re-processar com FK:

1. `expedir_rapido.vincular_rag_7.py` — cria `Process` (tenant=1) e um
   `RAGExample` (cópia do RAG-modelo `9999999-99…`, que é o `RAGExample` com
   a sequência `intimacao_eletronica` pra "cumprimento de sentença 15d",
   `prazo_intimacao=4`, `descricao_mov="Intimação"`, `polo=res`).
2. Como a RAG tem FK única p/ processo (1→1), cria-se **uma cópia por CNJ**.
3. O `proc_projudi` (número interno) só vem do `link_processo` da varredura.
   Como eles não são pendentes, set `Process.projudi_url =
   '...DadosProcesso?numeroProcesso=<numero_interno>'` — o dispatcher extrai
   o interno disso e roda no Fluxo B (MovimentarProcesso).

### Records de desfecho
`executar_com_intimacao` grava agora um `CumprimentoLog`
com o desfecho + erro (`sucesso`/`_erro_mov`). Antes os records dessa função
nasciam SEM log nenhum, e era impossível fiscalizar o motivo da falha.

### ⚠️ AR em intimação eletrônica
`expedir_ar=true` numa seq de intimação **eletrônica** (parte com domicílio
CNJ) quebra na etapa de expedição pelos Correios ("Não achei o select
name=tipo" com link de AR) → lança `falha` **mesmo a intimação tendo concluído**.
Se a intimação é eletrônica, use `expedir_ar=false` pra registrar como
`cumprido`.
