from django.db import models

from base.models import TimeStampedModel, TenantModel, ActiveModel


class ProjudiSession(TenantModel, TimeStampedModel):
    STATUS_CHOICES = [
        ('active', 'Ativa'),
        ('expired', 'Expirada'),
        ('invalid', 'Inválida'),
    ]

    # Sobrescreve tenant do TenantModel para permitir null
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='projudi_sessions',
        null=True,
        blank=True
    )

    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='projudi_sessions'
    )
    cookies = models.JSONField('Cookies', default=dict)
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default='active')
    last_activity = models.DateTimeField('Última atividade', auto_now=True)
    session_data = models.JSONField('Dados da sessão', default=dict)

    class Meta:
        verbose_name = 'Sessão Projudi'
        verbose_name_plural = 'Sessões Projudi'
        ordering = ['-last_activity']

    def __str__(self):
        return f'Sessão {self.user.email} - {self.status}'

    @property
    def is_valid(self):
        return self.status == 'active'


class Court(TenantModel, TimeStampedModel, ActiveModel):
    name = models.CharField('Nome', max_length=200)
    code = models.CharField('Código', max_length=50, unique=True)
    state = models.CharField('Estado', max_length=2, default='BA')
    projudi_url = models.URLField('URL Projudi', blank=True)

    class Meta:
        verbose_name = 'Tribunal'
        verbose_name_plural = 'Tribunais'
        ordering = ['name']

    def __str__(self):
        return self.name


class Vara(TenantModel, TimeStampedModel, ActiveModel):
    court = models.ForeignKey(
        Court,
        on_delete=models.CASCADE,
        related_name='varas'
    )
    name = models.CharField('Nome', max_length=200)
    code = models.CharField('Código', max_length=50)
    comarca = models.CharField('Comarca', max_length=200)
    address = models.TextField('Endereço', blank=True)
    phone = models.CharField('Telefone', max_length=20, blank=True)
    email = models.EmailField('Email', blank=True)

    class Meta:
        verbose_name = 'Vara'
        verbose_name_plural = 'Varas'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} - {self.comarca}'


class Judge(TenantModel, TimeStampedModel, ActiveModel):
    vara = models.ForeignKey(
        Vara,
        on_delete=models.CASCADE,
        related_name='judges'
    )
    name = models.CharField('Nome', max_length=200)
    email = models.EmailField('Email', blank=True)

    class Meta:
        verbose_name = 'Juiz'
        verbose_name_plural = 'Juízes'
        ordering = ['name']

    def __str__(self):
        return self.name


class OficioRecord(TimeStampedModel):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('enviado', 'Enviado'),
        ('juntado', 'Juntado'),
        ('falhou_email', 'Falha no E-mail'),
        ('falhou_juntada', 'Falha na Juntada'),
        ('ignorado', 'Ignorado'),
        ('dispensado', 'Dispensado'),
    ]

    STATUS_RETORNO_CHOICES = [
        ('sem_retorno', 'Sem Retorno'),
        ('recebido', 'Recebido'),
        ('lido', 'Lido'),
        ('processado', 'Processado'),
        ('pendente_acao', 'Pendente de Ação'),
    ]

    processo = models.CharField('Processo (Interno)', max_length=30, db_index=True)
    numero_processo_cnj = models.CharField('Nº Processo (CNJ)', max_length=25, blank=True, db_index=True)
    numero_oficio = models.CharField('Número Ofício', max_length=50, db_index=True)
    email_destino = models.EmailField('E-mail Destino', blank=True)
    assunto = models.CharField('Assunto', max_length=300, blank=True)
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default='pendente')

    # URLs Projudi
    url_oficio = models.URLField('URL Ofício', blank=True)
    url_processo = models.URLField('URL Processo', blank=True)
    url_recebimento = models.URLField('URL Recebimento', blank=True)
    url_baixa = models.URLField('URL Baixa', blank=True)

    # Dados de envio
    msg_id = models.CharField('Message-ID', max_length=200, blank=True)
    data_envio = models.DateField('Data Envio', null=True, blank=True)
    hora_envio = models.TimeField('Hora Envio', null=True, blank=True)

    # Conteúdo extraído (para exibição e fallback)
    texto_html = models.TextField('HTML Ofício', blank=True)

    # Usuário que executou
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='oficios_executados'
    )

    # Campos de RETORNO (resposta por email)
    status_retorno = models.CharField(
        'Status do Retorno',
        max_length=20,
        choices=STATUS_RETORNO_CHOICES,
        default='sem_retorno'
    )
    data_retorno = models.DateTimeField('Data do Retorno', null=True, blank=True)
    remetente_retorno = models.EmailField('Remetente do Retorno', blank=True)
    assunto_retorno = models.CharField('Assunto do Retorno', max_length=300, blank=True)
    conteudo_retorno = models.TextField('Conteúdo do Retorno', blank=True)
    anexos_retorno = models.JSONField('Anexos do Retorno', default=list, blank=True)
    observacao_retorno = models.TextField('Observação do Retorno', blank=True)

    class Meta:
        verbose_name = 'Ofício'
        verbose_name_plural = 'Ofícios'
        ordering = ['-created_at']
        unique_together = ['processo', 'numero_oficio']

    def __str__(self):
        return f'{self.numero_oficio} — {self.processo}'

    @property
    def enviado(self):
        return self.status in ('enviado', 'juntado')

    @property
    def juntado(self):
        return self.status == 'juntado'

    @property
    def pode_enviar(self):
        return self.status in ('pendente', 'falhou_email', 'falhou_juntada')

    @property
    def dispensado(self):
        return self.status == 'dispensado'

    @property
    def tem_retorno(self):
        return self.status_retorno != 'sem_retorno'


