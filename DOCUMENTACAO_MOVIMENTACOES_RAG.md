# 📚 Como Processar Movimentações do Projudi e Construir RAG (Antes da Juntada)

> **Objetivo:** Ensinar como extrair, processar e rastrear movimentações do Projudi (intimações, mandados, avisos de recebimento) — transformar o texto judicial em dicionário estruturado, cruzar expedidas/lidas, e salvar no banco para usar como **RAG** (memória de cumprimentos anteriores) antes de decidir se a movimentação do juiz deve ser cumprida.

---

## 🎯 Visão Geral do Fluxo

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Projudi  │ ▶ │ Extrair  │ ▶ │ Dict     │
│ (HTML)    │     │ Movs     │     │ Estrut.  │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
                                    ┌─────────────┐
                                    │ Rastrear │
                                    │ Expedidas│
                                    │ / Lidas  │
                                    └─────────────┘
                                              │
                                              ▼
                                    ┌─────────────┐
                                    │ Salvar   │
                                    │ no Banco │
                                    │ (RAG)    │
                                    └─────────────┘
                                              │
                                              ▼
                                    ┌─────────────┐
                                    │ Decidir  │
                                    │ Cumprir? │
                                    │ (LLM)    │
                                    └─────────────┘
```

---

## 1. Extrair Movimentações do Projudi (HTML → Lista)

### Onde está a informação?

A página **DadosProcesso** do Projudi tem uma tabela de movimentações. Cada linha (`<tr>`) representa um evento:

| Coluna | Significado |
|--------|-------------|
| Evento (número) | ID sequencial da movimentação |
| Ato | Texto descritivo (ex: "Intimação expedida p/ João") |
| Data | Data da movimentação |
| Autor | Quem criou (Juiz, Sistema, etc.) |
| Observação | Span escondido que expande com clique |
| Documentos | Links para download |

### Como o sistema extrai (requests + BeautifulSoup):

```python
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

