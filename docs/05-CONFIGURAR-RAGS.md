# Configurar RAGs — Guia da `sequencia_cumprimento`

> Data: 2026-07-31 — cobre os tipos de passo, códigos e regras de comportamento.

## 1. Onde configurar

RAGExample no Admin → campo **sequencia_cumprimento** (JSON, lista de passos).

Regra de ouro:

| Sequência | Comportamento |
|---|---|
| **Preenchida** | Executa SÓ os passos da lista (pula CommandAnalyzer/FluxoDecisor/expedição) |
| **Vazia** (`[]`) | Fluxo dinâmico completo: CommandAnalyzer → ParteClassifier → FluxoDecisor → expedição |

> ⚠️ Se o RAG não deve expedir documento completo (ex: só solicitar mandado), SEMPRE dê uma sequência explícita. Sequência vazia cai no fluxo dinâmico.

## 2. Campos comuns a todos os passos

| Campo | Obrigatório | Default | Descrição |
|---|---|---|---|
| `tipo` | sim | — | Tipo do passo (ver tabela abaixo) |
| `codigo_mov` | não | `"581"` | Código da movimentação (581 = grid+TD; 11383 = direto, sem grid) |
| `descricao_mov` | não | varia | Descrição da movimentação no Projudi |
| `observacao` | não | — | Texto da observação (vai no campo `#observacao`) |
| `localizador` | não | — | Código do localizador específico (`codLocalizador`) |
| `tipo_localizador` | não | — | Código do tipo de localizador (`codTipoLocalizador`) |

## 3. Tipos de passo

| `tipo` | O que faz | Parâmetros específicos |
|---|---|---|
| `"movimentacao"` | Mov581 genérico (descrição "Cumprimento de Decisão") | — |
| `"solicitar_expedicao"` | Mov581 "Solicitada a Expedição de Mandado" — **sem confecção**. Identifica a parte (réu → específico no histórico → todos → ata) e põe o nome na observação | — |
| `"localizar"` | Só altera o localizador (Mov581 + tipo_localizador) | `tipo_localizador` (obrigatório), `tipo_documento` |
| `"vistas_mp"` | Vistas ao MP (Mov581 + enviaMP) | `tipo_localizador`, `cod_nucleo_mp` (default 31=PA), `tipo_documento` |
| `"certidao_criminal"` | Certidão criminal art. 76 — **ADIADA** (flag `CERTIDAO_CRIMINAL_ADIADA=True` no expedir_rapido.py) | — |
| `"intimacao_eletronica"` | Mov581 + intimação via DJEN (painel Autoras/Rés) | `fallback`, `prazo_intimacao`, `tipo_localizador`, `cod_analise` |
| `"mandado"` | Mov581 + **confecção completa** do mandado via Playwright | `template_id` (obrigatório), `subtipo`, `polo`, `prazo` |
| `"oficio"` | Mov581 + confecção do ofício | `template_id` (obrigatório) |
| `"buscar_processo"` | Só busca processo por nome da parte (sem movimentar) | `nomes` |

## 4. Passo `intimacao_eletronica` — detalhes

```json
{
  "tipo": "intimacao_eletronica",
  "codigo_mov": "581",
  "descricao_mov": "Intimação",
  "observacao": "Intimem-se as partes para ciência",
  "fallback": "mandado",
  "prazo_intimacao": "2",
  "tipo_localizador": "22614"
}
```

### Pre-check do canal (automático, pelo histórico de comunicações)

Antes de abrir o navegador, o sistema olha a **última intimação** do processo
(`meio_comunicacao` do `extrair_movimentacoes`):

| Última intimação | Ação |
|---|---|
| `domicilio_cnj` (DJEN/advgs.) | segue com intimação eletrônica |
| `ar` | PULA (fazer manual) |
| `mandado` / `precatoria` + `"fallback": "mandado"` | registra solicitação de expedição (sem expedir) |
| `mandado` / `precatoria` sem fallback | PULA (fazer manual) |
| `mandado` / `precatoria` + passo explícito de mandado/solicitação na sequência | PULA a intimação (sem solicitação duplicada — `mandado_explicito`) |

