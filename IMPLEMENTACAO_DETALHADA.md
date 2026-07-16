# Plano de Implementação - Evolução SCCJ v4

## Análise do Código Existente (send_of_v2)

### 1. Arquivos Funcionais

| Arquivo | Função | Status |
|---------|--------|--------|
| `projudi_bot.py` | Gerencia sessão/cookies via browser_cookie3 | ✅ Funciona |
| `projudi_client.py` | Cliente HTTP para Projudi | ✅ Funciona |
| `enviar.ipynb` | Envia ofícios + faz juntada | ✅ Funciona |
| `projudiProcessNavigator.py` | Extrai partes e movimentações | ✅ Funciona |
| `projudiDocReader.py` | Analisa comandos judiciais | ✅ Funciona |
| `projudi_command_analyzer_new.py` | Analisa comandos com spaCy | ✅ Funciona |

### 2. Fluxo Atual Identificado

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUXO ATUAL (send_of_v2)                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. projudi_bot.py                                               │
│     └─> Captura cookies do Firefox (browser_cookie3)            │
│     └─> Mantém sessão ativa (keep_alive)                        │
│                                                                  │
│  2. projudi_client.py                                            │
│     └─> Navega páginas Projudi (requests + cookies)             │
│     └─> Extrai links (ofícios, processos, movimentações)        │
│                                                                  │
│  3. enviar.ipynb                                                 │
│     └─> Lista ofícios expedidos                                 │
│     └─> Extrai texto do ofício (BS4)                            │
│     └─> Extrai email destinatário (regex)                       │
│     └─> Envia email (SMTP Gmail)                                │
│     └─> Faz juntada no Projudi (Selenium)                       │
│     └─> Registra em CSV (protocolo_email_projudi.csv)           │
│                                                                  │
│  4. projudiProcessNavigator.py                                   │
│     └─> Extrai partes (autor/réu)                               │
│     └─> Extrai movimentações com datas                          │
│     └─> Relaciona eventos (expedição → leitura)                 │
│                                                                  │
│  5. projudiDocReader.py / projudi_command_analyzer_new.py        │
│     └─> Extrai comandos judiciais (regex + spaCy)               │
│     └─> Classifica comandos (intimação, ofício, etc)            │
│     └─> Salva em SQLite (comandos)                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Lacunas Identificadas

| Lacuna | Descrição | Prioridade |
|--------|-----------|------------|
| **Banco de Dados Vetorial** | Não existe pgvector para RAG | 🔴 Alta |
| **Persistência de Cumprimentos** | CSV é limitado, sem histórico estruturado | 🔴 Alta |
| **Automação de Cliques** | Selenium apenas para juntada, falta cobertura | 🟡 Média |
| **RAG para Decisões** | Não há busca semântica de padrões | 🔴 Alta |
| **Integração Django** | Tudo em notebooks/scripts soltos | 🟡 Média |

---

## 4. Plano de Implementação

### FASE 1: Modelo de Dados (Sprint 1-2)

#### 1.1 Models Django - App `judicial_commands`