class OficioLog(TimeStampedModel):
    TIPO_CHOICES = [
        ('info', 'Info'),
        ('envio', 'Envio'),
        ('juntada', 'Juntada'),
        ('erro_email', 'Erro E-mail'),
        ('erro_juntada', 'Erro Juntada'),
        ('resposta', 'Resposta Recebida'),
        ('resumo', 'Resumo IA'),
    ]

    oficio = models.ForeignKey(
        OficioRecord,
        on_delete=models.CASCADE,
        related_name='logs',
        null=True, blank=True,
    )
    tipo = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES, default='info')
    mensagem = models.TextField('Mensagem')
    detalhes = models.JSONField('Detalhes', default=dict, blank=True)

    class Meta:
        verbose_name = 'Log de Ofício'
        verbose_name_plural = 'Logs de Ofícios'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.tipo}] {self.oficio.numero_oficio}'


class MandadoRecord(TimeStampedModel):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('expedido', 'Expedido'),
        ('juntado', 'Juntado'),
        ('falha', 'Falha'),
        ('dispensado', 'Dispensado'),
    ]

    processo = models.CharField('Processo (Interno)', max_length=30, db_index=True)
    numero_processo_cnj = models.CharField('Nº Processo (CNJ)', max_length=25, blank=True, db_index=True)
    numero_mandado = models.CharField('Número Mandado', max_length=50, db_index=True)
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default='pendente')

    # URLs Projudi
    url_mandado = models.URLField('URL Mandado', blank=True)
    url_processo = models.URLField('URL Processo', blank=True)

    # Conteúdo extraído
    parte_nome = models.CharField('Nome da Parte', max_length=200, blank=True)
    texto_html = models.TextField('HTML Mandado', blank=True)

    # Usuário que executou
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='mandados_executados'
    )

    class Meta:
        verbose_name = 'Mandado'
        verbose_name_plural = 'Mandados'
        ordering = ['-created_at']
        unique_together = ['processo', 'numero_mandado']

    def __str__(self):
        return f'{self.numero_mandado} — {self.processo}'

    @property
    def expedido(self):
        return self.status in ('expedido', 'juntado')

    @property
    def juntado(self):
        return self.status == 'juntado'

    @property
    def pode_expedir(self):
        return self.status in ('pendente', 'falha')

    @property
    def dispensado(self):
        return self.status == 'dispensado'


class MandadoLog(TimeStampedModel):
    TIPO_CHOICES = [
        ('info', 'Info'),
        ('expedicao', 'Expedição'),
        ('juntada', 'Juntada'),
        ('erro', 'Erro'),
    ]

    mandado = models.ForeignKey(
        MandadoRecord,
        on_delete=models.CASCADE,
        related_name='logs',
        null=True, blank=True,
    )
    tipo = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES, default='info')
    mensagem = models.TextField('Mensagem')
    detalhes = models.JSONField('Detalhes', default=dict, blank=True)

    class Meta:
        verbose_name = 'Log de Mandado'
        verbose_name_plural = 'Logs de Mandados'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.tipo}] {self.mandado.numero_mandado if self.mandado else "?"}'
