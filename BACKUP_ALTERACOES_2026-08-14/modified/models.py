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


class CumprimentoRecord(TimeStampedModel):
    """Registro de cumprimento de ato de secretaria (não mandado/ofício).

    Análogo a MandadoRecord / OficioRecord, mas para fluxos como:
    - eletronico (DJEN)
    - advogado (intimação ao advogado)
    - email / email_condicional
    - ar (Aviso de Recebimento)
    - mandado_precatorio
    - edital
    - movimentacao_simples (certidões internas)
    """

    FLUXO_CHOICES = [
        ('eletronico', 'Eletrônico (DJEN)'),
        ('advogado', 'Advogado Constituído'),
        ('email', 'E-mail'),
        ('email_condicional', 'E-mail Condicional'),
        ('ar', 'Aviso de Recebimento'),
        ('mandado', 'Mandado'),
        ('mandado_precatorio', 'Mandado Prec.'),
        ('edital', 'Edital'),
        ('movimentacao_simples', 'Movimentação Simples'),
    ]

    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('processando', 'Processando'),
        ('cumprido', 'Cumprido'),
        ('falha', 'Falha'),
        ('dispensado', 'Dispensado'),
    ]

    processo = models.CharField('Processo (Interno)', max_length=30, db_index=True)
    numero_processo_cnj = models.CharField('Nº Processo (CNJ)', max_length=25, blank=True, db_index=True)

    # Fluxo escolhido pelo FluxoDecisor
    fluxo = models.CharField('Fluxo', max_length=25, choices=FLUXO_CHOICES)
    fluxo_justificativa = models.TextField('Justificativa do Fluxo', blank=True)

    # Dados da decisão
    parte_nome = models.CharField('Nome da Parte', max_length=200, blank=True)
    parte_papel = models.CharField('Papel da Parte', max_length=20, blank=True)
    endereco_analisado = models.JSONField('Endereço Analisado', default=dict, blank=True)

    # Comando / ato de origem
    act_verb = models.CharField('Ato', max_length=50, blank=True)
    snippet = models.TextField('Trecho da Decisão', blank=True)

    # Template/Documento gerado
    template_used = models.ForeignKey(
        'processes.DocumentTemplate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cumprimentos'
    )
    rag_example = models.ForeignKey(
        'processes.RAGExample',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cumprimentos_gerados'
    )
    texto_html = models.TextField('HTML Gerado', blank=True)

    # ── Análise de prazo (observação / certidão controladas por JSON) ──
    prazo_info = models.JSONField(
        'Análise de Prazo (JSON)',
        default=dict, blank=True,
        help_text='Resultado serializável do PrazoService '
                  '(último dia, decurso, dias contados/excluídos, modo, djen).',
    )
    observacao_prazo = models.TextField(
        'Observação de Prazo', blank=True,
        help_text='Texto controlado gerado a partir de prazo_info, '
                  'usado na observação do Mov581 e/ou na certidão.',
    )

    # URLs Projudi
    url_processo = models.URLField('URL Processo', max_length=500, blank=True)
    url_movimentacao = models.URLField('URL Movimentação', max_length=500, blank=True)

    # Status
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default='pendente')

    # Usuário que executou
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cumprimentos_executados'
    )

    class Meta:
        verbose_name = 'Cumprimento'
        verbose_name_plural = 'Cumprimentos'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_fluxo_display()} — {self.processo}'

    @property
    def cumprido(self):
        return self.status == 'cumprido'

    @property
    def pode_executar(self):
        return self.status in ('pendente', 'falha')

    @property
    def dispensado(self):
        return self.status == 'dispensado'


class CumprimentoLog(TimeStampedModel):
    TIPO_CHOICES = [
        ('info', 'Info'),
        ('decisao', 'Decisão'),
        ('execucao', 'Execução'),
        ('erro', 'Erro'),
    ]

    cumprimento = models.ForeignKey(
        CumprimentoRecord,
        on_delete=models.CASCADE,
        related_name='logs',
        null=True, blank=True,
    )
    tipo = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES, default='info')
    mensagem = models.TextField('Mensagem')
    detalhes = models.JSONField('Detalhes', default=dict, blank=True)

    class Meta:
        verbose_name = 'Log de Cumprimento'
        verbose_name_plural = 'Logs de Cumprimentos'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.tipo}] {self.cumprimento_id}'


