# APRENDIZADOS — RAGs Catch-all + Observação Dinâmica com Eventos (2026-08-18)

## Contexto

Criamos RAGs genéricas ("catch-all") para aglutinar variações de **liminar**
(concedida / não concedida) e de **despachos que intimam a parte autora a juntar
petição/documentos citando **eventos** numéricos do processo.

Também implementamos a **injeção dinâmica de placeholders** na observação da
movimentação (campo `observacao` da `sequencia_cumprimento`), para que os números
de evento citados no despacho real preencham o texto automaticamente.

---

## 1. RAGs Catch-all de Liminar (criadas 2026-08-18)

| RAG ID | Nome | Fallback | Uso |
|--------|------|----------|-----|
| **2529** | Liminar Concedida | `fallback: mandado` | Concedida → expede mandado na mesma mov |
| **2531** | Liminar Concedida | `fallback: solicitar_expedicao` | Concedida → só pede expedição (Mov 581) |
| **2530** | Liminar Não Concedida | `fallback: mandado` | Não concedida → intimação + mandado/AR fallback |

**Catch-all** = a RAG NÃO é amarrada a uma milésima variação de texto. O
`despacho_observacao` combina palavras-chave de todas as RAGs do grupo para ter
interseção máxima de tokens no matching (`_palavras_para_match`).

### Posição dos polos (intimação eletrônica vs. fallback AR/mandado)

Regra de negócio usada na RAG 2534 (desarquivamento) e recomendada como padrão:

- **Intimação eletrônica (DJEN)** → `polo: todos` (autor + réus, todos os
  domiciliados eletronicamente).
- **Fallback AR ou mandado** → `fallback_polo: autor_especifico` (foca em quem
  solicitou — na maioria dos casos o autor). Se raramente o réu pede,
  `fallback_polo: ['autor_especifico', 'res']`.

```
CAMPO PRINCIPAL x CAMPO DE FALLBACK NÃO SE CONFUNDEM:
  polo           → quem é intimado na intimação ELETRÔNICA (DJEN)
  fallback_polo  → quem é intimado quando o canal cai para AR/mandado
```

Ver vocabulário de `fallback_polo`: `todos`, `autores`/`autoras`,
`autor_especifico`, `res`, `reu_especifico`, ou lista `[...]`.

### Fallback AR + Solicitação de mandado (RAG 2534)

- `fallback_ar: true` → última comunicação foi AR → **expede pelos Correios com
  AR digital** (em vez de pular). Combina com `assinar_ar`.
- `fallback: solicitar_expedicao` + `solicitar_mandado: true` → próxima etapa do
  fluxo pede a expedição de mandado via Mov 581.
- `fallback_ar` trata da **comunicação anterior** (por AR); `fallback` trata do
  **próximo passo da sequência**. São independentes e podem coexistir.
- `assinar_ar: true` = assina automático; `assinar_ar: false` = deixa a página do
  AR aberta para assinatura manual (cards "Aguardando Assinatura").

---

## 2. RAG de DESPACHO com Eventos (RAG 2533)

Pegamos um despacho real que intima o autor a juntar petição referenciando
evento(s) e o tornamos genérico:

```
DESPACHO¹

Intime-se a parte autora, através de sua defesa, para juntar a petição mencionada
no evento [NÚMERO_SOLTO], bem como, os respectivos documentos em formato pdf, no
prazo legal de 5 dias, sob pena de indeferimento do pleito.

Dê-se ciência à parte contrária acerca do informado nos eventos indicados nos autos
```

- `despacho_ato`: `DESPACHO¹`
- `despacho_observacao`: contém `evento` (palavra genérica, sem número)
- `sequencia_cumprimento[0]`:
  - `polo: todos`
  - `tipo: intimacao_eletronica`
  - `fallback: mandado`
  - `observacao`: texto com **placeholders** (ver seção 3)

**Matching** é robusto porque os tokens estruturais (`evento`, `eventos`, `retro`,
`intime`, `autora`, `juntar`, `peticao`, `prazo`, `documentos`, `indeferimento`)
não dependem do número do evento. Testado: jaccard 0.97 no texto do usuário;
reconhece evento 94, 120, 25, retro, indicados — todos.

---

## 3. Placeholders Dinâmicos de Evento na Observação

Implementado em `projudi/rag_router.py`.

### Função `_extrair_eventos(texto)` → list[str]