```python
# judicial_commands/models.py

from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex


class JudicialProcess(models.Model):
    """Processo judicial"""
    numero = models.CharField(max_length=50, unique=True)
    numero_normalizado = models.CharField(max_length=50)  # sem formatação
    
    # Partes
    partes = models.JSONField(default=list)  # Lista de partes extraídas
    
    # URLs Projudi
    url_dados = models.URLField(max_length=500)
    url_movimentar = models.URLField(max_length=500, blank=True)
    
    # Metadados
    vara = models.CharField(max_length=200, blank=True)
    comarca = models.CharField(max_length=200, blank=True)
    classe_processual = models.CharField(max_length=100, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['numero']),
            models.Index(fields=['numero_normalizado']),
        ]


class JudicialCommand(models.Model):
    """Comando judicial extraído de decisão/despacho"""
    
    # Relacionamento
    processo = models.ForeignKey(
        JudicialProcess, 
        on_delete=models.CASCADE,
        related_name='comandos'
    )
    
    # Identificação única do trecho
    hash_trecho = models.CharField(max_length=64, unique=True)
    
    # Texto
    texto_original = models.TextField()
    texto_normalizado = models.TextField()
    
    # Classificação
    tipo_documento = models.CharField(max_length=50, choices=[
        ('despacho', 'Despacho'),
        ('sentenca', 'Sentença'),
        ('decisao', 'Decisão Interlocutória'),
        ('atOrdinatorio', 'Ato Ordinatório'),
    ])
    
    ato = models.CharField(max_length=100)  # intime-se, oficie-se, etc
    trecho = models.TextField()
    
    # Dados extraídos
    destinatarios = models.JSONField(default=list)
    objetivos = models.JSONField(default=list)
    prazo = models.JSONField(default=dict)  # {'dias': 5, 'tipo': 'úteis'}
    meio = models.JSONField(default=list)  # ['email', 'mandado']
    condicoes = models.JSONField(default=list)
    
    # Custas
    tem_custas = models.BooleanField(default=False)
    texto_custas = models.TextField(blank=True)
    
    # Cumprimento
    cumprivel = models.BooleanField(default=True)
    polo_ativo_automatizavel = models.BooleanField(default=True)
    polo_passivo_automatizavel = models.BooleanField(default=True)
    
    # Contexto
    evento_numero = models.CharField(max_length=20, blank=True)
    evento_data = models.DateField(null=True, blank=True)
    url_documento = models.URLField(max_length=500, blank=True)
    url_movimentacao = models.URLField(max_length=500, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['ato']),
            models.Index(fields=['tipo_documento']),
            models.Index(fields=['cumprivel']),
            GinIndex(fields=['destinatarios']),
        ]


class ComplianceAction(models.Model):
    """Registro de como um comando foi cumprido"""
    
    # Relacionamento
    comando = models.ForeignKey(
        JudicialCommand,
        on_delete=models.CASCADE,
        related_name='cumprimentos'
    )
    
    # Tipo de ação
    tipo_acao = models.CharField(max_length=50, choices=[
        ('email_enviado', 'Email Enviado'),
        ('juntada_projudi', 'Juntada no Projudi'),
        ('oficio_gerado', 'Ofício Gerado'),
        ('mandado_gerado', 'Mandado Gerado'),
        ('intimacao_realizada', 'Intimação Realizada'),
        ('manual', 'Cumprimento Manual'),
    ])
    
    # Detalhes
    descricao = models.TextField()
    passos_executados = models.JSONField(default=list)
    
    # Dados do envio
    email_destino = models.EmailField(blank=True)
    email_msg_id = models.CharField(max_length=200, blank=True)
    email_data_envio = models.DateTimeField(null=True, blank=True)
    
    # URLs Projudi
    url_oficio = models.URLField(max_length=500, blank=True)
    url_recebimento = models.URLField(max_length=500, blank=True)
    url_baixa = models.URLField(max_length=500, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('concluido', 'Concluído'),
        ('parcial', 'Parcial'),
        ('pendente', 'Pendente'),
        ('falhou', 'Falhou'),
    ])
    
    # Observações
    observacoes = models.TextField(blank=True)
    itens_pendentes = models.JSONField(default=list)
    
    # Número do ofício
    numero_oficio = models.CharField(max_length=50, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['tipo_acao']),
            models.Index(fields=['status']),
            models.Index(fields=['email_data_envio']),
        ]


class CompliancePattern(models.Model):
    """Padrão de cumprimento para RAG"""
    
    # Identificação
    nome_padrao = models.CharField(max_length=200)
    tipo_comando = models.CharField(max_length=100)  # intime-se, oficie-se
    
    # Descrição
    descricao = models.TextField()
    
    # Passos recomendados
    passos_recomendados = models.JSONField(default=list)
    
    # Templates
    templates_documentos = models.JSONField(default=list)
    
    # Navegação Projudi
    navegacao_projudi = models.JSONField(default=dict)
    # Ex: {
    #   'url': '/movimentacao/MovimentarProcesso',
    #   'selectors': {
    #       'codigo_mov': '#seqCategoriaMovimentacao',
    #       'observacao': '#observacao',
    #       'concluir': '#Concluir'
    #   }
    # }
    
    # Exemplos de sucesso
    exemplos_sucesso = models.ManyToManyField(
        ComplianceAction,
        related_name='padroes'
    )
    
    # Métricas
    uso_count = models.IntegerField(default=0)
    taxa_sucesso = models.FloatField(default=0.0)
    
    # Texto para embedding (será usado pelo pgvector)
    texto_embedding = models.TextField()
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['tipo_comando']),
            models.Index(fields=['is_active']),
        ]
```

