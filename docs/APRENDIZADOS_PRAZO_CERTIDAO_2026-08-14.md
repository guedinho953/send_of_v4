# APRENDIZADOS — Contagem de Prazo + Comunicações Tracker + Certidão de Prazo

Data: 14/08/2026
Autor: Ivan (send_of_v4) — assistido por Hermes Agent

---

## 0. ONDE ESTÃO AS ALTERAÇÕES DE HOJE

### 0.1 Não comitadas (estado atual do working tree)

Arquivos **MODIFICADOS** (já rastreados pelo git, sem commit):

| Arquivo | O que mudou |
|---|---|
| `projudi/cumprimento_service.py` | +745 linhas — núcleo: PrazoService, tracker, observação/certidão de prazo, gancho de movimentação, polo (autor/réu/ambos) |
| `projudi/models.py` | +153 linhas — campos `prazo_info` / `observacao_prazo` em `CumprimentoRecord`; modelos `Feriado` e `SuspensaoPrazo` |
| `projudi/movimentacao_service.py` | +7 linhas — parâmetro `certidao_titulo` usado no campo `descricao` da certidão (não aparece mais "Certidão Criminal" numa certidão de prazo) |
| `projudi/admin.py` | +26 linhas — exibição dos campos de prazo no admin |

Arquivos **NOVOS** (untracked):

| Arquivo | Função |
|---|---|
| `projudi/prazo_service.py` | `PrazoService` — contagem CPC/CNJ (DJEN, feriados móveis/fixos, recesso 20/12–22/01, suspensões) |
| `projudi/feriados_nacionais.py` | Tabela de feriados nacionais (fixos + móveis por ano) |
| `projudi/management/commands/popular_feriados.py` | Seed de feriados no banco |
| `projudi/migrations/0013_feriado_suspensaoprazo.py` | Migration dos modelos Feriado/SuspensaoPrazo |
| `projudi/migrations/0014_cumprimentorecord_observacao_prazo_and_more.py` | Migration dos campos de prazo no CumprimentoRecord |
| `criar_template_certidao_prazo.py` | Cria `DocumentTemplate` id=11 "Certidão de Prazo" (brasão + rodapé + variáveis) |
| `test_prazo_feriados.py` | Testes automatizados (TODOS OS ASSERTS PASSARAM) |
| `validar_contador_2024.py` | Validação contra contador manual do Ivan (BATE? True) |

> ⚠️ **ATENÇÃO — migration pendente**: `python manage.py makemigrations --check`
> pede `processes/migrations/0014_alter_ragexample_sequencia_cumprimento.py`
> ("Alter field sequencia_cumprimento on ragexample"). É só ajuste de definição
> de campo JSONField (sem risco a dados). Gerar com:
> `python manage.py makemigrations processes`

### 0.2 Backup local (salvo antes de reverter o fluxo crítico)

Pasta: `/home/ivan/PythonProjects/send_of_v4/BACKUP_ALTERACOES_2026-08-14/`

- `modified/` → cópias dos 4 arquivos alterados COMO ESTAVAM antes do revert do
  `movimentacao_service.py` (ou seja, incluem o estado das 16:27)
- `new/` → os arquivos novos listados acima
- `diffs/` → patches `git diff` de cada arquivo modificado (mostra exatamente o que mudou vs ontem/commit `dbc31bf`)

> O `/mnt/e` (E:) **não** foi usado: é root-only no WSL e sem sudo disponível.
> O backup ficou na própria pasta do projeto, acessível pelo Windows.

### 0.3 Config do Hermes (modelo) — fora do projeto

Arquivo: `~/.hermes/config.yaml` (alterado via `hermes config set`, não por
edição direta — o Hermes bloqueia escrita direta em config de segurança).

- `model.default`: `deepseek-v4-flash`
- `model.provider`: `opencode-zen` (corrigido de `opencode-go` — é o provedor
  que tem os modelos **free**)
- `model.base_url`: `https://opencode.ai/zen/v1`
- `fallback_model`: **removido** (sem fallback, como pedido — se o deepseek
  falhar, a sessão para em vez de cair em outro modelo)