class MovimentacaoRecord(TimeStampedModel):
    """Registro de movimentação interna no Projudi (Mov581).

    Análogo a MandadoRecord / OficioRecord, mas para atos que
    não geram documento — apenas registram o cumprimento via Mov581.
    """

    CATEGORIA_CHOICES = [
        ('certidao', 'Certidão'),
        ('intimacao', 'Intimação'),
        ('arquivamento', 'Arquivamento'),
        ('publicacao', 'Publicação'),
        ('registro', 'Registro'),
        ('outro', 'Outro'),
    ]

    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('processando', 'Processando'),
        ('cumprido', 'Cumprido'),
        ('falha', 'Falha'),
        ('dispensado', 'Dispensado'),
    ]

    processo = models.CharField('Processo (Interno)', max_length=30, db_index=True)
    numero_processo_cnj = models.CharField('Nº Processo (CNJ)', max_length=25, blank=True, db_index=True)

    # Dados do ato
    act_verb = models.CharField('Ato', max_length=50, blank=True,
        help_text='Ex: certifique-se, arquive-se, publique-se, registre-se')
    categoria = models.CharField('Categoria', max_length=20,
        choices=CATEGORIA_CHOICES, default='outro')
    observacao = models.TextField('Observação', blank=True,
        help_text='Texto a ser registrado como observação da movimentação')

    # Código e descrição da movimentação no Projudi (seqCategoriaMovimentacao)
    codigo_movimentacao = models.CharField(
        'Código Mov.', max_length=10, default='581',
        help_text='Código da categoria no Projudi (ex: 581 = TD - Tipo Documental)')
    descricao_movimentacao = models.CharField(
        'Descrição Mov.', max_length=100, default='Cumprimento de Decisão',
        help_text='Descrição que aparece no campo descCategoriaMovimentacao do Projudi')

    # Parte (se o ato tiver um destinatário)
    parte_nome = models.CharField('Nome da Parte', max_length=200, blank=True)
    parte_papel = models.CharField('Papel da Parte', max_length=20, blank=True)

    # Origem (RAG + template)
    rag_example = models.ForeignKey(
        'processes.RAGExample',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='movimentacoes_geradas'
    )
    template_used = models.ForeignKey(
        'processes.DocumentTemplate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='movimentacoes'
    )

    # URLs
    url_processo = models.URLField('URL Processo', max_length=500, blank=True)
    url_movimentacao = models.URLField('URL Movimentação', max_length=500, blank=True)

    # Localizador
    localizador = models.CharField('Localizador', max_length=20, blank=True,
        help_text='Código do localizador (ex: 1, 2, 3...)')
    tipo_localizador = models.CharField('Tipo Localizador', max_length=20, blank=True,
        help_text='Tipo de localizador (ex: 1=Cartório, 2=Físico...)')

    # Status
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default='pendente')

    # Usuário que executou
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='movimentacoes_executadas'
    )

    class Meta:
        verbose_name = 'Movimentação'
        verbose_name_plural = 'Movimentações'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.act_verb or self.get_categoria_display()} — {self.processo}'

    @property
    def cumprido(self):
        return self.status == 'cumprido'

    @property
    def pode_executar(self):
        return self.status in ('pendente', 'falha')

    @property
    def dispensado(self):
        return self.status == 'dispensado'


class MovimentacaoLog(TimeStampedModel):
    TIPO_CHOICES = [
        ('info', 'Info'),
        ('execucao', 'Execução'),
        ('erro', 'Erro'),
    ]

    movimentacao = models.ForeignKey(
        MovimentacaoRecord,
        on_delete=models.CASCADE,
        related_name='logs',
        null=True, blank=True,
    )
    tipo = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES, default='info')
    mensagem = models.TextField('Mensagem')
    detalhes = models.JSONField('Detalhes', default=dict, blank=True)

    class Meta:
        verbose_name = 'Log de Movimentação'
        verbose_name_plural = 'Logs de Movimentações'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.tipo}] {self.movimentacao_id}'


