"""Cálculo semiautomático de prazo DJEN + certidão de tempestividade/trânsito.

Não expede nada: calcula, mostra a memória de contagem e gera um preview HTML
para conferência.

Uso:
    python manage.py prazo_djen --disponibilizacao 28/11/2026 --prazo 10
    python manage.py prazo_djen --disponibilizacao 28/11/2026 --protocolo 15/12/2026
    python manage.py prazo_djen --disponibilizacao 28/11/2026 --processo 0002803-76.2025.8.05.0191 --parte "FULANO"
"""

import json
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template import Context, Template

from projudi.certidao_inominado import (
    PREPARO_LABELS, texto_certidao_inominado,
)
from projudi.prazo_service import PrazoService, TIPOS_PRAZO

DIAS_SEMANA = [
    'segunda-feira', 'terça-feira', 'quarta-feira',
    'quinta-feira', 'sexta-feira', 'sábado', 'domingo',
]


def _parse_data(texto):
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime((texto or '').strip(), fmt).date()
        except ValueError:
            continue
    raise CommandError(f'Data inválida: {texto!r} (use 28/11/2026 ou 2026-11-28)')


def _fmt(data):
    if not data:
        return ''
    return f'{data.strftime("%d/%m/%Y")} ({DIAS_SEMANA[data.weekday()]})'


def _fmt_curta(data):
    return data.strftime('%d/%m/%Y') if data else ''


def _texto_publico_prazo(res, info, options, tempestivo=None):
    """Texto público do modelo base para contrarrazões/impugnação."""
    tipo = options.get('tipo')
    evento_recurso = str(options.get('evento_recurso') or '').strip()
    evento_txt = (
        evento_recurso if evento_recurso.isdigit() else 'não informado'
    )

    if tipo == 'impugnacao_embargos_execucao' and tempestivo is not None:
        evento_imp = (
            f'no evento {evento_recurso}'
            if evento_recurso.isdigit() else 'nos autos'
        )
        evento_int = str(options.get('evento_intimacao') or '').strip()
        evento_int_txt = (
            f', evento {evento_int}' if evento_int.isdigit()
            else ', evento não informado'
        )
        seguranca = options.get('seguranca_juizo') or 'nenhuma'
        seguranca_txt = {
            'integral': 'o juízo está integralmente seguro',
            'parcial': (
                'houve depósito parcial, não havendo segurança integral '
                'do juízo'),
            'nenhuma': 'não houve segurança do juízo',
        }.get(seguranca, 'não houve segurança do juízo')
        conclusao = (
            'TEMPESTIVA' if tempestivo else 'INTEMPESTIVA')
        return (
            'Certifico, para os devidos fins, que a Impugnação/Embargos à '
            f'Execução apresentada {evento_imp} é {conclusao}, referente à '
            f'intimação eletrônica (DJEN){evento_int_txt}, que abriu o '
            'prazo de 15 (quinze) dias úteis para pagamento (art. 525, '
            'caput, do CPC). Publicação em '
            f'{_fmt_curta(res.data_publicacao)}; início do prazo em '
            f'{_fmt_curta(res.data_inicio_contagem)}; termo final em '
            f'{_fmt_curta(res.ultimo_dia)}. Certifico ainda que '
            f'{seguranca_txt}, observados o valor executado e o valor '
            'depositado/penhorado (Enunciado n. 117 do FONAJE).'
        )

    if tipo == 'contrarrazoes_inominado' and tempestivo is not None:
        conclusao = (
            'TEMPESTIVIDADE' if tempestivo else 'INTEMPESTIVIDADE')
        return (
            'Certifico, para os devidos fins, a '
            f'{conclusao} das contrarrazões ao recurso inominado, evento '
            f'{evento_txt}. Publicação em '
            f'{_fmt_curta(res.data_publicacao)}; início do prazo em '
            f'{_fmt_curta(res.data_inicio_contagem)}; termo final em '
            f'{_fmt_curta(res.ultimo_dia)}.'
        )

    atos = {
        'cumprimento_sentenca': 'impugnação/cumprimento de sentença',
        'pagamento_impugnacao_penhora': (
            'impugnação ao decurso do prazo da penhora'),
        'decurso_pagamento': (
            'cumprimento voluntário da sentença/impugnação'),
    }
    ato = atos.get(
        tipo,
        str(info.get('ato') or 'manifestação'),
    )
    dias = int(res.prazo_dias)
    palavra = {10: 'dez', 15: 'quinze'}.get(dias, '')
    dias_txt = f'{dias} ({palavra})' if palavra else str(dias)
    evento = str(options.get('evento_intimacao') or '').strip()
    evento_int_txt = (
        f', evento {evento}' if evento.isdigit()
        else ', evento não informado'
    )
    return (
        f'Certifico, para os devidos fins, o prazo de {dias_txt} dias '
        f'úteis para {ato}, referente à intimação eletrônica (DJEN)'
        f'{evento_int_txt}. Publicação em {_fmt_curta(res.data_publicacao)}; '
        f'início do prazo em {_fmt_curta(res.data_inicio_contagem)}; '
        f'termo final em {_fmt_curta(res.ultimo_dia)}.'
    )


