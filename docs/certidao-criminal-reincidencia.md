# Certidão Criminal — Reincidência

## Lógica

1. Extrair todos os **autores do fato** do processo
2. Para cada autor, buscar no Projudi pelo nome
3. Se **todos** têm apenas **1 resultado** (só o processo atual):
   - Gerar certidão criminal (art. 76, §2º, II e §4º da Lei 9.099/95)
4. Se 1 autor → template singular. Se vários → template plural.

## Fluxo

```
Extrair autores do fato
  │
  ├─ Autor 1 → Buscar no Projudi → N resultados
  ├─ Autor 2 → Buscar no Projudi → N resultados
  └─ ...
       │
       ▼
  Todos com 1 resultado?
       │
       ├─ Sim → Gerar certidão
       │         ├─ 1 autor → texto singular
       │         └─ N autores → texto plural
       │
       └─ Não → Relatar / pular
```

## Templates

### 1 autor
```
PODER JUDICIÁRIO DO ESTADO DA BAHIA
2ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE PAULO AFONSO
Rua das Caraibeiras, 420, Quadra 04 - 1º Andar, General Dutra - PAULO AFONSO
pafonso-2vsj@tjba.jus.br // Tel.: (75) 3281-8372

CERTIDÃO

PROCESSO N.º  -  {{ processo }}
AUTOR DO FATO -  {{ autor_nome }}
VÍTIMA        -  {{ vitima_nome }}

Em observância ao art. 76, §2º, II, e §4º da Lei nº. 9.099/95 fiz busca
no sistema Projudi e constatei que o(a) autor(a) do fato, {{ autor_nome }}
qualificado(a) nos autos, NÃO FOI BENEFICIADO(A) anteriormente no prazo
de 05 (cinco) anos, pela aplicação de pena restritiva ou multa.

O referido é verdade, Dou fé.

Paulo Afonso-BA, {{ data_atual }}.
{{ servidor_nome }}
{{ servidor_cargo }}
```

### N autores
```
PROCESSO N.º  -  {{ processo }}
AUTOR DO FATO -  {{ autores_nomes }}
VÍTIMA        -  {{ vitima_nome }}

... constatei que os(as) autores(as) do fato, qualificados(as) nos autos,
NÃO FOI BENEFICIADO anteriormente no prazo de 05 (cinco) anos...
```

## Placeholders

| Placeholder | Origem |
|---|---|
| `{{ processo }}` | Nº CNJ |
| `{{ autor_nome }}` | Nome do autor (1) |
| `{{ autores_nomes }}` | Nomes separados |
| `{{ vitima_nome }}` | Nome da vítima |
| `{{ data_atual }}` | Data de hoje |
| `{{ servidor_nome }}` | Servidor |
| `{{ servidor_cargo }}` | Cargo |
