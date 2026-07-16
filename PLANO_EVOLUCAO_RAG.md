# Plano de Evolução - SCCJ v4

## 1. Arquitetura do Sistema de RAG para Cumprimentos Judiciais

### 1.1 Componentes Principais

```
┌─────────────────────────────────────────────────────────┐
│                    FLUXO RAG JUDICIAL                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐      ┌──────────────────┐            │
│  │  Projudi     │─────>│  Extractor       │            │
│  │  (Selenium)  │      │  (BS4/Regex)     │            │
│  └──────────────┘      └────────┬─────────┘            │
│                                 │                       │
│                                 ▼                       │
│  ┌──────────────┐      ┌──────────────────┐            │
│  │  Qwen 2.5    │<─────│  Embedder        │            │
│  │  (Local)     │      │  (Sentence-BERT) │            │
│  └──────────────┘      └────────┬─────────┘            │
│          ▲                      │                       │
│          │                      ▼                       │
│  ┌──────────────┐      ┌──────────────────┐            │
│  │  Gerador     │<─────│  pgvector        │            │
│  │  Respostas   │      │  (PostgreSQL)    │            │
│  └──────────────┘      └──────────────────┘            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 1.2 Modelos de Dados Propostos

#### 1.2.1 JudicialCommand (Comando Judicial)
```python
class JudicialCommand(models.Model):
    """Armazena comandos judiciais extraídos de decisões/despachos"""
    
    # Identificação
    command_hash = models.CharField(max_length=64, unique=True)
    original_text = models.TextField()
    normalized_text = models.TextField()
    
    # Classificação
    command_type = models.CharField(max_length=50, choices=[
        ('citacao', 'Citação'),
        ('intimacao', 'Intimação'),
        ('penhora', 'Penhora'),
        ('alvara', 'Alvará'),
        ('mandado', 'Mandado'),
        ('oficio', 'Ofício'),
        ('audiencia', 'Audiência'),
        ('sentenca', 'Sentença'),
        ('decisao', 'Decisão Interlocutória'),
        ('despacho', 'Despacho'),
    ])
    
    # Contexto
    process_number = models.CharField(max_length=50)
    court = models.CharField(max_length=200)
    judge = models.CharField(max_length=200)
    event_number = models.CharField(max_length=20)
    event_date = models.DateField()
    
    # Partes envolvidas
    target_parties = models.JSONField()  # Lista de partes destinatárias
    
    # Requisitos de cumprimento
    requirements = models.JSONField()  # O que deve ser feito
    deadline_days = models.IntegerField(null=True)
    deadline_date = models.DateField(null=True)
    
    # Vetor para busca semântica
    embedding = models.VectorField(dimensions=384)  # Sentence-BERT
    
    # Metadados
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
```

#### 1.2.2 ComplianceAction (Ação de Cumprimento)
```python
class ComplianceAction(models.Model):
    """Registra como um comando judicial foi cumprido"""
    
    # Relacionamento
    judicial_command = models.ForeignKey(
        JudicialCommand, 
        on_delete=models.CASCADE,
        related_name='compliance_actions'
    )
    
    # Tipo de ação realizada
    action_type = models.CharField(max_length=50, choices=[
        ('email_sent', 'Email Enviado'),
        ('document_generated', 'Documento Gerado'),
        ('projudi_click', 'Ação no Projudi'),
        ('manual', 'Cumprimento Manual'),
        ('pending', 'Pendente'),
    ])
    
    # Detalhes da ação
    description = models.TextField()
    steps_performed = models.JSONField()  # Passo a passo executado
    
    # Documentos gerados
    generated_documents = models.JSONField()  # Links/paths de documentos
    
    # Projudi interaction
    projudi_urls_accessed = models.JSONField()
    projudi_buttons_clicked = models.JSONField()
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('completed', 'Concluído'),
        ('partial', 'Parcial'),
        ('failed', 'Falhou'),
        ('pending', 'Pendente'),
    ])
    
    # Observações
    notes = models.TextField(blank=True)
    pending_items = models.JSONField(null=True)
    
    # Vetor para busca de padrões de cumprimento
    embedding = models.VectorField(dimensions=384, null=True)
    
    # Metadados
    performed_by = models.CharField(max_length=200)
    performed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