Extrai os números de evento citados no despacho, na ordem de aparecimento:

```python
_extrair_eventos('...evento 94... eventos 25 e 26')  # → ['94', '25', '26']
```

Regex: `evento\s*([^.\n;,]{0,40})` e depois pega todos os `\d+` do trecho.
Remove duplicados preservando ordem.

### Função `_preencher_eventos_observacao(obs, texto, sequencia=None)` → str

Substitui os placeholders na observação pelo texto real. Funciona com múltiplos
eventos (ordena: 1º para autora, demais para réus).

### Function `_substituir_polo_placeholder(obs, polo)` → str

Substitui `{{autor}}`/`{{reu}}` baseado no campo `polo` da sequência.

### Placeholders suportados

| Placeholder | Vira (exemplo) |
|-------------|----------------|
| `{{evento}}` | 1º evento (ex `94`) |
| `{{eventos}}` | todos separados por ` e ` (ex `25 e 26`) |
| `{{evento_autora}}` | igual a `{{evento}}` (1º) |
| `{{eventos_reus}}` | todos exceto o 1º (ex `25 e 26`) |
| `{{autor}}` | texto do polo (ex `a parte autora` / `as partes`) |
| `{{reu}}` | idem |

### Exemplos de resultado

| Texto do despacho | Observação gerada |
|-------------------|-------------------|
| `...evento 94` | `Intime-se a parte autora para ciência do evento 94. Intime-se a(s) parte(s) ré(s) para ciência dos eventos indicados nos autos` |
| `...evento 94 ... eventos 25 e 26` | `Intime-se a parte autora para ciência do evento 94. Intime-se a(s) parte(s) ré(s) para ciência dos eventos indicados nos autos 25 e 26` |
| sem número de evento | remove placeholders, mantém texto limpo |

### Template da observação (RAG 2533)

```
"Intime-se a parte autora para ciência do evento {{evento_autora}}. " +
"Intime-se a(s) parte(s) ré(s) para ciência dos eventos indicados nos autos {{eventos_reus}}"
```

### Onde é aplicado

No `rag_router._executar_sequencia`, a observação de cada passo é preenchida
antes de ser usada:

```python
obs = _observacao_com_eventos(passo, texto)
```

`_observacao_com_eventos` chama `_preencher_eventos_observacao` (eventos) e
`_substituir_polo_placeholder` (polo), nessa ordem.

> ⚠️ IMPORTANTE: os placeholders preenchem a **observação** (`observacao`) que
> vai para o campo observação da movimentação do Mov581. **NÃO** preenchem o
> `despacho_observacao` (corpo do despacho HTML) — isso já era feito pelo
> matching/parser de HTML do Projudi no fluxo normal.

---

## 4. RAG 2534 — Desarquivamento / Gratuidade de Justiça

Despacho que intima a parte solicitante a comprovar estado de pobreza
(gratuidade) no prazo de 5 dias (art. 5º, LXXIV da CF).

Configuração final:
- `polo: todos` (intimação eletrônica abrange todos)
- `fallback_polo: autor_especifico` (AR/mandado foca no autor/cliente da gratuidade)
- `fallback_ar: true`, `assinar_ar: true`
- `fallback: solicitar_expedicao`, `solicitar_mandado: true`
- `prazo_intimacao: 5`, `motivo_intimacao: 3`

Observação:
```
"Intimação da parte solicitante para comprovar estado de pobreza (gratuidade
da justiça), no prazo de 05 dias, sob pena de indeferimento do pedido de
assistência judiciária gratuita."
```

---

## 5. Pitfalls / Lições

1. **`polo` ≠ `fallback_polo`** — não confundir; o 1º é a intimação eletrônica
   (DJEN), o 2º é quando o canal cai para AR/mandado.
2. **`fallback_ar` trata a comunicação anterior; `fallback` o próximo passo** —
   independentes, podem coexistir.
3. **Placeholder vazio** — se o despacho não tiver número de evento, os
   placeholders são removidos para não deixar `evento .`/`evento e`. A limpeza
   precisa remover o espaço que precede o placeholder (`{{x}} ` → '').
4. **Placeholders só valem para `observacao`** da sequência; não mexem no
   `despacho_observacao` (HTML).
5. **Matching não depende do número** — manter `evento` sem número no
   `despacho_observacao` torna a RAG genérica (capta 94, 120, retro, etc.).