- Aliases free adicionados: `/glm`, `/kimi`, `/qwen`, `/minimax`, `/nemotron`,
  `/mimo`, `/hy3`, `/ling` (além dos originais `/codigo`, `/rapido`, `/medio`,
  `/padrao`, `/pago`, `/visual`)
- ⚠️ A mudança de modelo do **Hermes** só vale em sessão NOVA. Esta sessão já
  iniciou com o modelo anterior. Trocar modelo DENTRO da conversa: `/glm`, etc.

---

## 1. O QUE FOI IMPLEMENTADO

### 1.1 Contagem de prazo automática (`PrazoService`)
- Regras CPC/CNJ: dia da intimação NÃO conta; fins de semana, feriados e recesso
  (20/12–22/01) suspendem; `ultimo_dia` = N-ésimo dia útil; `data_decurso` = dia
  seguinte.
- **DJEN** (art. 5º §3º): 1º dia da intimação + 1º dia útil subsequente NÃO
  contam; conta do 3º dia útil.
- **Decadencial**: corre todos os dias, sem suspensão.
- Carga de feriados/suspensões do **banco** (modelos `Feriado`/`SuspensaoPrazo`),
  isolados por tenant e filtráveis por court/vara.

### 1.2 Comunicações Tracker integrado
- `_data_intimacao_do_tracker` usa `ComunicacaoTracker` (de
  `comunicacao_tracker.py`) sobre o `Movement` do processo para captar a **data
  REAL** da intimação da parte (situação concluída/lida). É a fonte autorizada
  da `data_inicio`.

### 1.3 Observação de prazo controlada (JSON)
- Flags **independentes** no `RAGExample.sequencia_cumprimento`:
  - `observacao_prazo`: bool → texto na observação do Mov581
  - `expede_certidao_prazo`: bool → gera a CERTIDÃO DE PRAZO (documento à parte)
  - `polo_prazo`: `'autor'` | `'reu'` | `'ambos'` → para quem corre o prazo
- Texto genérico/elegante, identifica COMO foi a intimação (DJEN/AR/advogado/
  e-mail) e os 4 marcos (leitura, início, término, decurso). Sem citar artigos.

### 1.4 Certidão de Prazo integrada com movimentações
- Template `DocumentTemplate` id=11 "Certidão de Prazo" — reaproveita a base
  visual da certidão criminal (brasão embutido, Times New Roman, rodapé de
  assinatura eletrônica), trocando só o corpo (contagem de prazo em vez de
  "negativa de antecedentes"). Variáveis: `processo`, `parte`, `observacao_prazo`,
  `data`, `servidor`.
- `_html_certidao_prazo` renderiza esse template (fallback mantido caso o
  template não exista).
- Gancho em `_executar_movimentacao_simples` →
  `MovimentacaoService.executar_requests(mov, certidao_html=..., certidao_titulo='Certidão de Prazo')`.
  Esse método É o fluxo Playwright já testado (injeta no FCKeditor, assina).
  **Não** foi reescrito o Playwright — só passado o HTML certo.
- Roteamento conservador: `eletronico`/`advogado` → `_executar_via_movimentacao`
  → `_executar_movimentacao_simples`. `email`/`edital` mantidos como placeholder.

### 1.5 Destinatário da certidão (autor/réu/ambos)
- `_rotulo_parte(papel, nome)` gera "à parte autora X" / "ao réu X" / "aos
  autores e réus".
- `_papel_resolvido(record)` lê `polo_prazo` do JSON da RAG (sobrepõe
  `parte_papel` do record). Usado no texto da observação E no template da
  certidão.

---

## 2. COMO FUNCIONA (arquitetura resumida)

