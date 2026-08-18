# Aprendizados — RAGs de Bloqueio por Frases (NÃO FAZER / NÃO CUMPRIR)

> Consolidado em 2026-08-18. Substitui o mecanismo puro de "RAG com sequência vazia"
> por um bloqueio **determinístico por frases** — resolve a diluição do Jaccard.

---

## 1. Problema que motivou

RAGs "NÃO CUMPRIR" eram cadastradas com `sequencia_cumprimento = []` (vazia) e o
sistema bloqueava quando elas apareciam no topo do ranking de similaridade.

**Porém o Jaccard diluía:** uma RAG com observação LONGUA (ex.: liminar+segredo+
bloqueio, ~30 palavras) acertava o despacho, mas perdia pontos por causa das outras
25 palavras que o despacho real não repete:

```
jaccard = intersecao / min(palavras_atual, palavras_hist)
        = 5 / 8 = 0.67   ← a quantidade de palavras atrapalha
```

Resultado: RAG de bloqueio ficava em 0.67 (zona de risco) e uma RAG **com sequência**
(mandado) com vocabulário parecido podia "roubar" o despacho e expedir indevidamente.

## 2. Solução: Frases Bloqueadoras Determinísticas

Em vez de depender da contagem de palavras, o sistema agora verifica **substring real**
de frases-chave no texto do despacho — ANTES do matching por similaridade.

### Novo campo no RAGExample
```
frases_bloqueio      JSONField: ["certifique-se sobre a tempestividade", ...]
exigir_todas_frases  Boolean: True = TODAS as frases (AND) / False = qualquer uma (OR)
```

- **Vazio** → RAG normal, executa sua sequência.
- **Preenchido** → RAG bloqueadora: se a frase estiver no despacho, BLOQUEIA.

### Função determinística
```python
def encontrar_bloqueio(texto_movimentacao):
    # normaliza (minúsculas, sem acento) ambos os lados
    # percorre RAGs active=True com frases_bloqueio preenchido
    # retorna a primeira RAG que "disparou" (substring)
    # OR (padrão) ou AND (exigir_todas_frases=True)
```

## 3. Fluxo Integrado no expedir_rapido.py

```
PARA cada movimentação:
    texto = extraído do documento
    1º  → encontrar_bloqueio(texto)        ← DETERMINÍSTICO, primeiro!
          se disparar: BLOQUEIA (não executa nada)
    2º  → buscar_cumprimentos_similares()  ← só se não foi bloqueado
          executa mandado/ofício/intimação conforme a sequência
```

Flag `--ignorar-bloqueio` desativa o passo 1 (apenas para testes), via
`expedir_rapido.IGNORAR_BLOQUEIO` global.

## 4. Frases cadastradas (2026-08-18)

| RAG | Frases | Modo |
|-----|--------|------|
| 2444 | certifique-se sobre a tempestividade, integral seguranca do juizo | OR |
| 2450 | certifique-se a secretaria sobre a tempestividade, integral seguranca do juizo | OR |
| 2526 | certifique-se sobre a procuração | OR |
| 2527 | atualize-se o endereco, remarque-se a audiencia | OR |
| 2532 | acordo firmado entre as partes nao chegou a ser homologado, diligencias pendentes | OR |
| 2535 | concessao da tutela provisoria de urgencia, segredo de justica, bloqueio de conta | AND |
| 2537 | desarquive-se sem custas, assistencia judiciaria gratuita | OR |
| 2539 | convole o deposito judicial em penhora, efeito suspensivo aos embargos | OR |
| 2543 | oficie-se ao juizo deprecado, devolucao da carta precatoria | OR |
| 2544 | carta precatoria acostada, certifique-se a secretaria se | OR |

**Duplicata eliminada:** RAG 2536 (cópia da 2535) → `active=False`.

## 5. Resultado do teste real

| Despacho | Bloqueia? | RAG |
|----------|-----------|-----|
| "Certifique-se sobre a procuração..." | ✅ SIM | 2526 |
| "Certifique-se a secretaria sobre a tempestividade..." | ✅ SIM | 2450 |
| "concessão da tutela provisória + segredo + bloqueio" | ✅ SIM | 2535 (AND) |
| "Atualize-se o endereço... remarque-se a audiência" | ✅ SIM | 2527 |
| "Oficie-se ao Juízo deprecado... devolução da carta precatória" | ✅ SIM | 2543 |
| "Vista ao Ministério Público para parecer" | ✅ NÃO (correto!) | — |
| "Citem-se as partes para responder" | ✅ NÃO (correto!) | — |
| "Expeça-se mandado de citação do executado..." | ✅ NÃO (correto!) → matching RAG 2445 | — |

**Falso positivo: ZERO.** Despachos de "fazer" não são bloqueados.

## 6. Por que funciona melhor

| | Jaccard de vocabulário (RAG vazia) | Frase bloqueadora |
|---|---|---|
| Sensível a texto longo | ❌ Sim (dilui) | ✅ Não |
| Determinístico | ❌ Probabilístico | ✅ Substring |
| Falso positivo | ⚠️ Possível | ✅ Raro |
| Auditoria | ❌ Score oculto | ✅ Sabemos qual frase disparou |
| Prioridade | Só no ranking | ✅ Corre ANTES |

## 7. Arquivos alterados
- `processes/models.py` → campos `frases_bloqueio`, `exigir_todas_frases`
- `processes/migrations/0015_*.py` → migration dos campos
- `processes/admin.py` → fieldset "Frases Bloqueadoras"
- `processes/movimentacoes_service.py` → função `encontrar_bloqueio()`
- `expedir_rapido.py` → passo 1 de bloqueio + flag `IGNORAR_BLOQUEIO`
- `preencher_frases_bloqueio.py` → script de seed das frases
- `expedir_mandado_humanizado.py` → correção do loop por destinatário

## 8. Próximos passos sugeridos
- [ ] Revisar as frases com base em novos despachos reais que aparecerem
- [ ] Testar o fluxo completo no dashboard (botões) — integrar o passo de bloqueio
      também no `CumprimentoService` se necessário
- [ ] Considerar diferenciar "NÃO FAZER" (nunca) de "JÁ FEITO" (observar antes)
```