#### 1.2 Models para Vetores - App `vector_store`

```python
# vector_store/models.py

from django.db import models
from django.contrib.postgres.fields import ArrayField


class VectorEmbedding(models.Model):
    """Model base para embeddings vetoriais"""
    
    # Tipo de conteúdo
    content_type = models.CharField(max_length=50, choices=[
        ('comando_judicial', 'Comando Judicial'),
        ('cumprimento', 'Cumprimento'),
        ('padrao', 'Padrão'),
    ])
    
    # ID do objeto relacionado
    object_id = models.PositiveIntegerField()
    
    # Texto original
    texto_original = models.TextField()
    texto_normalizado = models.TextField()
    
    # Embedding (384 dimensões para all-MiniLM-L6-v2)
    embedding = ArrayField(
        models.FloatField(),
        size=384,
        null=True
    )
    
    # Metadados
    metadata = models.JSONField(default=dict)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['content_type']),
            models.Index(fields=['object_id']),
        ]
        unique_together = [['content_type', 'object_id']]
```

### FASE 2: Pipeline RAG (Sprint 3-4)

#### 2.1 Embedder Service

```python
# vector_store/services.py

from sentence_transformers import SentenceTransformer
from django.db import connection
from typing import List, Dict
import numpy as np


class EmbeddingService:
    """Serviço de geração e busca de embeddings"""
    
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        self.model = SentenceTransformer(model_name)
        self.dimensions = 384
    
    def generate_embedding(self, text: str) -> List[float]:
        """Gera embedding para um texto"""
        embedding = self.model.encode(text)
        return embedding.tolist()
    
    def generate_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Gera embeddings para múltiplos textos"""
        embeddings = self.model.encode(texts, batch_size=32)
        return [e.tolist() for e in embeddings]
    
    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calcula similaridade cosseno entre dois vetores"""
        a = np.array(vec1)
        b = np.array(vec2)
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    
    def search_similar(
        self, 
        query_text: str, 
        content_type: str = None,
        top_k: int = 5,
        threshold: float = 0.7
    ) -> List[Dict]:
        """Busca textos similares usando similaridade cosseno no PostgreSQL"""
        
        query_embedding = self.generate_embedding(query_text)
        
        # Query SQL com similaridade cosseno
        sql = """
        SELECT 
            id,
            content_type,
            object_id,
            texto_original,
            texto_normalizado,
            metadata,
            1 - (embedding <=> %s::real[]) as similarity
        FROM vector_store_vectorembedding
        WHERE embedding IS NOT NULL
        """
        
        params = [query_embedding]
        
        if content_type:
            sql += " AND content_type = %s"
            params.append(content_type)
        
        sql += f"""
        ORDER BY embedding <=> %s::real[]
        LIMIT {top_k}
        """
        params.append(query_embedding)
        
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        # Filtra por threshold
        results = [r for r in results if r['similarity'] >= threshold]
        
        return results
```

#### 2.2 RAG Pipeline