```
RAGExample.sequencia_cumprimento[]
   └─ {'tipo':'movimentacao', 'observacao_prazo':bool,
       'expede_certidao_prazo':bool, 'polo_prazo':'autor|reu|ambos'}
            │
            ▼
CumprimentoService._config_prazo_do_rag(record)  →  {'observacao_prazo','expede_certidao_prazo','polo_prazo'}
            │
            ▼
gerar_observacao_prazo(record)
   ├─ Fonte 1: ComunicacaoTracker (Movement)  → data_inicio REAL
   ├─ Fonte 2: despacho/RAG (snippet)         → prazo_dias + modo
   ├─ PrazoService.contar_prazo_por_fluxo()   → ultimo_dia / data_decurso
   ├─ _texto_observacao_prazo()              → observacao_prazo (com polo)
   └─ salva em record.prazo_info / record.observacao_prazo
            │
            ▼
_executar_movimentacao_simples(record)
   ├─ observacao = observacao_para_movimentacao(record)  [se flag]
   ├─ certidao_html = _html_certidao_prazo(record)        [se flag]
   ├─ cria MovimentacaoRecord (parte_papel resolvido)
   └─ MovimentacaoService.executar_requests(mov, certidao_html=...,
                                            certidao_titulo='Certidão de Prazo')
            │
            ▼
        Playwright (já existente): injeta certidão no FCKeditor + assina
```

---

## 3. POR QUE (motivação / decisões)

1. **Decisão soberana no JSON da RAG**: o operador (Ivan) configura na RAG se
   quer observação e/ou certidão e para quem (polo). O código só obedece — não
   adivinha. Isso evita falsos positivos e respeita o fluxo de curadoria RAG.

2. **Não quebrar o que já funciona**: o fluxo Playwright de certidão (certidão
   criminal) já estava validado. A certidão de prazo REUTILIZA esse caminho
   exato (`certidao_html` + `certidao_titulo`), só trocando o título e o
   conteúdo. Reverti `movimentacao_service.py` ao estado de ontem quando uma
   alteração ficou incompleta, e reapliquei só o necessário (`certidao_titulo`
   no campo `descricao`) — compatível com o fluxo criminal (default mantém o
   texto criminal).

3. **Tracker como fonte autorizada da data**: a data da intimação vem do
   `Movement` rastreado, não de suposição no despacho. Garante contagem correta
   mesmo quando o despacho não cita a data.

4. **Validação contra contador manual**: `validar_contador_2024.py` compara o
   `PrazoService` com o contador manual do Ivan (caso 2024: 15 dias úteis,
   contados 15, último 04/11/2024, decurso 05/11/2024 → BATE? True). Isso dá
   confiança de que a lógica está igual à prática do cartório.

5. **Conservadorismo no roteamento**: só `eletronico`/`advogado` foram ligados
   ao gancho de prazo. `email`/`edital` ficaram como placeholder para não
   alterar comportamento de fluxos não solicitados.

6. **Bug corrigido no teste de hoje**: `gerar_observacao_prazo` retornava
   "Já calculado" e não gerava o texto quando `prazo_info` existia mas
   `observacao_prazo` estava vazio. Corrigido para regerar o texto sempre que
   `observacao_prazo` estiver vazio (re-execuções passam a gerar a observação).

---

## 4. COMO TESTAR / VALIDAR

```bash
# 1. Servidor de dev (já reiniciado com --noreload para pegar as mudanças)
python manage.py runserver 0.0.0.0:8000 --noreload

# 2. Testes automatizados
python test_prazo_feriados.py          # TODOS OS ASSERTS PASSARAM
python validar_contador_2024.py        # BATE? True
python manage.py check                 # 1 warning irrelevante (static)

# 3. No dashboard (login admin@admin.com):
#    - Criar CumprimentoRecord com RAG tendo polo_prazo + flags
#    - Executar o cumprimento → observação e/ou certidão vão ao Projudi via Playwright

# 4. Trocar modelo do Hermes DENTRO da conversa (aliases free):
#    /glm  /kimi  /qwen  /minimax  /nemotron  /mimo  /hy3  /ling
#    /padrao (volta p/ deepseek-v4-flash)   /pago (glm-5.1)   /visual (gpt-5-nano)
```

---

## 5. PENDÊNCIAS / PRÓXIMOS PASSOS

- [ ] Gerar migration pendente: `python manage.py makemigrations processes`
- [ ] Teste end-to-end com Playwright em processo real do Projudi (Ivan testa
      no dashboard com dados reais)
- [ ] Opcional: ligar `_executar_ar` também à observação de prazo (AR conta do
      dia seguinte) — deixado fora do escopo conservador desta sessão
- [ ] Commit das alterações (quando Ivan aprovar)