#### 1.2.3 CompliancePattern (Padrão de Cumprimento - para RAG)
```python
class CompliancePattern(models.Model):
    """Padrões aprendidos de como cumprir tipos de comandos"""
    
    # Identificação do padrão
    pattern_name = models.CharField(max_length=200)
    command_type = models.CharField(max_length=50)
    
    # Descrição do padrão
    description = models.TextField()
    
    # Passos recomendados
    recommended_steps = models.JSONField()
    
    # Templates de documentos
    document_templates = models.JSONField()
    
    # URLs e elementos do Projudi
    projudi_navigation = models.JSONField()  # URLs, seletores, etc.
    
    # Exemplos de sucesso
    success_examples = models.JSONField()  # IDs de ComplianceAction
    
    # Vetor do padrão
    embedding = models.VectorField(dimensions=384)
    
    # Métricas
    usage_count = models.IntegerField(default=0)
    success_rate = models.FloatField(default=0.0)
    
    # Metadados
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
```

### 1.3 Pipeline de Processamento RAG

```python
class JudicialRAGPipeline:
    """Pipeline RAG para recuperação e geração de cumprimentos"""
    
    def __init__(self):
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
        self.llm = None  # Qwen 2.5 quantizado
        
    async def ingest_command(self, command_data: dict):
        """Ingerir novo comando judicial no banco vetorial"""
        
        # 1. Normalizar texto
        normalized = self.normalize_text(command_data['original_text'])
        
        # 2. Gerar embedding
        embedding = self.embedder.encode(normalized)
        
        # 3. Salvar no banco
        command = JudicialCommand.objects.create(
            command_hash=hashlib.sha256(normalized.encode()).hexdigest(),
            original_text=command_data['original_text'],
            normalized_text=normalized,
            embedding=embedding,
            **command_data
        )
        
        return command
    
    async def find_similar_commands(self, query: str, top_k: int = 5):
        """Buscar comandos similares usando busca vetorial"""
        
        query_embedding = self.embedder.encode(query)
        
        # Busca por similaridade cosseno
        similar = JudicialCommand.objects.filter(
            is_active=True
        ).annotate(
            similarity=CosineDistance('embedding', query_embedding)
        ).order_by('similarity')[:top_k]
        
        return similar
    
    async def get_compliance_pattern(self, command_type: str):
        """Obter padrão de cumprimento para tipo de comando"""
        
        patterns = CompliancePattern.objects.filter(
            command_type=command_type,
            is_active=True
        ).order_by('-success_rate', '-usage_count')
        
        return patterns.first()
    
    async def generate_compliance_plan(self, command: JudicialCommand):
        """Gerar plano de cumprimento usando RAG + LLM"""
        
        # 1. Buscar comandos similares já cumpridos
        similar_commands = await self.find_similar_commands(
            command.normalized_text,
            top_k=5
        )
        
        # 2. Buscar padrões de cumprimento
        pattern = await self.get_compliance_pattern(command.command_type)
        
        # 3. Buscar ações de cumprimento bem-sucedidas
        successful_actions = ComplianceAction.objects.filter(
            judicial_command__in=similar_commands,
            status='completed'
        ).order_by('-performed_at')[:3]
        
        # 4. Construir contexto para LLM
        context = {
            'current_command': command,
            'similar_commands': similar_commands,
            'pattern': pattern,
            'successful_actions': successful_actions
        }
        
        # 5. Gerar plano com LLM
        plan = await self.llm_generate_plan(context)
        
        return plan
```

### 1.4 Sistema de Automação Projudi

#### 1.4.1 ProjudiActionExecutor
```python
class ProjudiActionExecutor:
    """Executa ações automatizadas no Projudi"""
    
    def __init__(self, driver):
        self.driver = driver
        self.wait = WebDriverWait(driver, 10)
        
    async def click_intimacao_button(self, process_number: str):
        """Clica no botão de intimação para um processo"""
        
        # 1. Navegar para o processo
        url = f"https://projudi.tjba.jus.br/projudi/DadosProcesso?numeroProcesso={process_number}"
        self.driver.get(url)
        
        # 2. Aguardar carregamento
        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "tabelaLista"))
        )
        
        # 3. Encontrar e clicar no botão de movimentar
        movimentar_btn = self.wait.until(
            EC.element_to_be_clickable((
                By.XPATH, 
                "//a[contains(text(), 'Movimentar Processo')]"
            ))
        )
        movimentar_btn.click()
        
        # 4. Aguardar modal/formulário
        self.wait.until(
            EC.presence_of_element_located((By.ID, "formularioMovimentacao"))
        )
        
        return True
    
    async def attach_document(self, file_path: str, document_type: str):
        """Anexa documento ao processo"""
        
        # 1. Encontrar input de arquivo
        file_input = self.wait.until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "input[type='file']"
            ))
        )
        
        # 2. Enviar arquivo
        file_input.send_keys(file_path)
        
        # 3. Aguardar upload
        self.wait.until(
            EC.presence_of_element_located((
                By.CLASS_NAME,
                "upload-success"
            ))
        )
        
        return True
    
    async def fill_compliance_form(self, form_data: dict):
        """Preenche formulário de cumprimento"""
        
        for field_name, value in form_data.items():
            field = self.wait.until(
                EC.presence_of_element_located((
                    By.NAME,
                    field_name
                ))
            )
            
            if field.tag_name == 'select':
                Select(field).select_by_visible_text(value)
            else:
                field.clear()
                field.send_keys(value)
        
        return True
```

