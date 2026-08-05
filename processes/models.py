from django.db import models

from base.models import TimeStampedModel, TenantModel, ActiveModel
from base.utils import mask_cpf, mask_phone


class Process(TenantModel, TimeStampedModel, ActiveModel):
    STATUS_CHOICES = [
        ('distributed', 'Distribuído'),
        ('analyzing', 'Em Análise'),
        ('pending_compliance', 'Aguardando Cumprimento'),
        ('complied', 'Cumprido'),
        ('document_sent', 'Ofício Expedido'),
        ('closed', 'Encerrado'),
    ]

    number = models.CharField('Número', max_length=50)
    number_normalized = models.CharField('Número Normalizado', max_length=50)
    status = models.CharField('Status', max_length=30, choices=STATUS_CHOICES, default='distributed')
    vara = models.ForeignKey(
        'projudi.Vara',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processes'
    )
    court = models.ForeignKey(
        'projudi.Court',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processes'
    )
    judge = models.ForeignKey(
        'projudi.Judge',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processes'
    )
    class_processual = models.CharField('Classe Processual', max_length=100, blank=True)
    subject = models.CharField('Assunto', max_length=300, blank=True)
    value = models.DecimalField('Valor da causa', max_digits=15, decimal_places=2, null=True, blank=True)
    distribution_date = models.DateField('Data de distribuição', null=True, blank=True)
    ai_summary = models.TextField('Resumo IA', blank=True)
    projudi_url = models.URLField('URL Projudi', max_length=500, blank=True)
    assigned_to = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_processes'
    )

    class Meta:
        verbose_name = 'Processo'
        verbose_name_plural = 'Processos'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['number']),
            models.Index(fields=['number_normalized']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        from base.utils import normalize_process_number
        if not self.number_normalized:
            self.number_normalized = normalize_process_number(self.number)
        super().save(*args, **kwargs)


class Party(TenantModel, TimeStampedModel, ActiveModel):
    ROLE_CHOICES = [
        ('autor', 'Autor'),
        ('reu', 'Réu'),
        ('exequente', 'Exequente'),
        ('executado', 'Executado'),
        ('terceiro', 'Terceiro Interessado'),
    ]

    process = models.ForeignKey(
        Process,
        on_delete=models.CASCADE,
        related_name='parties'
    )
    name = models.CharField('Nome', max_length=200)
    name_normalized = models.CharField('Nome Normalizado', max_length=200, blank=True)
    role = models.CharField('Papel', max_length=20, choices=ROLE_CHOICES)
    cpf_cnpj = models.CharField('CPF/CNPJ', max_length=18, blank=True)
    cpf_cnpj_encrypted = models.CharField('CPF/CNPJ Criptografado', max_length=200, blank=True)
    email = models.EmailField('Email', blank=True)
    phone = models.CharField('Telefone', max_length=20, blank=True)
    rg = models.CharField('RG', max_length=30, blank=True)
    rg_encrypted = models.CharField('RG Criptografado', max_length=200, blank=True)
    nome_pai = models.CharField('Nome do Pai', max_length=200, blank=True)
    nome_mae = models.CharField('Nome da Mãe', max_length=200, blank=True)
    address = models.TextField('Endereço', blank=True)
    has_lawyer = models.BooleanField('Tem advogado', default=False)
    lawyer_name = models.CharField('Advogado', max_length=200, blank=True)
    receives_email_intimation = models.BooleanField('Recebe intimação por email', default=False)
    has_domicilio_cnj = models.BooleanField('Domicílio CNJ', default=False)
    is_revel = models.BooleanField('Revel', default=False)

    class Meta:
        verbose_name = 'Parte'
        verbose_name_plural = 'Partes'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def masked_cpf(self):
        return mask_cpf(self.cpf_cnpj)

    @property
    def masked_phone(self):
        return mask_phone(self.phone)

    @property
    def is_author_side(self):
        return self.role in ['autor', 'exequente']

    @property
    def is_defendant_side(self):
        return self.role in ['reu', 'executado']


class Movement(TenantModel, TimeStampedModel):
    CATEGORY_CHOICES = [
        ('citacao', 'Citação'),
        ('intimacao', 'Intimação'),
        ('audiencia', 'Audiência'),
        ('sentenca', 'Sentença'),
        ('despacho', 'Despacho'),
        ('decisao', 'Decisão'),
        ('peticao', 'Petição'),
        ('certidao', 'Certidão'),
        ('ato_ordinatorio', 'Ato Ordinatório'),
        ('recurso', 'Recurso'),
        ('outro', 'Outro'),
    ]

    COMMUNICATION_STATUS_CHOICES = [
        ('expedida', 'Expedida'),
        ('lida', 'Lida'),
        ('realizada', 'Realizada'),
        ('pendente', 'Pendente'),
    ]

    COMMUNICATION_MEANS_CHOICES = [
        ('domicilio_cnj', 'Domicílio CNJ'),
        ('mandado', 'Mandado'),
        ('ar', 'Aviso de Recebimento'),
        ('precatoria', 'Precatória'),
        ('email', 'Email'),
        ('outro', 'Outro'),
    ]

    process = models.ForeignKey(
        Process,
        on_delete=models.CASCADE,
        related_name='movements'
    )
    event_number = models.CharField('Evento', max_length=20)
    act_description = models.TextField('Descrição do Ato')
    act_normalized = models.TextField('Ato Normalizado', blank=True)
    category = models.CharField('Categoria', max_length=30, choices=CATEGORY_CHOICES, blank=True)
    act_date = models.DateField('Data do Ato', null=True, blank=True)
    reading_date = models.DateField('Data de Leitura', null=True, blank=True)
    reference_date = models.DateField('Data de Referência', null=True, blank=True)
    author = models.CharField('Autor', max_length=200, blank=True)
    communication_status = models.CharField(
        'Status Comunicação',
        max_length=20,
        choices=COMMUNICATION_STATUS_CHOICES,
        blank=True
    )
    communication_means = models.CharField(
        'Meio de Comunicação',
        max_length=20,
        choices=COMMUNICATION_MEANS_CHOICES,
        blank=True
    )
    recipient = models.CharField('Destinatário', max_length=200, blank=True)
    observation = models.TextField('Observação', blank=True)
    deadline_days = models.IntegerField('Prazo (dias)', null=True, blank=True)
    deadline_date = models.DateField('Data do Prazo', null=True, blank=True)
    referenced_event = models.CharField('Evento Referenciado', max_length=200, blank=True)
    referenced_event_obj = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referenced_by',
        verbose_name='Movimentação Referenciada'
    )
    document_url = models.URLField('URL Documento', max_length=500, blank=True)

    class Meta:
        verbose_name = 'Movimentação'
        verbose_name_plural = 'Movimentações'
        ordering = ['-act_date', '-event_number']
        indexes = [
            models.Index(fields=['process', 'event_number']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f'Evento {self.event_number} - {self.process.number}'


class Deadline(TenantModel, TimeStampedModel):
    STATUS_CHOICES = [
        ('pending', 'Pendente'),
        ('completed', 'Concluído'),
        ('expired', 'Expirado'),
    ]

    TYPE_CHOICES = [
        ('prescricao', 'Prescrição'),
        ('decadencia', 'Decadência'),
        ('audiencia', 'Audiência'),
        ('recurso', 'Prazo Recursal'),
        ('intimacao', 'Intimação'),
        ('outro', 'Outro'),
    ]

    process = models.ForeignKey(
        Process,
        on_delete=models.CASCADE,
        related_name='deadlines'
    )
    movement = models.ForeignKey(
        Movement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deadlines'
    )
    type = models.CharField('Tipo', max_length=20, choices=TYPE_CHOICES)
    description = models.TextField('Descrição')
    due_date = models.DateField('Data de Vencimento')
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default='pending')
    assigned_to = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_deadlines'
    )

    class Meta:
        verbose_name = 'Prazo'
        verbose_name_plural = 'Prazos'
        ordering = ['due_date']

    def __str__(self):
        return f'{self.get_type_display()} - {self.process.number}'