### Códigos de prazo do painel (`prazo_intimacao`)

| value | Prazo |
|---|---|
| `2` | 05 dias |
| `3` | 10 dias (default) |
| `4` | 15 dias |
| `7` | 30 dias |
| `29` | 6 meses |

> O default `'3'` (10 dias) vale para sentenças. Despachos com outro prazo: informar o value no JSON (ex: retorno dos autos = `"2"`).

### Fluxo da página (`fluxo_processo`)

Por padrão o passo usa o link de **MovimentarAnalise** (`codAnalise`, Fluxo A — com painel de intimação Autoras/Rés). Para forçar o link genérico **MovimentarProcesso** (Fluxo B — sem painel, usa o link "Intimar" do DadosProcesso), adicionar `"fluxo_processo": true` no passo.

### Polo do fallback (`fallback_polo`)

O fallback de mandado (canal mandado → solicitação) identifica a parte com o vocabulário do mandado. Default: `reu_especifico` (só réus). Para mudar:

```json
{
  "tipo": "intimacao_eletronica",
  "fallback": "mandado",
  "fallback_polo": ["autor_especifico", "reu_especifico"]
}
```

Valores: `reu_especifico` (padrão) | `autor_especifico` | `autores` | `res` | `todos` | lista. Vários nomes → todos selecionados como destinatário.

## 5. Passo `mandado` — detalhes

```json
{
  "tipo": "mandado",
  "template_id": 8,
  "subtipo": "3",
  "polo": "reu_especifico",
  "prazo": "05",
  "observacao": "Solicitada Expedicao de Mandado"
}
```

### `template_id` (modelos ativos)

| ID | Modelo |
|---|---|
| 8 | Mandado de Citação, Intimação, Penhora e Avaliação |
| 6 | Mandado de Intimação (Transação Penal) |
| 2 | Mandado (genérico) |

### `subtipo` — natureza do mandado (`subtipoCumprimento`, após tipoCumprimento=4)

| Código | Subtipo |
|---|---|
| 1 | Citação e Intimação para Audiência |
| 2 | Intimação para Audiência |
| 3 | Intimação |
| 4 | Citação |
| 5 | Intimação Despacho |
| 6 | Intimação de Sentença |
| 7 | Busca e Apreensão |
| 8 | Citação e/ou Intimação com Liminar |
| 9 | Mandado genérico |
| 10 | Alvará de soltura |
| 11 | Citação/Penhora/Avaliação/Intimação/Depósito (default do código) |
| 12 | Ofício |
| 24 | Notificação |
| 26 | Penhora e/ou avaliação |
| 27 | Reintegração de Posse |
| 34 | Prisão |

### `polo` — para quem (NUNCA nome de parte; string OU lista)

| valor | Comportamento |
|---|---|
| `"reu_especifico"` (padrão) | busca a parte exata entre os réus (histórico de comunicações); não achou → TODOS os réus |
| `"autor_especifico"` | idem entre as autoras; não achou → TODAS as autoras |
| `"autores"` | todas as autoras |
| `"res"` | todos os réus |
| `"todos"` | todas as partes |
| lista (ex: `["autor_especifico", "reu_especifico"]`) | os DOIS polos — cada um com sua própria busca específica; sem duplicatas |

> A busca usa o destinatário das intimações passadas ("p/ FULANO") via `_buscar_parte_especifica()`.

### `prazo` — dias do documento