```python
# judicial_commands/rag_pipeline.py

from vector_store.services import EmbeddingService
from .models import JudicialCommand, ComplianceAction, CompliancePattern
from typing import List, Dict, Optional
import json


class JudicialRAGPipeline:
    """Pipeline RAG para recuperação de padrões de cumprimento"""
    
    def __init__(self):
        self.embedder = EmbeddingService()
    
    def index_command(self, command: JudicialCommand):
        """Indexa um comando judicial no banco vetorial"""
        
        # Prepara texto para embedding
        texto = f"""
        Ato: {command.ato}
        Trecho: {command.texto_normalizado}
        Destinatários: {json.dumps(command.destinatarios)}
        Objetivos: {json.dumps(command.objetivos)}
        """
        
        # Gera embedding
        embedding = self.embedder.generate_embedding(texto)
        
        # Salva
        from vector_store.models import VectorEmbedding
        VectorEmbedding.objects.update_or_create(
            content_type='comando_judicial',
            object_id=command.id,
            defaults={
                'texto_original': command.texto_original,
                'texto_normalizado': command.texto_normalizado,
                'embedding': embedding,
                'metadata': {
                    'ato': command.ato,
                    'tipo_documento': command.tipo_documento,
                    'processo_numero': command.processo.numero,
                }
            }
        )
    
    def index_compliance(self, compliance: ComplianceAction):
        """Indexa um cumprimento realizado"""
        
        command = compliance.comando
        
        # Prepara texto
        texto = f"""
        Tipo de ação: {compliance.tipo_acao}
        Comando original: {command.ato} - {command.texto_normalizado[:200]}
        Descrição: {compliance.descricao}
        Passos: {json.dumps(compliance.passos_executados)}
        Status: {compliance.status}
        """
        
        # Gera embedding
        embedding = self.embedder.generate_embedding(texto)
        
        # Salva
        from vector_store.models import VectorEmbedding
        VectorEmbedding.objects.update_or_create(
            content_type='cumprimento',
            object_id=compliance.id,
            defaults={
                'texto_original': compliance.descricao,
                'texto_normalizado': texto,
                'embedding': embedding,
                'metadata': {
                    'tipo_acao': compliance.tipo_acao,
                    'status': compliance.status,
                    'comando_id': command.id,
                    'numero_oficio': compliance.numero_oficio,
                }
            }
        )
    
    def find_similar_commands(
        self, 
        query: str, 
        top_k: int = 5
    ) -> List[Dict]:
        """Busca comandos similares ao query"""
        
        results = self.embedder.search_similar(
            query_text=query,
            content_type='comando_judicial',
            top_k=top_k,
            threshold=0.6
        )
        
        # Enriquece com dados do comando
        enriched = []
        for r in results:
            command = JudicialCommand.objects.get(id=r['object_id'])
            enriched.append({
                'command': command,
                'similarity': r['similarity'],
                'texto': r['texto_normalizado'],
            })
        
        return enriched
    
    def find_successful_compliances(
        self,
        command: JudicialCommand,
        top_k: int = 3
    ) -> List[Dict]:
        """Busca cumprimentos bem-sucedidos para comandos similares"""
        
        # Busca comandos similares
        similar = self.find_similar_commands(
            query=command.texto_normalizado,
            top_k=top_k * 2  # Busca mais para ter opções
        )
        
        # Busca cumprimentos bem-sucedidos
        successful = []
        for item in similar:
            compliances = ComplianceAction.objects.filter(
                comando=item['command'],
                status='concluido'
            ).order_by('-created_at')[:2]
            
            for c in compliances:
                successful.append({
                    'compliance': c,
                    'similarity': item['similarity'],
                    'command': item['command'],
                })
        
        # Ordena por similaridade
        successful.sort(key=lambda x: x['similarity'], reverse=True)
        
        return successful[:top_k]
    
    def generate_compliance_plan(
        self,
        command: JudicialCommand
    ) -> Dict:
        """Gera plano de cumprimento usando RAG"""
        
        # 1. Busca cumprimentos similares bem-sucedidos
        similar_compliances = self.find_successful_compliances(command)
        
        # 2. Busca padrões conhecidos
        patterns = CompliancePattern.objects.filter(
            tipo_comando=command.ato,
            is_active=True
        ).order_by('-taxa_sucesso', '-uso_count')[:3]
        
        # 3. Monta contexto para LLM
        context = {
            'current_command': {
                'ato': command.ato,
                'texto': command.texto_normalizado,
                'destinatarios': command.destinatarios,
                'prazo': command.prazo,
                'processo': command.processo.numero,
            },
            'similar_compliances': [
                {
                    'tipo_acao': c['compliance'].tipo_acao,
                    'descricao': c['compliance'].descricao,
                    'passos': c['compliance'].passos_executados,
                    'similarity': c['similarity'],
                }
                for c in similar_compliances
            ],
            'known_patterns': [
                {
                    'nome': p.nome_padrao,
                    'descricao': p.descricao,
                    'passos': p.passos_recomendados,
                    'taxa_sucesso': p.taxa_sucesso,
                }
                for p in patterns
            ]
        }
        
        # 4. Aqui seria chamado o LLM (Qwen 2.5) para gerar o plano
        # Por enquanto, retorna o contexto para o LLM processar
        
        return {
            'context': context,
            'suggested_actions': self._suggest_actions(command, similar_compliances),
            'confidence': self._calculate_confidence(similar_compliances, patterns),
        }
    
    def _suggest_actions(
        self,
        command: JudicialCommand,
        similar_compliances: List[Dict]
    ) -> List[Dict]:
        """Sugere ações baseado em cumprimentos similares"""
        
        if not similar_compliances:
            return []
        
        # Conta tipos de ação mais comuns
        action_counts = {}
        for c in similar_compliances:
            tipo = c['compliance'].tipo_acao
            action_counts[tipo] = action_counts.get(tipo, 0) + 1
        
        # Ordena por frequência
        sorted_actions = sorted(
            action_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return [
            {'tipo': tipo, 'frequencia': count}
            for tipo, count in sorted_actions
        ]
    
    def _calculate_confidence(
        self,
        similar_compliances: List[Dict],
        patterns: List[CompliancePattern]
    ) -> float:
        """Calcula confiança na sugestão"""
        
        if not similar_compliances and not patterns:
            return 0.0
        
        # Média das similaridades
        if similar_compliances:
            avg_similarity = sum(
                c['similarity'] for c in similar_compliances
            ) / len(similar_compliances)
        else:
            avg_similarity = 0.0
        
        # Bonus por padrões conhecidos
        pattern_bonus = 0.2 if patterns else 0.0
        
        return min(avg_similarity + pattern_bonus, 1.0)
```