class MovementCommand(TimeStampedModel):
    """
    Comando extraido de uma movimentacao (resultado do transforma_texto_dict).
    Um comando = um ato cumprivel dentro de uma movimentacao.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='movement_commands'
    )
    movement = models.ForeignKey(
        Movement,
        on_delete=models.CASCADE,
        related_name='commands'
    )
    act_verb = models.CharField('Ato', max_length=50)  # intime-se, expeca-se...
    is_completable = models.BooleanField('Cumprivel', default=False)
    recipient = models.JSONField('Destinatarios', default=list)
    means = models.JSONField('Meios', default=list)
    objective = models.JSONField('Objetivos', default=list)
    deadline = models.JSONField('Prazos', default=list)
    conditions = models.JSONField('Condicoes', default=list)
    snippet = models.TextField('Trecho', blank=True)
    has_costs = models.BooleanField('Tem custas', default=False)
    costs_text = models.TextField('Texto custas', blank=True)
    extracted_at = models.DateTimeField('Extraido em', auto_now_add=True)

    class Meta:
        verbose_name = 'Comando de Movimentacao'
        verbose_name_plural = 'Comandos de Movimentacoes'
        ordering = ['-extracted_at']

    def __str__(self):
        return f'{self.act_verb} - {self.movement.process.number}'


class CommunicationTracking(TimeStampedModel):
    """
    Rastreamento de comunicacoes expedidas x lidas/devolvidas.
    Uma linha = uma comunicacao completa (expedicao + retorno).
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='communication_trackings'
    )
    process = models.ForeignKey(
        Process,
        on_delete=models.CASCADE,
        related_name='communications'
    )
    TYPE_CHOICES = [
        ('intimacao', 'Intimacao'),
        ('citacao', 'Citacao'),
        ('mandado', 'Mandado'),
        ('certidao', 'Certidao'),
        ('ar', 'Aviso de Recebimento'),
        ('oficio', 'Oficio'),
        ('outro', 'Outro'),
    ]
    type = models.CharField('Tipo', max_length=20, choices=TYPE_CHOICES)

    # Expedicao
    event_expedido = models.CharField('Evento Expedido', max_length=10)
    date_expedido = models.DateField('Data Expedicao')
    act_expedido = models.TextField('Ato Expedido')
    recipient = models.CharField('Destinatario', max_length=300)
    means = models.CharField('Meio', max_length=30, blank=True)

    # Retorno / Leitura
    event_lido = models.CharField('Evento Lido', max_length=10, blank=True)
    date_lido = models.DateField('Data Leitura', null=True, blank=True)
    STATUS_CHOICES = [
        ('lida', 'Lida'),
        ('devolvida_sem_leitura', 'Devolvida sem leitura'),
        ('ar_juntado', 'AR juntado'),
        ('mandado_devolvido', 'Mandado devolvido'),
        ('mandado_assinado', 'Mandado assinado'),
        ('pendente', 'Pendente'),
    ]
    status = models.CharField('Status', max_length=30, choices=STATUS_CHOICES, default='pendente')
    deadline_days = models.IntegerField('Prazo (dias)', null=True, blank=True)
    deadline_expired = models.BooleanField('Prazo vencido', default=False)

    class Meta:
        verbose_name = 'Rastreamento de Comunicacao'
        verbose_name_plural = 'Rastreamentos de Comunicacoes'
        ordering = ['-date_expedido']
        indexes = [
            models.Index(fields=['process', 'event_expedido']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.type} - {self.recipient[:40]}'


class ComplianceHistory(TimeStampedModel):
    """
    Memoria de cumprimentos realizados - base para RAG futuro.
    Quando o sistema cumpre uma movimentacao, salva aqui.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='compliance_histories'
    )
    process = models.ForeignKey(
        Process,
        on_delete=models.CASCADE,
        related_name='compliances'
    )
    movement = models.ForeignKey(
        Movement,
        on_delete=models.CASCADE,
        related_name='compliance_history',
        null=True,
        blank=True
    )
    act_type = models.CharField('Tipo Ato', max_length=50)
    act_verb = models.CharField('Verbo', max_length=50)
    recipient = models.CharField('Destinatario', max_length=300)
    means_used = models.CharField('Meio Utilizado', max_length=50)
    full_text = models.TextField('Texto Completo')
    commands_json = models.JSONField('Comandos JSON', default=dict)
    email_sent = models.BooleanField('Email Enviado', default=False)
    email_to = models.EmailField('Email Destino', blank=True)
    juntada_done = models.BooleanField('Juntada Realizada', default=False)
    compliance_date = models.DateTimeField('Data Cumprimento', auto_now_add=True)
    active = models.BooleanField('Ativo p/ RAG', default=True,
        help_text='Usar este registro como exemplo nas buscas RAG')
    embedding = models.JSONField('Embedding', null=True, blank=True)

    class Meta:
        verbose_name = 'Cumprimento Historico'
        verbose_name_plural = 'Cumprimentos Historicos'
        ordering = ['-compliance_date']
        indexes = [
            models.Index(fields=['process', 'act_type']),
            models.Index(fields=['means_used']),
        ]

    def __str__(self):
        return f'{self.act_verb} - {self.process.number}'


class ProcessSummary(TimeStampedModel):
    """
    Resumo processado de um processo apos analise completa.
    Status de automatizacao e canais disponiveis.
    """
    process = models.OneToOneField(
        Process,
        on_delete=models.CASCADE,
        related_name='summary'
    )
    is_automatable = models.BooleanField('Automatizavel', default=False)
    automation_status = models.CharField('Status Automacao', max_length=30, default='nao_analisado')
    total_movements = models.IntegerField('Total Movimentacoes', default=0)
    total_commands = models.IntegerField('Total Comandos', default=0)
    completable_commands = models.IntegerField('Comandos Cumpriveis', default=0)
    tracked_communications = models.IntegerField('Comunicacoes Rastreadas', default=0)
    pending_deadlines = models.IntegerField('Prazos Pendentes', default=0)
    last_analysis = models.DateTimeField('Ultima Analise', null=True, blank=True)

    # Canais disponiveis (resumo)
    has_advogado = models.BooleanField('Tem Advogado', default=False)
    has_domicilio_cnj = models.BooleanField('Domicilio CNJ', default=False)
    has_email = models.BooleanField('Email', default=False)
    channels_summary = models.JSONField('Resumo Canais', default=dict)

    class Meta:
        verbose_name = 'Resumo do Processo'
        verbose_name_plural = 'Resumos dos Processos'

    def __str__(self):
        return f'{self.process.number} - {self.automation_status}'


class RAGExample(TimeStampedModel):
    """
    Par despacho + cumprimentos de Ivan para curadoria e busca RAG.
    Preserva o texto do juiz e os atos mesmo se o Projudi cair.
    """
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='rag_examples'
    )
    process = models.ForeignKey(
        Process, on_delete=models.CASCADE,
        related_name='rag_examples'
    )
    oficio = models.CharField('Oficio', max_length=50, blank=True)
    despacho_ato = models.TextField('Decisao do Juiz')
    despacho_observacao = models.TextField('Observacao do Despacho', blank=True,
        help_text='Texto completo da decisao/juntada do juiz')
    despacho_data = models.CharField('Data Despacho', max_length=20, blank=True)
    despacho_autor = models.CharField('Juiz', max_length=200, blank=True)
    evento_despacho = models.CharField('Evento Despacho', max_length=20, blank=True)
    cumprimentos = models.JSONField('Atos de Cumprimento', default=list, blank=True,
        help_text='Lista de dicts com ato, observacao, data, autor, tipo')
    documentos = models.JSONField('Documentos do Despacho', default=list, blank=True,
        help_text='Links para documentos/downloads do despacho')
    active = models.BooleanField('Ativo p/ RAG', default=True,
        help_text='Usar como exemplo nas buscas')

    sequencia_cumprimento = models.JSONField(
        'Sequência de Execução', default=list, blank=True,
        help_text=(
            'Lista ORDENADA de atos a executar quando este RAGExample '
            'for match. Cada item da lista é um dict:\n'
            '- {"tipo": "movimentacao", "observacao": "texto..."}\n'
            '  + campos opcionais: "codigo_mov": "581", '
            '"descricao_mov": "Intimação"\n'
            '- {"tipo": "mandado", "template_id": 12}\n'
            '  + campo opcional: "subtipo": "11"\n'
            '    (1=Citação+Int.Audiência, 2=Int.Audiência, '
            '3=Intimação, 4=Citação, 5=Int.Despacho, '
            '6=Int.Sentença, 11=Citação/Penhora/Avaliação, '
            '26=Penhora, 27=Reintegração)\n'
            '- {"tipo": "oficio", "template_id": 7}\n'
            '- {"tipo": "intimacao", "template_id": 5}\n'
            'A ordem da lista define a sequência de execução. '
            'Para movimentações, a "observacao" é o texto que será '
            'registrado no Projudi via Mov581, e "codigo_mov"/'
            '"descricao_mov" definem o tipo de movimentação no Projudi '
            '(padrão: 581 / "Cumprimento de Decisão").'
        )
    )

    class Meta:
        verbose_name = 'Exemplo RAG'
        verbose_name_plural = 'Exemplos RAG'
        ordering = ['-created_at']

    suggested_templates = models.ManyToManyField(
        'DocumentTemplate', blank=True,
        related_name='rag_examples',
        help_text='Modelos de documento sugeridos para esta decisao'
    )

    def save(self, *args, **kwargs):
        # JSONFields com blank=True viram None quando salvos vazios pelo
        # form do admin (não []), violando NOT NULL. Normaliza antes de
        # salvar — cobre admin, scripts e qualquer outro caminho.
        if self.cumprimentos is None:
            self.cumprimentos = []
        if self.documentos is None:
            self.documentos = []
        if self.sequencia_cumprimento is None:
            self.sequencia_cumprimento = []
        super().save(*args, **kwargs)

    def get_template_context(self, parte_id=None):
        """Retorna dict com dados do processo + partes para preencher template.
        Se parte_id for passado, retorna apenas aquela parte em 'parte' e 'partes' com 1 item.
        """
        qs = self.process.parties.all()
        if parte_id:
            qs = qs.filter(pk=parte_id)

        cumprimentos = self.cumprimentos or []

        ctx = {
            'processo': self.process.number,
            'despacho_ato': self.despacho_ato,
            'despacho_observacao': self.despacho_observacao,
            'despacho_data': self.despacho_data,
            'despacho_autor': self.despacho_autor,
            'partes': [
                {
                    'nome': p.name,
                    'papel': p.get_role_display(),
                    'cpf_cnpj': p.cpf_cnpj,
                    'rg': p.rg,
                    'nome_pai': p.nome_pai,
                    'nome_mae': p.nome_mae,
                    'email': p.email,
                    'telefone': p.phone,
                    'endereco': p.address,
                    'advogado': p.lawyer_name,
                }
                for p in qs
            ],
            'cumprimentos': cumprimentos,
        }
        if cumprimentos:
            ctx['cumprimento'] = cumprimentos[0]
            ctx['cumprimento_ato'] = cumprimentos[0].get('ato', '')
            ctx['cumprimento_observacao'] = cumprimentos[0].get('observacao', '')
            ctx['cumprimento_data'] = cumprimentos[0].get('data', '')
            ctx['cumprimento_autor'] = cumprimentos[0].get('autor', '')
            ctx['cumprimento_tipo'] = cumprimentos[0].get('tipo', '')
        if parte_id and ctx['partes']:
            ctx['parte'] = ctx['partes'][0]
        return ctx

    def __str__(self):
        return f'{self.process.number} - despacho #{self.evento_despacho}'


class DocumentTemplate(TimeStampedModel):
    TEMPLATE_TYPES = [
        ('mandado', 'Mandado'),
        ('oficio', 'Ofício'),
        ('intimacao', 'Intimação'),
        ('certidao', 'Certidão'),
        ('outro', 'Outro'),
    ]

    name = models.CharField('Nome do Modelo', max_length=200)
    template_type = models.CharField('Tipo', max_length=20, choices=TEMPLATE_TYPES, default='outro')
    description = models.TextField('Descrição', blank=True,
        help_text='Quando usar este modelo? Ex: "Para ofícios ao banco com decisão de força de mandado"')
    html_template = models.TextField('Template HTML',
        help_text='HTML com placeholders {{ parte.nome }}, {{ processo }}, {{ despacho_observacao }}, etc.')
    active = models.BooleanField('Ativo', default=True)

    class Meta:
        verbose_name = 'Modelo de Documento'
        verbose_name_plural = 'Modelos de Documento'
        ordering = ['name']

    def __str__(self):
        return self.name

    def render(self, context: dict) -> str:
        """Preenche o template com os dados do contexto e retorna HTML pronto."""
        from django.template import Template, Context
        tpl = Template(self.html_template)
        return tpl.render(Context(context))


class GeneratedDocument(TimeStampedModel):
    tenant = models.ForeignKey(
        'accounts.Tenant', on_delete=models.CASCADE,
        null=True, blank=True, related_name='generated_documents'
    )
    process = models.ForeignKey(
        Process, on_delete=models.CASCADE, related_name='generated_documents'
    )
    rag_example = models.ForeignKey(
        RAGExample, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_documents'
    )
    template = models.ForeignKey(
        DocumentTemplate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_documents'
    )
    sequential_number = models.IntegerField('Número Sequencial', default=0)
    year = models.IntegerField('Ano', default=0)
    recipient_name = models.CharField('Destinatário', max_length=300, blank=True)
    recipient_email = models.CharField('Email', max_length=200, blank=True)
    html_content = models.TextField('HTML Gerado', blank=True)
    exported_to_projudi = models.BooleanField('Exportado ao Projudi', default=False)

    class Meta:
        verbose_name = 'Documento Gerado'
        verbose_name_plural = 'Documentos Gerados'
        ordering = ['-year', '-sequential_number']
        unique_together = [('template', 'year', 'sequential_number')]

    def __str__(self):
        return f'{self.template.name if self.template else "Documento"} Nº {self.sequential_number:03d}/{self.year}'

    @classmethod
    def proximo_numero(cls, template, year=None):
        from datetime import date
        year = year or date.today().year
        ultimo = cls.objects.filter(template=template, year=year).order_by('-sequential_number').first()
        return (ultimo.sequential_number + 1) if ultimo else 1