Hierarquia: `"prazo"` no JSON → extrai da movimentação ("prazo de N dias") → vazio
(o template usa o próprio default, ex: `{{ prazo_dias |default:"15" }}` no modelo #8).

## 6. Passo `solicitar_expedicao` — detalhes

```json
{
  "tipo": "solicitar_expedicao",
  "codigo_mov": "581",
  "observacao": "Solicitada Expedicao de Mandado",
  "descricao_mov": "Solicitada a Expedição de Mandado"
}
```

- Só Mov581 — **sem confecção** (não abre FCKeditor, não registra documento).
- **Ignora canal** (AR/eletrônica): sempre solicita.
- Identificação da parte: aceita `polo` igual ao passo mandado (`reu_especifico` padrão, `autor_especifico`, `autores`, `res`, `todos`, ou lista ex: `["autor_especifico","reu_especifico"]`). Vários nomes são juntados com " / " e TODOS são selecionados no campo destinatário antes do Concluir (multi-seleção).
- Nome da parte vai na observação e no `parte_nome` do registro.
- **Obrigatório no Playwright**: Tipo Documento = 51 (Mandado) + tipoCumprimento=4 + subtipo=3 + destinatário, tudo ANTES do `btnAddCumprimento`. Sem isso o Projudi valida "tipo de documento obrigatório" e "prazo para Autor/Testemunha obrigatório" (implementado no `MovimentacaoService.executar()` quando `act_verb == 'solicitar_expedicao'`).
- Validado 2026-07-31: processo 0001781-80.2025.8.05.0191 → "Solicitada a Expedição de Mandado de Intimação p/ CAIXA DE ASSISTENCIA DOS FUNCIONARIOS DO BANCO DO BRASIL" registrado no Projudi.

## 7. Passo `localizar` — detalhes

```json
{
  "tipo": "localizar",
  "codigo_mov": "581",
  "tipo_documento": "CUMPRIMENTO",
  "tipo_localizador": "9376",
  "observacao": "Ao Localizador de Pesquisa de Endereco"
}
```

- `tipo_documento`: label do select `codTipoDocumento` — default **"CUMPRIMENTO"** (genérico). O label "PESQUISA DE ENDEREÇO SISBAJUD ORDENADA" **NÃO existe** no select.
- Pre-check: se o localizador já está definido no processo, pula como cumprido.

## 8. Códigos de localizador (`tipo_localizador`)

| Código | Localizador |
|---|---|
| `9376` | Pesquisa de Endereço |
| `22614` | SISBAJUD |
| `9205` | Aguardar Cumprir Transação |
| `30586` | Aguardar Distribuição |
| `15286` | Aguardar Decurso do Prazo |
| `14396` | Aguardar retorno de AR |
| `11916` | RENAJUD |
| `24012` | SERASAJUD |
| `22644` | SNIPER |
| `10248` | Certificação Trânsito em Julgado |

## 9. Código da movimentação: 581 vs 11383

| Código | Descrição padrão | Pipeline | Quando usar |
|---|---|---|---|
| `581` | TD - Tipo Documental | Playwright (grid + btnAddCumprimento + Concluir) | Movimentação que precisa de grid de documentos (localizar, vistas_mp, mandado, ofício) |
| `11383` | Cumprimento de Oficio | requests direto (POST multipart com Concluir.x/y) | Movimentação simples (solicitar_expedicao, movimentacao) |

> ⚠️ **11383 NÃO funciona para `localizar`** — precisa do Tipo Documento (codTipoDocumento) que só é populado via grid com 581.

## 10. Outros códigos úteis

### Núcleo MP (`cod_nucleo_mp` no passo vistas_mp)
| Código | Núcleo |
|---|---|
| `31` | Paulo Afonso |
| `1` | Turmas Recursais |

### Descrição de documento (`codDescricao1` — inserção de certidão)
| Código | Tipo |
|---|---|
| `37` | Certidão |
| `1006` | Ato Ordinatório |
| `2` | Citação |
| `5` | Intimação |

## 11. Exemplos de sequência prontos

### Só intimação eletrônica (liminar não concedida)
```json
[
  {"tipo": "intimacao_eletronica", "codigo_mov": "581", "descricao_mov": "Intimação",
   "observacao": "Intimem-se as partes para ciência da Decisão (NÃO CONCEDIDA A MEDIDA LIMINAR)",
   "fallback": "mandado"}
]
```

### Intimação + solicitação de mandado (liminar concedida)
```json
[
  {"tipo": "intimacao_eletronica", "codigo_mov": "581", "descricao_mov": "Intimação",
   "observacao": "Intimem-se as partes para ciência da Decisão (CONCEDIDA A MEDIDA LIMINAR)"},
  {"tipo": "solicitar_expedicao", "codigo_mov": "581",
   "observacao": "Solicitada Expedicao de Mandado",
   "descricao_mov": "Solicitada a Expedição de Mandado"}
]
```

### Intimação com prazo de 05 dias (retorno dos autos)
```json
[
  {"tipo": "intimacao_eletronica", "codigo_mov": "581", "descricao_mov": "Intimação",
   "observacao": "Intimem-se as partes para manifestarem-se do retorno dos autos, no prazo de 05 (cinco) dias...",
   "fallback": "mandado", "prazo_intimacao": "2"}
]
```

### Mandado completo — réu específico, citação/penhora, prazo 15
```json
[
  {"tipo": "mandado", "template_id": 8, "subtipo": "11", "polo": "reu_especifico", "prazo": "15"}
]
```

### Só solicitar expedição (não cai no fluxo de expedir)
```json
[
  {"tipo": "solicitar_expedicao", "codigo_mov": "581",
   "observacao": "Solicitada Expedicao de Mandado - Intimação para Comprovar Cumprimento de TP",
   "descricao_mov": "Solicitada a Expedição de Mandado"}
]
```

### Alterar localizador (pesquisa de endereço)
```json
[
  {"tipo": "localizar", "tipo_documento": "CUMPRIMENTO", "tipo_localizador": "9376",
   "observacao": "Ao Localizador de Pesquisa de Endereco"}
]
```

## 12. Regras de comportamento gerais

1. **Sequência preenchida** → fluxo dinâmico NÃO roda (nem expedição completa).
2. **Certidão criminal** está ADIADA — flag `CERTIDAO_CRIMINAL_ADIADA = True` no `expedir_rapido.py` (pula com "⏸️"). Fluxo pronto atrás da flag (autores/vítima extraídos da ata, nunca do JSON).
3. **Pre-check de canal** só age dentro do passo `intimacao_eletronica` — não bloqueia passos seguintes.
4. **Anti-duplicação**: se a sequência tem passo `solicitar_expedicao`/`mandado` explícito, o pre-check da intimação não registra solicitação (flag `mandado_explicito`).
5. **Prazo do documento** (mandado/ofício): JSON → movimentação → default do template.
6. **`input()` no dashboard**: nunca bloqueia (só espera Enter em terminal interativo — `sys.stdout.isatty()`).

## 13. Arquivos envolvidos

| Arquivo | O que tem |
|---|---|
| `expedir_rapido.py` | `_executar_sequencia_rapido()` — executa a sequência; `_buscar_parte_especifica()`; `_extrair_dados_ata()`; flag `CERTIDAO_CRIMINAL_ADIADA` |
| `projudi/movimentacao_service.py` | `executar_com_intimacao()` (pre-check canal, prazo_intimacao, fallback_mandado, mandado_explicito); `executar_requests()` (tipo_documento default "CUMPRIMENTO") |
| `projudi/rag_router.py` | Cria records a partir da sequência (batch) |
| `projudiProcessNavigator.py` | `ProcessoParser` — `extrair_movimentacoes()` (categoria/meio_comunicacao), `extrair_localizador()`, `extrair_classe()` |
| `processes/movimentacoes_service.py` | `buscar_cumprimentos_similares()`, `meio_comunicacao()`, `extrair_prazo_dias()` |