def extrair_movimentacoes(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    movimentacoes = []

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue

        numero = tds[0].get_text(strip=True)
        if not re.fullmatch(r"\d+", numero):
            continue  # pula cabeçalho

        # Ato principal
        evento = tds[1].get_text(" ", strip=True)
        texto_evento = evento.lower()

        # Data
        data_str = tds[2].get_text(strip=True)

        # Autor
        autor = tds[3].get_text(" ", strip=True)

        # --- Observação escondida (span id="obs123") ---
        observacao = ""
        documentos = []
        id_mov = None

        for a in tr.find_all("a", href=True):
            m = re.search(r"mostra\('sub(\d+)'\)", a["href"])
            if m:
                id_mov = m.group(1)

        if id_mov:
            span_obs = soup.find("span", id=f"obs{id_mov}")
            if span_obs:
                observacao = span_obs.get_text(" ", strip=True)

            span_sub = soup.find("span", id=f"sub{id_mov}")
            if span_sub:
                for a in span_sub.find_all("a", href=True):
                    href = a["href"].lower()
                    if href.startswith("javascript") or "original=true" in href:
                        continue
                    documentos.append({
                        "nome": a.get_text(strip=True),
                        "url": urljoin(base_url, href)
                    })

        movimentacoes.append({
            "evento": numero,
            "ato": evento,
            "ato_normalizado": texto_evento,
            "data_texto": data_str,
            "autor": autor,
            "observacao": observacao,
            "documentos": documentos,
        })

    return movimentacoes
```

> 💡 **Dica:** As observações e documentos ficam em `<span>` escondidos que só aparecem no HTML completo (não precisa de clique — o Projudi já envia tudo no HTML, só está com `display:none`).

---

## 2. Classificar a Movimentação

### O que cada movimentação é?

```python
import re

PADROES_CLASSIFICACAO = {
    "sentenca": re.compile(
        r'julgo\s+procedente|julgo\s+improcedente|extingo\s+o\s+processo|'
        r'resolu[cç][aã]o\s+de\s+m[eé]rito|art\.\s*487|condeno|honor[aá]rios',
        re.I
    ),
    "decisao": re.compile(
        r'tutela\s+de\s+urg[eê]ncia|defiro\s+a\s+liminar|indefiro\s+a\s+liminar',
        re.I
    ),
    "despacho": re.compile(
        r'despacho|intimem?-se|expe[cç]a-se|oficie-se|certifique-se|arquive-se',
        re.I
    ),
    "intimacao": re.compile(r'intima[cç][aã]o', re.I),
    "citacao": re.compile(r'cita[cç][aã]o', re.I),
    "certidao": re.compile(r'certid[aã]o|juntada\s+de\s+ar|aviso\s+de\s+recebimento', re.I),
    "mandado": re.compile(r'mandado', re.I),
    "audiencia": re.compile(r'audi[eê]ncia', re.I),
}

def classificar_movimentacao(texto_ato):
    scores = {}
    for tipo, padrao in PADROES_CLASSIFICACAO.items():
        scores[tipo] = len(padrao.findall(texto_ato))

    tipo_final = max(scores, key=scores.get)
    if scores[tipo_final] == 0:
        return "indefinido", scores
    return tipo_final, scores
```

---

## 3. Transformar Texto Judicial em Dicionário Estruturado

Este é o coração do processamento. Cada ato do juiz precisa virar um **dicionário** com:
- `ato` (ex: "intime-se")
- `destinatario` (ex: "parte ré")
- `meio` (ex: "por mandado")
- `objetivo` (ex: "para manifestar-se")
- `prazo` (ex: "15 dias")
- `condicoes` (ex: "sob pena de revelia")

### Regex de extração:

```python
import re

PADROES_COMANDOS = {
    # =========================================================
    # 1. ATO (verbo imperativo)
    # =========================================================
    'ato': re.compile(
        r'(intimem?-se|oficie-se|cite-se|notifique-se|'
        r'expe[cç]a-se|arquive-se|certifique-se|publique-se|registre-se)',
        re.I
    ),

    # =========================================================
    # 2. DESTINATÁRIO
    # =========================================================
    'destinatario': re.compile(
        r'parte\s+autora|parte\s+r[eé]|executad[ao]s?|'
        r'embargad[ao]s?|exequente|advogado|minist[eé]rio\s+p[úú]blico',
        re.I
    ),

    # =========================================================
    # 3. MEIO (como vai ser entregue)
    # =========================================================
    'meio': re.compile(
        r'por\s+mandado|por\s+of[ií]cio|por\s+e-?mail|'
        r'atrav[eé]s\s+de\s+seu\s+advogado|por\s+oficial\s+de\s+justi[cç]a|'
        r'whats(?:app|zap)|eletr[ooô]nicamente|domic[ií]lio\s+judicial',
        re.I
    ),

    # =========================================================
    # 4. OBJETIVO (o que a parte deve fazer)
    # =========================================================
    'objetivo': re.compile(
        r'(?:para\s+)?(manifestar-se|contrarrazoar|pagar|juntar|'
        r'apresentar|impugnar|regularizar|comparecer|informar|'
        r'comprovar|depositar|efetuar\s+pagamento)',
        re.I
    ),

    # =========================================================
    # 5. PRAZO
    # =========================================================
    'prazo': re.compile(
        r'(?:no\s+prazo\s+de|prazo\s+de)\s+(\d+\s*(?:dias?|horas?|meses?))',
        re.I
    ),

    # =========================================================
    # 6. CONDIÇÕES (penalidades, lógica condicional)
    # =========================================================
    'condicoes': re.compile(
        r'\b('
            r'sob\s+pena\s+de\s+[a-zçãéêíóú\s]+'
            r'|findo\s+o\s+prazo'
            r'|caso\s+n[aã]o\s+haja'
            r'|na\s+aus[eê]ncia\s+de'
            r'|havendo\s+concord[aâ]ncia'
        r')\b',
        re.I
    ),
}
```

### Função de extração completa:

```python
def transformar_texto_em_dict(texto_judicial: str, tipo_classificado: str) -> list:
    """
    Transforma um texto judicial em lista de dicionários estruturados.
    Cada dicionário = um comando cumprível.
    """
    import re

    texto = re.sub(r'\s+', ' ', texto_judicial).strip().lower()

    # --- PASSO 1: Verificar se é cumprivel ---
    atos = list(PADROES_COMANDOS['ato'].finditer(texto))
    atos_extraidos = {m.group().lower().strip() for m in atos}

    # Só esses atos a secretaria pode cumprir sozinha
    ATOS_PERMITIDOS = {
        'publique-se', 'registre-se', 'arquive-se',
        'intime-se', 'intimem-se', 'cite-se', 'expeça-se',
        'certifique-se', 'oficie-se'
    }
    
    cumprivel = atos_extraidos.issubset(ATOS_PERMITIDOS)
    if not cumprivel:
        print(f"❌ Não é cumprivel. Atos encontrados: {atos_extraidos}")
        return []

    # --- PASSO 2: Extrair cada comando ---
    resultado = []

    for j, ato in enumerate(atos):
        inicio = ato.start()
        if j < len(atos) - 1:
            fim = atos[j + 1].start()  # até o próximo ato
        else:
            fim = len(texto)  # até o fim do texto

        trecho = texto[inicio:fim]

        dados = {
            'tipo': tipo_classificado,          # sentenca, despacho, etc.
            'cumprivel': cumprivel,
            'ato': ato.group(),                 # ex: "intime-se"
            'trecho': trecho,                   # texto entre este ato e o próximo
            'condicoes': [],
            'destinatario': [],
            'meio': [],
            'objetivo': [],
            'prazo': [],
        }

        # --- PASSO 3: Extrair campos via regex ---
        for campo in ['condicoes', 'destinatario', 'meio', 'objetivo', 'prazo']:
            dados[campo] = [
                m.group() for m in PADROES_COMANDOS[campo].finditer(trecho)
            ]

        # --- PASSO 4: Bloquear se tiver condição perigosa ---
        if dados['condicoes']:
            dados['cumprivel'] = False
            print(f"⚠️ Condições encontradas, não é cumprivel automático:")
            print(dados['condicoes'])

        # --- PASSO 5: Normalizar destinatário ---
        if not dados['destinatario']:
            dados['destinatario'] = ['partes']  # fallback

        resultado.append(dados)

    return resultado
```

### Exemplo de uso:

```python
texto = """
DESPACHO¹

Diante do explanado, intimem-se as executadas para
pagarem o débito remanescente de R$ 943,18 e/ou manifestar
no prazo de 15 dias, sob pena de prosseguimento do feito
com consequente penhora.
"""

comandos = transformar_texto_em_dict(texto, "despacho")
# Resultado:
# [{
#   'tipo': 'despacho',
#   'cumprivel': True,
#   'ato': 'intimem-se',
#   'destinatario': ['as executadas'],
#   'meio': [],  # não especificou meio
#   'objetivo': ['pagarem', 'manifestar'],
#   'prazo': ['15 dias'],
#   'condicoes': ['sob pena de prosseguimento do feito'],
#   'cumprivel': False  # ← bloqueado por condição!
# }]
```

---

## 4. Rastrear Expedidas ←→ Lidas (Rastreamento de Comunicações)

Este é o módulo de **re-atreamento** — cruzar o que foi **expedido** com o que foi **lido/devolvido**.

### Conceito:

| Evento | Ato | Situação |
|--------|-----|----------|
| 45 | Intimação expedida p/ João | **expedida** |
| 67 | Intimação lida em 10/05/26 (Referente ao evento 45) | **lida** |
| 89 | Aviso de Recebimento juntado (Referente ao evento 45) | **AR juntado** |

### Funções de classificação da comunicação:

```python
def situacao_comunicacao(texto):
    texto = str(texto).lower()
    if 'lido(a)' in texto:            return 'lida'
    if 'expedido(a)' in texto:         return 'expedida'
    if 'devolução sem leitura' in texto: return 'devolvida_sem_leitura'
    if 'juntada de ar' in texto:       return 'ar_juntado'
    if 'mandado devolvido' in texto:    return 'mandado_devolvido'
    if 'mandado assinado' in texto:     return 'mandado_assinado'
    if 'mandado à disposição' in texto: return 'mandado_disponivel'
    return None

def tipo_comunicacao(texto):
    texto = texto.lower()
    if 'citação' in texto:    return 'citacao'
    if 'intimação' in texto:  return 'intimacao'
    if 'certidão' in texto:    return 'certidao'
    if 'mandado' in texto:     return 'mandado'
    return 'outro'

def meio_comunicacao(texto):
    texto = texto.lower()
    if any(x in texto for x in ('advgs', 'advogado')):
        return 'advogado'
    if 'ofício' in texto:
        return 'oficio'
    if 'mandado' in texto:
        return 'mandado'
    if 'aviso de recebimento' in texto:
        return 'ar'
    if re.search(r'\bpara\b', texto):
        return 'pessoal'
    return None
```

### Cruzar Expedidas com Lidas:

```python
import pandas as pd

def cruzar_expedidas_lidas(df_movimentacoes):
    """
    Recebe DataFrame com todas as movimentações de UM processo.
    Retorna DataFrame com relações: qual expedida foi lida/AR juntado.
    """
    # Marcar situação e tipo
    df = df_movimentacoes.copy()
    df['situacao'] = df['ato'].apply(situacao_comunicacao)
    df['tipo'] = df['ato'].apply(tipo_comunicacao)
    df['meio_real'] = df['ato'].apply(meio_comunicacao)

    # Separar
    df_expedidas = df[df['situacao'] == 'expedida'].copy()
    df_lidas = df[df['situacao'].isin(['lida', 'devolvida_sem_leitura', 'ar_juntado'])].copy()

    # Criar chave de cruzamento: destinatario + data
    df_expedidas['chave'] = (
        df_expedidas['destinatario'].str.lower().str.strip()
        + '|' + df_expedidas['data_texto']
    )
    df_lidas['chave'] = (
        df_lidas['destinatario'].str.lower().str.strip()
        + '|' + df_lidas['data_referencia_str']  # data do evento original
    )

    # Merge
    relacoes = df_lidas.merge(
        df_expedidas,
        on=['chave', 'destinatario', 'tipo'],
        suffixes=('_lido', '_expedido')
    )

    # Extrair evento de origem do texto "Referente ao evento X"
    relacoes['ato_origem'] = relacoes['ato_lido'].str.extract(
        r'Referente ao evento\s+(.*?)\(', expand=False
    )
    relacoes['data_origem'] = relacoes['ato_lido'].str.extract(
        r'\((\d{2}/\d{2}/\d{2})\)', expand=False
    )

    return relacoes
```

### Colunas do DataFrame resultante:

| Coluna | Significado |
|--------|-------------|
| `evento_expedido` | Número do evento que expediu |
| `evento_lido` | Número do evento que registrou a leitura |
| `data_expedicao` | Quando foi expedido |
| `data_leitura` | Quando foi lido |
| `destinatario` | Quem recebeu |
| `meio` | Meio de comunicação |
| `ato_origem` | Texto do ato original |
| `prazo` | Prazo extraído do texto |
| `status` | `lida`, `devolvida_sem_leitura`, `ar_juntado` |

---

## 5. Extrair Dados das Partes (Para saber como comunicar)

Cada parte do processo tem canais de comunicação:

| Campo | De onde vem |
|-------|-------------|
| `tem_advogado` | Tabela de partes (coluna advogado) |
| `domicilio_cnj` | Ícone de domicílio judicial eletrônico |
| `recebe_intimacao_email` | Ícone de envelope na tabela |
| `email` | Span escondido com endereço |
| `tel` | Span escondido com telefone |
| `polo` | PROMOVENTE (autor/exequente) ou PROMOVIDO (réu/executado) |
| `revelia` | Nome contém "(rev. arg.)" |

### Função de status do processo:

```python
def status_processo(df_partes):
    """
    Verifica se TODAS as partes de ambos os polos têm canal de comunicação.
    """
    autores_ok = df_partes.loc[
        df_partes['papel'] == 'PROMOVENTE',
        'habilitada_receber'
    ].all()

    acusados_ok = df_partes.loc[
        df_partes['papel'] == 'PROMOVIDO',
        'habilitada_receber'
    ].all()

    if autores_ok and acusados_ok:
        return True, 'automatizar'
    if autores_ok and not acusados_ok:
        return False, 'reu_pendente'
    if not autores_ok and acusados_ok:
        return False, 'autor_pendente'
    return False, 'ambos_pendentes'
```

> 💡 **Uso:** Se `status == 'automatizar'`, a secretaria pode cumprir sozinha. Se não, precisa de intervenção manual.

---

## 6. Modelos Django para Salvar (Base do RAG)

### Modelos necessários:

```python
from django.db import models

class ProcessoMovimentacao(models.Model):
    """Cada movimentação de um processo"""
    numero_processo = models.CharField(max_length=25, db_index=True)
    numero_processo_cnj = models.CharField(max_length=25, blank=True)
    evento = models.CharField(max_length=10)
    ato = models.TextField()
    ato_normalizado = models.TextField()
    tipo = models.CharField(max_length=30)  # sentenca, despacho, intimacao...
    categoria = models.CharField(max_length=30, blank=True)  # citacao, intimacao...
    situacao = models.CharField(max_length=30, blank=True)   # expedida, lida...
    meio = models.CharField(max_length=30, blank=True)      # advogado, mandado, email...
    data_texto = models.CharField(max_length=20)
    data_obj = models.DateField()
    autor = models.CharField(max_length=100)
    observacao = models.TextField(blank=True)
    documentos = models.JSONField(default=list)  # [{"nome": "...", "url": "..."}]
    
    # Campos de processamento
    comandos_extraidos = models.JSONField(default=list)  # resultado do transforma_texto_dict
    cumprivel = models.BooleanField(default=False)
    status_cumprimento = models.CharField(max_length=30, default='nao_analisado')
    
    class Meta:
        ordering = ['-data_obj']
        unique_together = ['numero_processo', 'evento']


class ComunicacaoRastreada(models.Model):
    """
    Cruzamento: o que foi expedido e o que foi lido/devolvido.
    Uma linha = uma comunicação completa (expedição + leitura).
    """
    processo = models.CharField(max_length=25, db_index=True)
    tipo = models.CharField(max_length=20)  # intimacao, citacao, mandado, ar
    
    # Expedição
    evento_expedido = models.CharField(max_length=10)
    data_expedicao = models.DateField()
    ato_expedido = models.TextField()
    destinatario = models.CharField(max_length=300)
    meio = models.CharField(max_length=30)
    
    # Leitura / Retorno
    evento_lido = models.CharField(max_length=10, blank=True, null=True)
    data_leitura = models.DateField(blank=True, null=True)
    situacao = models.CharField(max_length=30)  # lida, devolvida_sem_leitura, ar_juntado
    
    # Prazo
    prazo_dias = models.IntegerField(blank=True, null=True)
    prazo_vencido = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-data_expedicao']


class CumprimentoHistorico(models.Model):
    """
    Memória de cumprimentos realizados — para RAG futuro.
    Quando o sistema cumpre uma movimentação, salva aqui.
    """
    processo = models.CharField(max_length=25, db_index=True)
    tipo_movimentacao = models.CharField(max_length=30)
    ato = models.CharField(max_length=100)
    destinatario = models.CharField(max_length=300)
    meio_utilizado = models.CharField(max_length=50)  # email, oficio, mandado...
    
    # Contexto
    texto_completo = models.TextField()  # movimentação original
    comandos_json = models.JSONField(default=dict)  # dicionário estruturado
    
    # Resultado
    email_enviado = models.BooleanField(default=False)
    email_destino = models.EmailField(blank=True)
    juntada_realizada = models.BooleanField(default=False)
    data_cumprimento = models.DateTimeField(auto_now_add=True)
    
    # Para busca semântica (RAG)
    embedding = models.JSONField(null=True, blank=True)  # vetor gerado por LLM
    
    class Meta:
        ordering = ['-data_cumprimento']
        verbose_name = 'Cumprimento Histórico'
        verbose_name_plural = 'Cumprimentos Históricos'
```

---

## 7. Pipeline Completo: De Extrair a Salvar

```python
def processar_movimentacoes_processo(numero_processo, html_dados_processo):
    """
    Pipeline completo para UM processo.
    """
    from projudiProcessNavigator import ProcessoParser
    
    # 1. Parsear HTML
    parser = ProcessoParser(html_dados_processo)
    dados = parser.parse_processo()
    
    partes = dados['partes']
    movimentacoes = dados['movimentacoes']
    
    # 2. Para cada movimentação, classificar e extrair comandos
    for mov in movimentacoes:
        # Classificar
        tipo, scores = classificar_movimentacao(mov['ato'])
        mov['tipo'] = tipo
        
        # Extrair dados estruturados (se for despacho/sentença)
        if tipo in ('despacho', 'sentenca', 'decisao'):
            comandos = transformar_texto_em_dict(mov['ato'], tipo)
            mov['comandos_extraidos'] = comandos
            mov['cumprivel'] = any(c['cumprivel'] for c in comandos)
        
        # Salvar no banco
        ProcessoMovimentacao.objects.update_or_create(
            numero_processo=numero_processo,
            evento=mov['evento'],
            defaults={
                'ato': mov['ato'],
                'tipo': mov.get('tipo', ''),
                'categoria': mov.get('categoria', ''),
                'situacao': mov.get('situacao_comunicacao', ''),
                'meio': mov.get('meio_comunicacao', ''),
                'data_texto': mov['data_texto'],
                'data_obj': mov['data_obj'],
                'autor': mov['autor'],
                'observacao': mov.get('observacao', ''),
                'documentos': mov.get('documentos', []),
                'comandos_extraidos': mov.get('comandos_extraidos', []),
                'cumprivel': mov.get('cumprivel', False),
            }
        )
    
    # 3. Rastrear comunicações (expedidas ←→ lidas)
    df = pd.DataFrame(movimentacoes)
    relacoes = cruzar_expedidas_lidas(df)
    
    for _, row in relacoes.iterrows():
        ComunicacaoRastreada.objects.update_or_create(
            processo=numero_processo,
            evento_expedido=row['evento_expedido'],
            defaults={
                'tipo': row['tipo'],
                'data_expedicao': row['data_expedicao'],
                'destinatario': row['destinatario'],
                'meio': row['meio'],
                'evento_lido': row.get('evento_lido'),
                'data_leitura': row.get('data_leitura'),
                'situacao': row['situacao'],
                'prazo_dias': row.get('prazo_dias'),
            }
        )
    
    # 4. Verificar se processo está pronto para automatização
    df_partes = pd.DataFrame(partes)
    ok, status = status_processo(df_partes)
    
    return {
        'processo': numero_processo,
        'movimentacoes': len(movimentacoes),
        'comunicacoes_rastreadas': len(relacoes),
        'automatizavel': ok,
        'status': status,
    }
```

---

## 8. RAG — Usar Cumprimentos Anteriores como Contexto

### Conceito:

Quando uma **nova** movimentação chega, o sistema busca no banco:
> "Já cumpri algo parecido antes? Como foi feito?"

### Como implementar (com busca por similaridade de texto):

```python
def buscar_cumprimentos_similares(texto_movimentacao, top_k=3):
    """
    Busca cumprimentos históricos similares ao texto da movimentação atual.
    Usa similaridade de cosseno entre embeddings (ou simples substring match).
    """
    # Versão simples (sem embedding)
    historicos = CumprimentoHistorico.objects.all()
    
    resultados = []
    for h in historicos:
        # Similaridade simples: palavras em comum
        palavras_atual = set(texto_movimentacao.lower().split())
        palavras_historico = set(h.texto_completo.lower().split())
        intersecao = palavras_atual & palavras_historico
        
        if len(intersecao) > 5:  # threshold arbitrário
            resultados.append({
                'similaridade': len(intersecao),
                'processo': h.processo,
                'meio_utilizado': h.meio_utilizado,
                'comandos': h.comandos_json,
                'data': h.data_cumprimento,
            })
    
    # Ordenar por similaridade
    resultados.sort(key=lambda x: x['similaridade'], reverse=True)
    return resultados[:top_k]
```

### Usar no prompt do LLM:

```python
prompt = f"""
Você é um assistente da secretaria judiciária.

NOVA MOVIMENTAÇÃO PARA CUMPRIR:
{texto_movimentacao}

CUMPRIMENTOS SIMILARES REALIZADOS ANTES:
{formatar_similares(similares)}

Com base nos cumprimentos anteriores, qual o melhor meio de comunicação?
Responda em JSON:
{{
  "meio_sugerido": "email|mandado|oficio|advogado|djen",
  "justificativa": "...",
  "prazo_esperado": "..."
}}
"""
```

---

## 9. Resumo dos Arquivos e Suas Funções

| Arquivo (existente) | O que faz |
|---------------------|-----------|
| `projudiProcessNavigator.py` | `ProcessoParser` — extrai partes, movimentações, links do HTML |
| `scripts_send_of_v2/transforma_texto_dict.ipynb` | Regex que transforma texto judicial em dicionário (`ato`, `destinatario`, `meio`, `objetivo`, `prazo`, `condicoes`) |
| `scripts_send_of_v2/intimacoes_lidas_expedidas.ipynb` | Funções `expedidas()`, `lidas()`, `relacoes()` — cruzam comunicações expedidas com lidas |
| `scripts_send_of_v2/mandados_ars.ipynb` | Variante para mandados e avisos de recebimento |
| `pipeline_orchestrator.py` | Orquestrador que integra tudo: extrai → analisa → busca RAG → executa |
| `projudi/oficio_service.py` | `juntar_cumprimento()` — executa a juntada no Projudi |

---

## 10. Regras de Ouro

| Regra | Por quê |
|-------|---------|
| **Sempre parse o HTML completo** | Observações e documentos estão em spans escondidos |
| **Normalize texto em lowercase** | Regex funciona melhor sem case |
| **Use trecho entre atos** | Cada ato só é válido até o próximo verbo imperativo |
| **Bloqueie se houver condição** | "sob pena de revelia" = precisa de análise humana |
| **Cruze expedida com lida** | Só assim você sabe se a comunicação foi recebida |
| **Salve comandos como JSON** | Permite busca e comparação futura (RAG) |
| **Guarde embedding se possível** | Busca semântica é melhor que palavras-chave |
| **Não junte antes de processar** | A juntada é a ÚLTIMA etapa, depois de toda análise |

---

## 11. Checklist: Antes de Juntar

- [ ] Extraí todas as movimentações do processo?
- [ ] Classifiquei cada uma (sentença, despacho, intimação...)?
- [ ] Transformei o texto em dicionário estruturado?
- [ ] Verifiquei se é `cumprivel` (sem condições perigosas)?
- [ ] Rastreei expedidas ←→ lidas para saber o status?
- [ ] Verifiquei se as partes têm canal de comunicação?
- [ ] Busquei cumprimentos similares no histórico (RAG)?
- [ ] O LLM sugeriu o melhor meio de cumprimento?
- [ ] Só então: **executar o cumprimento (email/juntada)**

---

*Documento gerado para fins educativos. A estrutura do HTML do Projudi pode mudar — mantenha os seletores atualizados.*