### FASE 3: Automação Projudi (Sprint 5-6)

#### 3.1 Projudi Action Executor

```python
# projudi_automation/executor.py

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import random


class ProjudiActionExecutor:
    """Executa ações automatizadas no Projudi"""
    
    def __init__(self, driver):
        self.driver = driver
        self.wait = WebDriverWait(driver, 20)
        self.short_wait = WebDriverWait(driver, 5)
    
    def _human_delay(self, min_sec=1, max_sec=3):
        """Delay aleatório para simular comportamento humano"""
        time.sleep(random.uniform(min_sec, max_sec))
    
    def _type_human_like(self, element, text):
        """Digita como um humano"""
        for char in text:
            element.send_keys(char)
            time.sleep(random.randint(50, 150) / 1000)
    
    def realizar_juntada(
        self,
        url_recebimento: str,
        codigo_movimentacao: str,
        observacao: str
    ) -> Dict:
        """
        Realiza juntada de recebimento no Projudi
        
        Baseado no código do enviar.ipynb:
        - url_recebimento: URL da página de recebimento
        - codigo_movimentacao: Código da movimentação (ex: '11383')
        - observacao: Texto da observação
        """
        
        try:
            # 1. Navega para página de recebimento
            self.driver.get(url_recebimento)
            self._human_delay(2, 4)
            
            # 2. Scroll para visualizar
            self.driver.execute_script("window.scrollBy(0, 567);")
            self._human_delay(1, 2)
            
            # 3. Preenche código da movimentação
            codigo_field = self.wait.until(
                EC.presence_of_element_located((By.ID, "seqCategoriaMovimentacao"))
            )
            codigo_field.clear()
            self._type_human_like(codigo_field, codigo_movimentacao)
            self._human_delay(1, 2)
            
            # 4. Clica no botão buscar
            btn_busca = self.short_wait.until(
                EC.element_to_be_clickable((By.ID, "btnBuscaMovimentacao"))
            )
            btn_busca.click()
            self._human_delay(2, 3)
            
            # 5. Preenche observação
            obs_field = self.wait.until(
                EC.presence_of_element_located((By.ID, "observacao"))
            )
            obs_field.clear()
            self._type_human_like(obs_field, observacao)
            self._human_delay(1, 2)
            
            # 6. Scroll para concluir
            self.driver.execute_script("window.scrollBy(0, 567);")
            self._human_delay(1, 2)
            
            # 7. Clica em concluir
            btn_concluir = self.wait.until(
                EC.element_to_be_clickable((By.ID, "Concluir"))
            )
            btn_concluir.click()
            self._human_delay(2, 3)
            
            # 8. Aguarda e aceita alerta
            alert = WebDriverWait(self.driver, 10).until(
                EC.alert_is_present()
            )
            alert_text = alert.text
            alert.accept()
            self._human_delay(2, 3)
            
            return {
                'success': True,
                'message': f'Juntada realizada: {alert_text}'
            }
            
        except TimeoutException as e:
            return {
                'success': False,
                'message': f'Timeout: {str(e)}'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Erro: {str(e)}'
            }
    
    def expedir_intimacao(
        self,
        url_processo: str,
        tipo_intimacao: str,
        destinatario: str,
        prazo_dias: int = None
    ) -> Dict:
        """
        Expede intimação no Projudi
        
        TODO: Implementar baseado nos padrões observados
        """
        
        try:
            # 1. Navega para o processo
            self.driver.get(url_processo)
            self._human_delay(2, 4)
            
            # 2. Clica em "Movimentar Processo"
            btn_movimentar = self.wait.until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'movimentar processo')]"
                ))
            )
            btn_movimentar.click()
            self._human_delay(2, 3)
            
            # TODO: Continuar implementação baseada nos padrões reais
            
            return {
                'success': True,
                'message': 'Intimação expedida'
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erro: {str(e)}'
            }
    
    def anexar_documento(
        self,
        url_processo: str,
        file_path: str,
        tipo_documento: str
    ) -> Dict:
        """
        Anexa documento ao processo
        
        TODO: Implementar baseado nos padrões observados
        """
        pass


class ProjudiNavigationPatterns:
    """Padrões de navegação conhecidos no Projudi"""
    
    # Mapeamento de ações para seletores/URLs
    PATTERNS = {
        'juntada_recebimento': {
            'url_pattern': '/movimentacao/MovimentarProcesso',
            'params': ['numeroProcesso', 'juntadaAr', 'codDocVinculado'],
            'selectors': {
                'codigo_mov': '#seqCategoriaMovimentacao',
                'btn_busca': '#btnBuscaMovimentacao',
                'observacao': '#observacao',
                'btn_concluir': '#Concluir',
            },
            'codigos_movimentacao': {
                'recebimento_oficio': '11383',
                'juntada_peticao': '192',
                'expedicao_oficio': '159',
            }
        },
        
        'expedicao_oficio': {
            'url_pattern': '/listagens/CumprimentoCartorio',
            'steps': [
                'navigate_to_cumprimento',
                'select_tipo_oficio',
                'fill_oficio_data',
                'generate_document',
                'attach_and_send'
            ],
            'selectors': {
                'tipo_select': 'select[name="tipoDocumento"]',
                'generate_btn': 'button#gerarOficio',
            }
        },
        
        'analisar_movimentacao': {
            'url_pattern': '/cadastros/AnalisarMovimentacao',
            'selectors': {
                'table_movimentacoes': 'table.tabelaLista',
                'link_movimentar': 'a[href*="MovimentarAnalise"]',
                'link_dispensar': 'a[href*="dispensar=true"]',
            }
        }
    }
    
    @classmethod
    def get_pattern(cls, action_type: str) -> Dict:
        """Retorna padrão de navegação para tipo de ação"""
        return cls.PATTERNS.get(action_type, {})
```