#### 1.4.2 ProjudiNavigationPatterns
```python
class ProjudiNavigationPatterns:
    """Padrões de navegação conhecidos no Projudi"""
    
    PATTERNS = {
        'intimacao_advogado': {
            'url_pattern': '/cadastros/AnalisarMovimentacao',
            'steps': [
                'navigate_to_analise',
                'select_process',
                'click_intimacao',
                'select_advogado',
                'confirm'
            ],
            'selectors': {
                'process_list': 'table.tabelaLista',
                'intimacao_btn': 'a[href*="Intimar"]',
                'confirm_btn': 'input[type="submit"][value="Confirmar"]'
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
                'upload_input': 'input[type="file"]'
            }
        },
        
        'juntada_peticao': {
            'url_pattern': '/listagens/JuntadaPeticao',
            'steps': [
                'navigate_to_peticao',
                'select_process',
                'upload_peticao',
                'confirm_juntada'
            ],
            'selectors': {
                'upload_area': 'div.dropzone',
                'confirm_btn': 'button#confirmarJuntada'
            }
        }
    }
```

## 2. Integração com Django

### 2.1 Estrutura de Apps

```
scsj/
├── core/                    # App principal
│   ├── models.py           # Models base
│   ├── views.py            # Views principais
│   └── urls.py
│
├── judicial_commands/       # App de comandos judiciais
│   ├── models.py           # JudicialCommand, ComplianceAction
│   ├── services.py         # Lógica de negócio
│   ├── rag_pipeline.py     # Pipeline RAG
│   └── tasks.py            # Tasks Celery
│
├── projudi_automation/     # App de automação
│   ├── models.py           # ProjudiSession, ActionLog
│   ├── executor.py         # ProjudiActionExecutor
│   ├── navigator.py        # ProjudiNavigationPatterns
│   ├── session_manager.py  # Gerenciamento de sessão
│   └── tasks.py            # Tasks Celery
│
├── vector_store/           # App de banco vetorial
│   ├── models.py           # Vector models
│   ├── embedder.py         # Geração de embeddings
│   ├── search.py           # Busca vetorial
│   └── migrations/         # Migrações com pgvector
│
└── base/                   # App base compartilhado
    ├── models.py           # Models base (TimeStampedModel)
    ├── middleware.py       # Multi-tenant middleware
    └── utils.py            # Utilitários
```

### 2.2 Configuração pgvector

```python
# vector_store/models.py

from django.contrib.postgres.fields import VectorField
from django.db import models

class BaseVectorModel(models.Model):
    """Model base com campo vetorial"""
    
    embedding = VectorField(dimensions=384, null=True)
    
    class Meta:
        abstract = True

# Migração para habilitar pgvector
# vector_store/migrations/0001_enable_pgvector.py

from django.db import migrations

class Migration(migrations.Migration):
    
    dependencies = []
    
    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql="DROP EXTENSION IF EXISTS vector;"
        ),
    ]
```

### 2.3 Tasks Celery

