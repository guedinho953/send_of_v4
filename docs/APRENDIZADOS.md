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