class Command(BaseCommand):
    help = 'Calcula prazo DJEN e gera preview de certidão (não expede)'

    def add_arguments(self, parser):
        parser.add_argument('--disponibilizacao', required=True,
                            help='Data da disponibilização (DD/MM/AAAA)')
        parser.add_argument(
            '--tipo', default='inominado', choices=sorted(TIPOS_PRAZO),
            help='Tipo de prazo (default: inominado = 10 dias úteis)')
        parser.add_argument('--prazo', type=int, default=None,
                            help='Sobrescreve os dias do tipo escolhido')
        parser.add_argument('--protocolo',
                            help='Data do protocolo do recurso (para tempestividade)')
        parser.add_argument(
            '--evento-recurso', default='infra',
            help='Número do evento do recurso inominado (default: infra)')
        parser.add_argument('--evento-intimacao', default='',
                            help='Número do evento da intimação/comunicação')
        parser.add_argument(
            '--evento-origem', default='',
            help=(
                'Evento de origem (despacho/decisão/recurso) usado para '
                'localizar a intimação'))
        parser.add_argument(
            '--preparo',
            choices=[
                'gratuidade', 'completo', 'incompleto',
                'insuficiente', 'nao_pago',
            ],
            help=(
                'Preparo do recurso inominado. Obrigatório se TEMPESTIVO; '
                'se INTEMPESTIVO, não é verificado.'))
        parser.add_argument(
            '--seguranca-juizo',
            choices=['integral', 'parcial', 'nenhuma'],
            help=(
                'Segurança do juízo na impugnação/embargos à execução: '
                'integral, depósito parcial ou não houve.'))
        parser.add_argument(
            '--habilitacao', choices=['regular', 'omitir'], default='regular',
            help='Cláusula de habilitação dos advogados (default: regular)')
        parser.add_argument('--processo', help='Número CNJ')
        parser.add_argument('--parte', help='Nome da parte')
        parser.add_argument(
            '--origem', choices=['peticao', 'movimentacao'],
            help=(
                'Origem da certidão. Default: petição para recurso/'
                'contrarrazões; movimentação para os demais tipos.'))
        parser.add_argument(
            '--peticao-documento',
            help='Nome do documento da petição (para a aba Petições)')
        parser.add_argument(
            '--peticao-url', help='URL do PDF/documento da petição')
        parser.add_argument('--servidor', default='IVAN GUEDES DA SILVA')
        parser.add_argument(
            '--servidor-cargo', default='Servidor Secretaria 2',
            help='Cargo do servidor que assina')
        parser.add_argument('--tenant', type=int, help='ID do tenant (opcional)')
        parser.add_argument('--saida', help='Arquivo HTML de saída')
        parser.add_argument('--sem-html', action='store_true',
                            help='Só calcula, sem gerar HTML')
        parser.add_argument(
            '--nao-registrar', action='store_true',
            help='Não grava o controle no dashboard (apenas preview/teste)')

    def handle(self, *args, **options):
        if options.get('preparo') == 'insuficiente':
            options['preparo'] = 'incompleto'
        if not options.get('origem'):
            options['origem'] = (
                'peticao'
                if options.get('tipo') in (
                    'inominado', 'contrarrazoes_inominado',
                    'impugnacao_embargos_execucao')
                else 'movimentacao'
            )
        if (options['tipo'] == 'impugnacao_embargos_execucao'
                and not options.get('seguranca_juizo')):
            raise CommandError(
                'Informe --seguranca-juizo (integral, parcial ou nenhuma) '
                'para a Impugnação/Embargos à Execução.')
        dispo = _parse_data(options['disponibilizacao'])
        protocolo = (
            _parse_data(options['protocolo'])
            if options['protocolo'] else None
        )
        if (options['tipo'] == 'impugnacao_embargos_execucao'
                and not protocolo):
            raise CommandError(
                'Informe --protocolo (data do protocolo da '
                'impugnação/embargos) para a certidão de tempestividade.')

        info = TIPOS_PRAZO[options['tipo']]
        prazo = options['prazo'] or int(info['dias'])
        if options['prazo'] and int(options['prazo']) != int(info['dias']):
            self.stdout.write(self.style.WARNING(
                f'Prazo informado ({options["prazo"]}) difere do padrão do '
                f'tipo {options["tipo"]} ({info["dias"]}). Usando '
                f'{options["prazo"]}.'))

        tenant = self._tenant(options)
        if tenant:
            anos = list(range(dispo.year, dispo.year + 3))
            svc = PrazoService.from_db(tenant=tenant, anos=anos)
        else:
            self.stdout.write(self.style.WARNING(
                'Sem tenant: usando apenas feriados nacionais fixos/móveis '
                'e recesso forense.'))
            svc = PrazoService()

        res = svc.contar_prazo_djen(dispo, prazo)

        tempestivo = (protocolo <= res.ultimo_dia) if protocolo else None
        preparo_status = 'nao_verificado'
        habilitacao_regular = options['habilitacao'] == 'regular'
        texto_certidao = ''
        template_nome = None

        if options['tipo'] == 'inominado' and protocolo:
            if tempestivo and not options['preparo']:
                raise CommandError(
                    'Recurso inominado TEMPESTIVO: informe --preparo '
                    '(gratuidade, completo, incompleto ou nao_pago).')
            if not tempestivo:
                if options['preparo']:
                    self.stdout.write(self.style.WARNING(
                        'Recurso INTEMPESTIVO: o preparo não é verificado; '
                        '--preparo ignorado.'))
            else:
                preparo_status = options['preparo']

            texto_certidao = texto_certidao_inominado(
                evento_recurso=options['evento_recurso'],
                tempestivo=bool(tempestivo),
                preparo_status=preparo_status,
                habilitacao_regular=habilitacao_regular,
            )
            template_nome = 'Certidão de Recurso Inominado (COJE)'
        elif options['tipo'] != 'inominado':
            texto_certidao = _texto_publico_prazo(
                res, info, options, tempestivo=tempestivo)
            template_nome = 'Certidão de Prazo — Modelo Base'

        self.stdout.write('=' * 70)
        self.stdout.write('CONTAGEM DJEN — ' + str(info['label']).upper())
        self.stdout.write('=' * 70)
        self.stdout.write(f'Disponibilização .........: {_fmt(dispo)}')
        self.stdout.write(f'Publicação (DJEN) ........: {_fmt(res.data_publicacao)}')
        self.stdout.write(
            f'Início do prazo (1º dia) .: {_fmt(res.data_inicio_contagem)}')
        self.stdout.write(f'Prazo ....................: {prazo} dias úteis')
        self.stdout.write(f'Último dia ...............: {_fmt(res.ultimo_dia)}')
        if info['transito']:
            self.stdout.write(
                f'Trânsito (1º útil após) ..: {_fmt(res.data_decurso)}')
        else:
            self.stdout.write(
                f'Decurso (1º útil após) ...: {_fmt(res.data_decurso)}')

        if protocolo:
            self.stdout.write(
                f'Protocolo ................: {_fmt(protocolo)}')
            self.stdout.write(self.style.SUCCESS(
                f'Tempestividade ...........: '
                f'{"TEMPESTIVO" if tempestivo else "INTEMPESTIVO"}'))
            if options['tipo'] == 'inominado':
                self.stdout.write(
                    f'Evento do recurso ........: '
                    f'{options["evento_recurso"]}')
                if tempestivo:
                    self.stdout.write(
                        f'Preparo ..................: '
                        f'{PREPARO_LABELS.get(preparo_status, preparo_status)}')
                else:
                    self.stdout.write(
                        'Preparo ..................: não verificado '
                        '(intempestivo)')
                self.stdout.write(
                    f'Habilitação ..............: '
                    f'{"regular" if habilitacao_regular else "omitida"}')
            if options.get('seguranca_juizo'):
                self.stdout.write(
                    f'Segurança do juízo .......: '
                    f'{options["seguranca_juizo"]}')
        else:
            tipo_certidao = (
                'certidão de trânsito' if info['transito']
                else 'certidão de prazo')
            self.stdout.write(
                f'Protocolo ................: não informado ({tipo_certidao})')
            self.stdout.write(
                '⚠️ Confirme nos autos o decurso/não interposição antes de '
                'assinar a certidão.')

        self.stdout.write('')
        self.stdout.write(res.relatorio())
        self.stdout.write('')
        self.stdout.write('prazo_info (JSON):')
        self.stdout.write(str(res.to_dict()))

        if texto_certidao:
            self.stdout.write('')
            self.stdout.write('Texto da certidão:')
            self.stdout.write(texto_certidao)

        certidao_path = ''
        if not options['sem_html']:
            certidao_path = self._gerar_html(
                res, protocolo, options, info,
                texto_certidao=texto_certidao,
                preparo_status=preparo_status,
                habilitacao_regular=habilitacao_regular,
                template_nome=template_nome,
            )
        if not options.get('nao_registrar'):
            self._registrar_log(
                res, protocolo, info, options, certidao_path,
                texto_certidao=texto_certidao,
                preparo_status=preparo_status,
                habilitacao_regular=habilitacao_regular,
                tempestivo=tempestivo,
            )

    def _tenant(self, options):
        if options['tenant']:
            from accounts.models import Tenant
            return Tenant.objects.filter(pk=options['tenant']).first()

        if options['processo']:
            from processes.models import Process
            proc = Process.objects.filter(number=options['processo']).first()
            if proc and proc.tenant_id:
                return proc.tenant

        from accounts.models import Tenant
        return Tenant.objects.first()

    def _observacao(self, res, protocolo, info):
        """Texto enxuto da certidão (o detalhe fica no controle/log)."""
        texto = (
            f'Intimação eletrônica (DJEN) — prazo de {res.prazo_dias} dias '
            f'úteis para {str(info["label"]).lower()}. Publicação em '
            f'{_fmt_curta(res.data_publicacao)}; início em '
            f'{_fmt_curta(res.data_inicio_contagem)}; vencimento em '
            f'{_fmt_curta(res.ultimo_dia)}.'
        )
        if protocolo:
            tempestivo = protocolo <= res.ultimo_dia
            texto += (
                f' {info["protocolo_frase"]} em {_fmt_curta(protocolo)}, '
                f'{"dentro" if tempestivo else "fora"} do prazo '
                f'({"TEMPESTIVO" if tempestivo else "INTEMPESTIVO"}).'
            )
        elif info['transito']:
            texto += (
                f' Não havendo {info["ato"]}, o trânsito em julgado ocorre '
                f'em {_fmt_curta(res.data_decurso)}.'
            )
        else:
            texto += (
                f' O decurso do prazo ocorre em '
                f'{_fmt_curta(res.data_decurso)}.'
            )
        return texto

    def _motivo(self, res, protocolo, info, preparo_status='',
                habilitacao_regular=None, evento_recurso='', tipo='',
                seguranca_juizo=''):
        """Memória completa, só para controle (não vai na certidão)."""
        linhas = [
            f'Disponibilização: {_fmt(res.data_disponibilizacao)}',
            f'Publicação DJEN: {_fmt(res.data_publicacao)}',
            f'Início do prazo: {_fmt(res.data_inicio_contagem)}',
            f'Prazo: {res.prazo_dias} dias úteis ({info["label"]})',
            f'Último dia: {_fmt(res.ultimo_dia)}',
            f'Decurso/trânsito: {_fmt(res.data_decurso)}',
        ]
        if protocolo:
            tempestivo = protocolo <= res.ultimo_dia
            linhas.append(
                f'Protocolo: {_fmt(protocolo)} — '
                f'{"dentro" if tempestivo else "fora"} do prazo '
                f'({"TEMPESTIVO" if tempestivo else "INTEMPESTIVO"})')
        else:
            linhas.append('Protocolo: não informado')

        if tipo == 'inominado':
            linhas.append(f'Evento do recurso: {evento_recurso or "infra"}')
            if protocolo and protocolo > res.ultimo_dia:
                linhas.append('Preparo: não verificado (recurso intempestivo)')
            else:
                linhas.append(
                    f'Preparo: '
                    f'{PREPARO_LABELS.get(preparo_status, preparo_status)}')
            linhas.append(
                'Habilitação dos advogados: '
                f'{"regular" if habilitacao_regular else "omitida"}')

        if seguranca_juizo:
            rotulos = {
                'integral': 'Integral',
                'parcial': 'Depósito parcial',
                'nenhuma': 'Não houve',
            }
            linhas.append(
                f'Segurança do juízo: '
                f'{rotulos.get(seguranca_juizo, seguranca_juizo)}')

        linhas.append(
            'Dias contados: ' + ', '.join(
                d.strftime('%d/%m/%Y') for d in res.dias_contados))
        linhas.append(
            'Dias excluídos: ' + ', '.join(
                d.strftime('%d/%m/%Y') for d in res.dias_excluidos))
        return '\n'.join(linhas)

    def _registrar_log(
        self, res, protocolo, info, options, certidao_path='',
        texto_certidao='', preparo_status='', habilitacao_regular=None,
        tempestivo=None,
    ):
        from projudi.models import PrazoDjenRecord

        if tempestivo is None:
            tempestivo = (protocolo <= res.ultimo_dia) if protocolo else None
        # Nos tipos que não são recurso inominado, o corpo público da certidão
        # é a observação de prazo. Guarda esse texto no controle para o
        # detalhe não ficar vazio.
        texto_registro = texto_certidao or self._observacao(
            res, protocolo, info)
        motivo = self._motivo(
            res, protocolo, info,
            preparo_status=preparo_status,
            habilitacao_regular=habilitacao_regular,
            evento_recurso=options['evento_recurso'],
            tipo=options['tipo'],
            seguranca_juizo=options.get('seguranca_juizo') or '',
        )
        registro_id = None
        try:
            rec = PrazoDjenRecord.objects.create(
                processo=options['processo'] or '',
                parte=options['parte'] or '',
                origem=options.get('origem') or 'movimentacao',
                peticao_documento=options.get('peticao_documento') or '',
                peticao_url=options.get('peticao_url') or '',
                tipo_prazo=options['tipo'],
                prazo_dias=res.prazo_dias,
                data_disponibilizacao=res.data_disponibilizacao,
                data_disponibilizacao_efetiva=(
                    res.data_disponibilizacao_efetiva),
                data_publicacao=res.data_publicacao,
                data_inicio_contagem=res.data_inicio_contagem,
                ultimo_dia=res.ultimo_dia,
                data_decurso=res.data_decurso,
                data_protocolo=protocolo,
                evento_recurso=options['evento_recurso'] or '',
                evento_origem=options.get('evento_origem') or '',
                evento_intimacao=options.get('evento_intimacao') or '',
                preparo_status=preparo_status or '',
                seguranca_juizo=options.get('seguranca_juizo') or '',
                habilitacao_regular=habilitacao_regular,
                texto_certidao=texto_registro,
                tempestivo=tempestivo,
                motivo=motivo,
                prazo_info=res.to_dict(),
                certidao_path=certidao_path,
                servidor=options['servidor'],
            )
            registro_id = rec.id
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(
                f'Controle registrado: #{rec.id} '
                f'(admin: /admin/projudi/prazodjenrecord/)'))
        except Exception as e:
            self.stderr.write(
                f'⚠️ Não foi possível registrar no banco: {e}')

        try:
            pasta = Path(settings.BASE_DIR) / 'var'
            pasta.mkdir(parents=True, exist_ok=True)
            log = pasta / 'prazo_djen.jsonl'
            payload = {
                'id': registro_id,
                'processo': options['processo'] or '',
                'parte': options['parte'] or '',
                'origem': options.get('origem') or 'movimentacao',
                'peticao_documento': options.get('peticao_documento') or '',
                'peticao_url': options.get('peticao_url') or '',
                'tipo_prazo': options['tipo'],
                'prazo_dias': res.prazo_dias,
                'tempestivo': tempestivo,
                'evento_recurso': options['evento_recurso'] or '',
                'evento_origem': options.get('evento_origem') or '',
                'evento_intimacao': options.get('evento_intimacao') or '',
                'preparo_status': preparo_status or '',
                'seguranca_juizo': options.get('seguranca_juizo') or '',
                'habilitacao_regular': habilitacao_regular,
                'texto_certidao': texto_registro,
                'motivo': motivo,
                'prazo_info': res.to_dict(),
                'certidao_path': certidao_path,
                'servidor': options['servidor'],
            }
            with log.open('a', encoding='utf-8') as f:
                f.write(json.dumps(
                    payload, ensure_ascii=False, default=str) + '\n')
            self.stdout.write(f'Log de controle: {log}')
        except Exception as e:
            self.stderr.write(f'⚠️ Não foi possível gravar o log: {e}')

    def _gerar_html(self, res, protocolo, options, info,
                    texto_certidao='', preparo_status='',
                    habilitacao_regular=None, template_nome=None):
        from html import escape as html_escape
        from processes.models import DocumentTemplate

        nome_tpl = template_nome or (
            'Certidão de Recurso Inominado (COJE)'
            if texto_certidao
            else 'Certidão de Tempestividade / Trânsito (DJEN)'
        )
        tpl = DocumentTemplate.objects.filter(
            name=nome_tpl, active=True).first()

        ctx = {
            'processo': options['processo'] or '—',
            'parte': options['parte'] or '',
            'observacao_prazo': self._observacao(res, protocolo, info),
            'texto_certidao': texto_certidao,
            'data': date.today().strftime('%d/%m/%Y'),
            'servidor': options['servidor'],
            'servidor_cargo': (
                options.get('servidor_cargo') or 'Servidor Secretaria 2'),
            'evento_intimacao': options.get('evento_intimacao') or '',
            'data_publicacao': _fmt_curta(res.data_publicacao),
            'data_inicio_contagem': _fmt_curta(res.data_inicio_contagem),
            'ultimo_dia': _fmt_curta(res.ultimo_dia),
        }
        parte_html = (
            f'<p>Para: {html_escape(ctx["parte"])}</p>'
            if ctx['parte'] else ''
        )

        if texto_certidao:
            titulo = 'CERTIDÃO'
        else:
            titulo = (
                'CERTIDÃO DE TRÂNSITO EM JULGADO'
                if info['transito'] else 'CERTIDÃO DE PRAZO'
            )

        if tpl:
            html = Template(tpl.html_template).render(Context(ctx))
            if not texto_certidao:
                html = html.replace(
                    'CERTIDÃO DE TEMPESTIVIDADE E TRÂNSITO', titulo)
            nome_template = tpl.name
        else:
            if texto_certidao:
                html = (
                    '<div style="font-family:Times New Roman,serif;font-size:12pt;">'
                    '<h3>CERTIDÃO</h3>'
                    f'<p>Processo: {html_escape(ctx["processo"])}</p>'
                    f'{parte_html}'
                    f'<p>{html_escape(texto_certidao)}</p>'
                    f'<p>Paulo Afonso-BA, {ctx["data"]}.<br>'
                    f'{html_escape(ctx["servidor"])}</p></div>'
                )
            else:
                html = (
                    '<div style="font-family:Times New Roman,serif;font-size:12pt;">'
                    f'<h3>{titulo}</h3>'
                    f'<p>Processo: {ctx["processo"]}</p>'
                    f'{parte_html}'
                    f'<p>Certifico que, referente ao processo em epígrafe, '
                    f'{ctx["observacao_prazo"]}</p>'
                    f'<p>Paulo Afonso-BA, {ctx["data"]}.<br>'
                    f'{ctx["servidor"]}</p></div>'
                )
            nome_template = '(fallback)'

        pasta = Path(settings.BASE_DIR) / 'var'
        pasta.mkdir(parents=True, exist_ok=True)
        saida = Path(options['saida']) if options['saida'] else (
            pasta / f'certidao_{options["tipo"]}_'
            f'{res.data_disponibilizacao.isoformat()}_'
            f'{datetime.now().strftime("%H%M%S")}.html')
        saida.parent.mkdir(parents=True, exist_ok=True)

        cabecalho = texto_certidao or self._observacao(
            res, protocolo, info)

        pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Preview certidão — {ctx['processo']}</title>
<style>body{{background:#eee;padding:20px;}}
.folha{{background:#fff;padding:40px;max-width:850px;margin:0 auto;
box-shadow:0 2px 12px rgba(0,0,0,.2);}}
.aviso{{max-width:850px;margin:0 auto 12px;padding:8px 12px;background:#fef3c7;
border:1px solid #f59e0b;font-family:Arial,sans-serif;font-size:13px;}}
</style></head><body>
<div class="aviso"><strong>PREVIEW — CONFERIR ANTES DE EXPEDIR.</strong>
Template: {nome_template}. {cabecalho}</div>
<div class="folha">{html}</div>
</body></html>"""
        saida.write_text(pagina, encoding='utf-8')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Preview: {saida}'))
        self.stdout.write('Abra no Firefox e confira antes de lançar no Projudi.')
        return str(saida)