```python
# judicial_commands/tasks.py

from celery import shared_task
from .rag_pipeline import JudicialRAGPipeline

@shared_task
def ingest_judicial_command(command_data: dict):
    """Ingerir comando judicial async"""
    
    pipeline = JudicialRAGPipeline()
    command = pipeline.ingest_command(command_data)
    
    # Gerar embedding async
    pipeline.generate_embedding.delay(command.id)
    
    return command.id

@shared_task
def find_similar_commands(query: str, top_k: int = 5):
    """Buscar comandos similares async"""
    
    pipeline = JudicialRAGPipeline()
    similar = pipeline.find_similar_commands(query, top_k)
    
    return [
        {
            'id': cmd.id,
            'text': cmd.normalized_text[:200],
            'type': cmd.command_type,
            'similarity': cmd.similarity
        }
        for cmd in similar
    ]

@shared_task
def generate_compliance_plan(command_id: int):
    """Gerar plano de cumprimento async"""
    
    pipeline = JudicialRAGPipeline()
    command = JudicialCommand.objects.get(id=command_id)
    
    plan = pipeline.generate_compliance_plan(command)
    
    return plan

# projudi_automation/tasks.py

@shared_task
def execute_projudi_action(action_type: str, params: dict):
    """Executar ação no Projudi async"""
    
    from .executor import ProjudiActionExecutor
    from .session_manager import get_active_session
    
    session = get_active_session()
    executor = ProjudiActionExecutor(session.driver)
    
    if action_type == 'click_intimacao':
        result = executor.click_intimacao_button(params['process_number'])
    elif action_type == 'attach_document':
        result = executor.attach_document(params['file_path'], params['doc_type'])
    
    return result
```

## 3. Fluxo de Trabalho Completo

### 3.1 Fluxo de Ingestão

```
1. Usuário acessa processo no Projudi
   ↓
2. Sistema extrai dados (BS4/Regex)
   ↓
3. Identifica comandos judiciais (NLP/Regex)
   ↓
4. Gera embeddings (Sentence-BERT)
   ↓
5. Salva no PostgreSQL + pgvector
   ↓
6. Busca padrões similares no banco
   ↓
7. Sugere plano de cumprimento (RAG + LLM)
```

### 3.2 Fluxo de Cumprimento

```
1. Usuário seleciona comando judicial
   ↓
2. Sistema busca padrões de cumprimento (RAG)
   ↓
3. Gera plano de cumprimento (LLM)
   ↓
4. Usuário aprova plano
   ↓
5. Sistema executa ações no Projudi (Selenium)
   ↓
6. Registra ações em ComplianceAction
   ↓
7. Atualiza padrões de sucesso
```

## 4. Próximos Passos

### Fase 1: Infraestrutura (Sprint 1-2)
- [ ] Configurar PostgreSQL com pgvector
- [ ] Criar models Django (JudicialCommand, ComplianceAction)
- [ ] Implementar embedder com Sentence-BERT
- [ ] Criar pipeline de ingestão básico

### Fase 2: RAG Básico (Sprint 3-4)
- [ ] Implementar busca vetorial
- [ ] Integrar Qwen 2.5 local
- [ ] Criar API de geração de planos
- [ ] Testar com dados reais

### Fase 3: Automação Projudi (Sprint 5-6)
- [ ] Refatorar ProjudiActionExecutor
- [ ] Criar biblioteca de padrões de navegação
- [ ] Implementar execução de ações
- [ ] Adicionar logging e retry

### Fase 4: Interface (Sprint 7-8)
- [ ] Dashboard de comandos judiciais
- [ ] Interface de aprovação de planos
- [ ] Visualização de padrões de cumprimento
- [ ] Chat com IA para consultas

### Fase 5: Otimização (Sprint 9-10)
- [ ] Fine-tuning de embeddings
- [ ] Otimização de queries vetoriais
- [ ] Cache de padrões frequentes
- [ ] Monitoramento e métricas

## 5. Tecnologias Recomendadas

| Componente | Tecnologia | Justificativa |
|------------|-----------|---------------|
| Banco Vetorial | PostgreSQL + pgvector | Integração nativa com Django, performance |
| Embeddings | Sentence-BERT (all-MiniLM-L6-v2) | Leve, rápido, boa qualidade |
| LLM Local | Qwen 2.5 3Q quantizado | Conforme especificado, roda local |
| Automação | Selenium + Playwright | Selenium para compatibilidade, Playwright para novos casos |
| Task Queue | Celery + Redis | Já especificado no projeto |
| Framework | Django 6.0+ | Conforme especificado |

## 6. Considerações de Segurança

- Dados sensíveis (CPF, telefone) devem ser criptografados no banco
- Logs não devem conter dados sensíveis em texto puro
- Sessão do Projudi deve ser validada antes de cada ação
- Ações automatizadas devem ter logs detalhados para auditoria
- Implementar rate limiting para evitar bloqueio pelo Projudi
