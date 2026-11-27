"""Ações de certidão agendadas para depois do prazo da intimação."""

from __future__ import annotations

from datetime import date

from django.utils import timezone


def data_decurso_intimacao(user, data_base=None, dias=15):
    """Primeiro dia útil seguinte ao prazo de 15 dias da intimação."""
    from projudi.prazo_service import PrazoService

    base = data_base or date.today()
    tenant = getattr(user, 'tenant', None)
    if tenant:
        svc = PrazoService.from_db(
            tenant=tenant, anos=list(range(base.year, base.year + 2)))
    else:
        svc = PrazoService()
    return svc.contar_prazo_djen(base, dias).data_decurso


def agendar_pos_intimacao(
    registro, user, tipos, data_base=None, *,
    tipo_localizador='', localizador='', tipo_conclusao='18',
    juiz_conclusao='41201',
):
    """Cria as ações escolhidas para o dia seguinte ao prazo da intimação."""
    from projudi.models import AcaoCertidaoAgendada

    data_agendada = data_decurso_intimacao(user, data_base=data_base)
    criadas = []
    for tipo in tipos:
        if tipo not in dict(AcaoCertidaoAgendada.TIPO_CHOICES):
            continue
        acao = AcaoCertidaoAgendada.objects.create(
            registro=registro,
            tipo=tipo,
            data_agendada=data_agendada,
            tipo_localizador=tipo_localizador if tipo == 'localizador' else '',
            localizador=localizador if tipo == 'localizador' else '',
            tipo_conclusao=tipo_conclusao if tipo == 'conclusao' else '',
            juiz_conclusao=juiz_conclusao if tipo == 'conclusao' else '',
            user=user,
        )
        criadas.append(acao)
    return data_agendada, criadas


def _processo_url(registro, user):
    from projudi.juntar_service import montar_plano

    plano = montar_plano(registro, user)
    return plano.get('processo_url') or ''


def executar_acao(acao, user):
    """Executa uma ação agendada e atualiza seu status."""
    from projudi.movimentacao_service import MovimentacaoService

    registro = acao.registro
    try:
        if acao.tipo == 'localizador':
            if not (acao.tipo_localizador or acao.localizador):
                raise ValueError('Ação sem código de localizador.')
            url = _processo_url(registro, user)
            service = MovimentacaoService(user)
            record = service.importar(
                processo_numero=registro.processo,
                act_verb='localizar',
                observacao='Localizador após o prazo da intimação.',
                categoria='outro',
                processo_cnj=registro.processo,
                url_processo=url,
                codigo_movimentacao='581',
                descricao_movimentacao='Localizador',
                tipo_localizador=acao.tipo_localizador,
                localizador=acao.localizador,
            )
            ok = service.executar_requests(record)

        elif acao.tipo == 'contadoria':
            from projudi.juntar_service import (
                executar_contadoria, montar_plano,
            )
            plano = montar_plano(registro, user)
            ok, _rec = executar_contadoria(registro, user, plano)

        elif acao.tipo == 'conclusao':
            from projudi.juntar_service import (
                executar_conclusao, montar_plano,
            )
            plano = montar_plano(registro, user)
            ok, _rec = executar_conclusao(
                registro, user, plano,
                tipo_conclusao=acao.tipo_conclusao or '18',
                juiz_conclusao=acao.juiz_conclusao or '41201',
            )

        else:
            raise ValueError(f'Ação desconhecida: {acao.tipo}')

        acao.status = 'executada' if ok else 'falha'
        acao.erro = '' if ok else 'A execução não foi confirmada.'
        acao.executado_em = timezone.now()
        acao.save(update_fields=['status', 'erro', 'executado_em'])
        return bool(ok)

    except Exception as exc:
        acao.status = 'falha'
        acao.erro = str(exc)[:2000]
        acao.executado_em = timezone.now()
        acao.save(update_fields=['status', 'erro', 'executado_em'])
        return False


def executar_pendentes(user=None, data=None):
    """Executa ações vencidas. O filtro por usuário é opcional."""
    from projudi.models import AcaoCertidaoAgendada

    qs = AcaoCertidaoAgendada.objects.filter(
        status='pendente', data_agendada__lte=data or date.today())
    if user is not None:
        qs = qs.filter(user=user)
    resultados = {'executadas': 0, 'falhas': 0}
    for acao in qs.select_related('registro'):
        ok = executar_acao(acao, acao.user or user)
        if ok:
            resultados['executadas'] += 1
        else:
            resultados['falhas'] += 1
    return resultados
