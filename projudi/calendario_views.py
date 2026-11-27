"""Calendário forense: feriados, suspensões e dias úteis."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


MESES = [
    'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]


class CalendarioForenseView(LoginRequiredMixin, TemplateView):
    template_name = 'projudi/calendario_forense.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from projudi.models import Feriado, SuspensaoPrazo

        hoje = date.today()
        try:
            ano = int(self.request.GET.get('ano') or hoje.year)
            mes = int(self.request.GET.get('mes') or hoje.month)
        except (TypeError, ValueError):
            ano, mes = hoje.year, hoje.month
        if not 1 <= mes <= 12:
            mes = hoje.month
        if not 1900 <= ano <= 2200:
            ano = hoje.year

        tenant = getattr(self.request.user, 'tenant', None)
        feriados = Feriado.objects.filter(is_active=True)
        suspensoes = SuspensaoPrazo.objects.filter(is_active=True)
        if tenant:
            feriados = feriados.filter(tenant=tenant)
            suspensoes = suspensoes.filter(tenant=tenant)

        eventos = {}

        def adicionar(dia, texto, tipo):
            if dia.year == ano and dia.month == mes:
                eventos.setdefault(dia, []).append({
                    'texto': texto,
                    'tipo': tipo,
                })

        for feriado in feriados:
            if feriado.tipo == 'fixo':
                if feriado.mes == mes and feriado.dia:
                    try:
                        dia = date(ano, mes, feriado.dia)
                    except ValueError:
                        continue
                    adicionar(
                        dia, feriado.nome, 'feriado')
            elif feriado.data:
                adicionar(feriado.data, feriado.nome, 'feriado')

        for suspensao in suspensoes:
            if not suspensao.data_inicio or not suspensao.data_fim:
                continue
            dia = max(suspensao.data_inicio, date(ano, mes, 1))
            fim = min(suspensao.data_fim, date(
                ano, mes, calendar.monthrange(ano, mes)[1]))
            while dia <= fim:
                adicionar(dia, suspensao.nome, 'suspensao')
                dia += timedelta(days=1)

        cal = calendar.Calendar(firstweekday=6)
        semanas = []
        for semana in cal.monthdatescalendar(ano, mes):
            celulas = []
            for dia in semana:
                eventos_dia = eventos.get(dia, [])
                celulas.append({
                    'data': dia,
                    'numero': dia.day,
                    'no_mes': dia.month == mes,
                    'fim_semana': dia.weekday() >= 5,
                    'hoje': dia == hoje,
                    'feriado': any(
                        e['tipo'] == 'feriado' for e in eventos_dia),
                    'suspensao': any(
                        e['tipo'] == 'suspensao' for e in eventos_dia),
                    'eventos': eventos_dia,
                })
            semanas.append(celulas)

        primeiro = date(ano, mes, 1)
        anterior = primeiro - timedelta(days=1)
        proximo = date(
            ano + (1 if mes == 12 else 0),
            1 if mes == 12 else mes + 1,
            1,
        )

        eventos_mes = []
        for dia in sorted(eventos):
            for ev in eventos[dia]:
                eventos_mes.append({
                    'data': dia,
                    'texto': ev['texto'],
                    'tipo': ev['tipo'],
                })

        context.update({
            'ano': ano,
            'mes': mes,
            'mes_nome': MESES[mes - 1],
            'semanas': semanas,
            'hoje': hoje,
            'eventos_mes': eventos_mes,
            'ano_anterior': anterior.year,
            'mes_anterior': anterior.month,
            'ano_proximo': proximo.year,
            'mes_proximo': proximo.month,
            'dias_uteis': sum(
                1 for d in calendar.Calendar().itermonthdates(ano, mes)
                if d.month == mes
                and d.weekday() < 5
                and d not in eventos
            ),
        })
        return context