### FASE 4: Integração com Django (Sprint 7-8)

#### 4.1 Tasks Celery

```python
# judicial_commands/tasks.py

from celery import shared_task
from .rag_pipeline import JudicialRAGPipeline
from .models import JudicialCommand, ComplianceAction


@shared_task
def index_judicial_command(command_id: int):
    """Indexa comando judicial no banco vetorial"""
    
    command = JudicialCommand.objects.get(id=command_id)
    pipeline = JudicialRAGPipeline()
    pipeline.index_command(command)
    
    return f'Comando {command_id} indexado'


@shared_task
def index_compliance_action(compliance_id: int):
    """Indexa cumprimento no banco vetorial"""
    
    compliance = ComplianceAction.objects.get(id=compliance_id)
    pipeline = JudicialRAGPipeline()
    pipeline.index_compliance(compliance)
    
    return f'Cumprimento {compliance_id} indexado'


@shared_task
def generate_compliance_plan(command_id: int):
    """Gera plano de cumprimento usando RAG"""
    
    command = JudicialCommand.objects.get(id=command_id)
    pipeline = JudicialRAGPipeline()
    
    plan = pipeline.generate_compliance_plan(command)
    
    return plan


@shared_task
def execute_projudi_action(action_type: str, params: dict):
    """Executa ação no Projudi via Celery"""
    
    from projudi_automation.executor import ProjudiActionExecutor
    from projudi_automation.session_manager import get_active_session
    
    session = get_active_session()
    executor = ProjudiActionExecutor(session.driver)
    
    if action_type == 'juntada':
        result = executor.realizar_juntada(
            url_recebimento=params['url_recebimento'],
            codigo_movimentacao=params['codigo_movimentacao'],
            observacao=params['observacao']
        )
    else:
        result = {'success': False, 'message': 'Ação não implementada'}
    
    return result
```