class Feriado(TenantModel, TimeStampedModel, ActiveModel):
    """Feriado ou data especial que NÃO conta como dia útil.

    Usado pelo PrazoService para excluir dias do cômputo de prazos.

    Tipos:
      - fixo: recorre todo ano (só mês/dia importam; o ano é ignorado
        na comparação). Ex: 01/01, 25/12.
      - unico: data pontual (exige ano). Ex: carnaval 04/03/2025.
      - movel: data pontual computada por regra (exige ano). Ex: Sexta
        Santa, Corpus Christi. O campo 'ano' marca em qual ano vale,
        pois a data muda a cada ano.

    'escopo' controla a abrangência: nacional, estadual (BA),
    comarca ou vara específica. Suspensões de âmbito menor (comarca/vara)
    são filtradas por Court/Vara quando o chamador as informa.
    """

    TIPO_CHOICES = [
        ('fixo', 'Fixo (todo ano)'),
        ('unico', 'Data única (ano específico)'),
        ('movel', 'Móvel (data calculada por ano)'),
    ]
    ESCOPO_CHOICES = [
        ('nacional', 'Nacional'),
        ('estadual', 'Estadual (BA)'),
        ('comarca', 'Comarca'),
        ('vara', 'Vara específica'),
    ]

    nome = models.CharField('Nome', max_length=120,
        help_text='Ex: Confraternização Universal, Carnaval, Sexta Santa')
    tipo = models.CharField('Tipo', max_length=10, choices=TIPO_CHOICES,
        default='fixo')
    escopo = models.CharField('Escopo', max_length=10,
        choices=ESCOPO_CHOICES, default='nacional')
    data = models.DateField('Data', null=True, blank=True,
        help_text='Obrigatória p/ tipos "unico" e "movel". Ignorada em "fixo".')
    mes = models.PositiveSmallIntegerField('Mês', null=True, blank=True,
        help_text='Obrigatório p/ "fixo" (1-12).')
    dia = models.PositiveSmallIntegerField('Dia', null=True, blank=True,
        help_text='Obrigatório p/ "fixo" (1-31).')

    # Filtros de escopo estreito (opcionais)
    court = models.ForeignKey(
        'projudi.Court', on_delete=models.CASCADE,
        null=True, blank=True, related_name='feriados',
        help_text='Usar p/ escopo=estadual/comarca/vara.')
    vara = models.ForeignKey(
        'projudi.Vara', on_delete=models.CASCADE,
        null=True, blank=True, related_name='feriados',
        help_text='Usar p/ escopo=vara.')

    observacao = models.TextField('Observação', blank=True)

    class Meta:
        verbose_name = 'Feriado'
        verbose_name_plural = 'Feriados'
        ordering = ['tipo', 'mes', 'dia', 'data']

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.tipo == 'fixo':
            if not (self.mes and self.dia):
                raise ValidationError(
                    'Feriado fixo exige mês e dia.')
        else:
            if not self.data:
                raise ValidationError(
                    'Feriado único/móvel exige a data completa.')

    def as_date(self, ano: int):
        """Devolve a data efetiva no ano informado (p/ tipo fixo)."""
        if self.tipo == 'fixo':
            from datetime import date
            return date(ano, self.mes, self.dia)
        return self.data

    def __str__(self):
        if self.tipo == 'fixo':
            return f'{self.nome} ({self.mes:02d}/{self.dia:02d})'
        return f'{self.nome} ({self.data})'


class SuspensaoPrazo(TenantModel, TimeStampedModel, ActiveModel):
    """Suspensão de prazos (ponto facultativo, greve, recesso local, etc.).

    Diferente do feriado, aqui há um PERÍODO [data_inicio, data_fim]
    (inclusive) em que NENHUM prazo corre — nem dias úteis, nem
    corridos (exceto se marcada como 'parcial').

    Exemplos:
      - Ponto facultativo (dia único): data_inicio == data_fim.
      - Greve do Judiciário: intervalo de vários dias.
      - Recesso local da comarca/vara.
      - Semana de baixa (suspensão administrativa).

    'motivo' é livre; 'escopo' segue a mesma lógica de Feriado.
    """

    TIPO_CHOICES = [
        ('ponto_facultativo', 'Ponto Facultativo'),
        ('greve', 'Greve / Paralisação'),
        ('recesso_local', 'Recesso Local'),
        ('baixa', 'Semana de Baixa'),
        ('outro', 'Outro'),
    ]
    ESCOPO_CHOICES = Feriado.ESCOPO_CHOICES

    nome = models.CharField('Nome', max_length=120,
        help_text='Ex: Ponto Facultativo, Greve Geral, Recesso Comarca X')
    tipo = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES,
        default='ponto_facultativo')
    escopo = models.CharField('Escopo', max_length=10,
        choices=ESCOPO_CHOICES, default='nacional')
    data_inicio = models.DateField('Data Início (inclusive)')
    data_fim = models.DateField('Data Fim (inclusive)')

    court = models.ForeignKey(
        'projudi.Court', on_delete=models.CASCADE,
        null=True, blank=True, related_name='suspensoes_prazo',
        help_text='Usar p/ escopo=estadual/comarca/vara.')
    vara = models.ForeignKey(
        'projudi.Vara', on_delete=models.CASCADE,
        null=True, blank=True, related_name='suspensoes_prazo',
        help_text='Usar p/ escopo=vara.')

    observacao = models.TextField('Observação', blank=True)

    class Meta:
        verbose_name = 'Suspensão de Prazo'
        verbose_name_plural = 'Suspensões de Prazo'
        ordering = ['data_inicio']

    def __str__(self):
        if self.data_inicio == self.data_fim:
            return f'{self.nome} ({self.data_inicio})'
        return f'{self.nome} ({self.data_inicio} a {self.data_fim})'