#### 4.2 Views

```python
# judicial_commands/views.py

from django.views.generic import ListView, DetailView, CreateView
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import JudicialCommand, ComplianceAction
from .rag_pipeline import JudicialRAGPipeline
from .tasks import generate_compliance_plan


class CommandListView(ListView):
    """Lista comandos judiciais"""
    model = JudicialCommand
    template_name = 'judicial_commands/command_list.html'
    context_object_name = 'commands'
    paginate_by = 20


class CommandDetailView(DetailView):
    """Detalhes de um comando judicial"""
    model = JudicialCommand
    template_name = 'judicial_commands/command_detail.html'
    context_object_name = 'command'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Busca cumprimentos similares
        pipeline = JudicialRAGPipeline()
        similar = pipeline.find_successful_compliances(self.object)
        context['similar_compliances'] = similar
        
        return context


def generate_plan_view(request, command_id):
    """Gera plano de cumprimento via API"""
    
    command = get_object_or_404(JudicialCommand, id=command_id)
    
    # Dispara task async
    task = generate_compliance_plan.delay(command_id)
    
    return JsonResponse({
        'task_id': task.id,
        'status': 'processing'
    })
```

---

## 5. Próximos Passos Imediatos

### Prioridade 1: Estrutura Django
- [ ] Criar projeto Django com apps: `core`, `base`, `judicial_commands`, `vector_store`, `projudi_automation`
- [ ] Configurar PostgreSQL com pgvector
- [ ] Criar models baseados no plano acima
- [ ] Rodar migrations

### Prioridade 2: Migração de Dados
- [ ] Migrar dados do CSV `protocolo_email_projudi.csv` para `ComplianceAction`
- [ ] Migrar dados do SQLite `juizados_especiais.db` para `JudicialCommand`
- [ ] Indexar dados existentes no banco vetorial

### Prioridade 3: RAG Básico
- [ ] Implementar `EmbeddingService` com Sentence-BERT
- [ ] Implementar busca por similaridade
- [ ] Criar API para gerar planos de cumprimento

### Prioridade 4: Automação
- [ ] Refatorar `ProjudiActionExecutor` baseado no `enviar.ipynb`
- [ ] Criar biblioteca de padrões de navegação
- [ ] Implementar testes de automação

---

## 6. Estrutura de Arquivos Proposta

```
send_of_v4/
├── core/                          # App principal
│   ├── models.py
│   ├── views.py
│   └── urls.py
│
├── base/                          # App base compartilhado
│   ├── models.py                  # TimeStampedModel, etc
│   ├── middleware.py              # Multi-tenant
│   └── utils.py
│
├── judicial_commands/             # App de comandos judiciais
│   ├── models.py                  # JudicialCommand, ComplianceAction
│   ├── services.py                # Lógica de negócio
│   ├── rag_pipeline.py            # Pipeline RAG
│   ├── tasks.py                   # Tasks Celery
│   ├── views.py
│   └── urls.py
│
├── vector_store/                  # App de banco vetorial
│   ├── models.py                  # VectorEmbedding
│   ├── services.py                # EmbeddingService
│   ├── search.py                  # Busca vetorial
│   └── migrations/
│
├── projudi_automation/            # App de automação
│   ├── models.py                  # ProjudiSession, ActionLog
│   ├── executor.py                # ProjudiActionExecutor
│   ├── navigator.py               # ProjudiNavigationPatterns
│   ├── session_manager.py         # Gerenciamento de sessão
│   └── tasks.py
│
├── manage.py
├── requirements.txt
└── docker-compose.yml
```
