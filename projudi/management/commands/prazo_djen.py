"""Cálculo semiautomático de prazo DJEN + certidão de tempestividade/trânsito.

Não expede nada: calcula, mostra a memória de contagem e gera um preview HTML
para conferência.

Uso:
    python manage.py prazo_djen --disponibilizacao 28/11/2026 --prazo 10
    python manage.py prazo_djen --disponibilizacao 28/11/2026 --protocolo 15/12/2026
    python manage.py prazo_djen --disponibilizacao 28/11/2026 --processo 0002803-76.2025.8.05.0191 --parte "FULANO"
"""

from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template import Context, Template

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
        parser.add_argument('--processo', help='Número CNJ')
        parser.add_argument('--parte', help='Nome da parte')
        parser.add_argument('--servidor', default='IVAN GUEDES DA SILVA')
        parser.add_argument('--tenant', type=int, help='ID do tenant (opcional)')
        parser.add_argument('--saida', help='Arquivo HTML de saída')
        parser.add_argument('--sem-html', action='store_true',
                            help='Só calcula, sem gerar HTML')

    def handle(self, *args, **options):
        dispo = _parse_data(options['disponibilizacao'])
        protocolo = (
            _parse_data(options['protocolo'])
            if options['protocolo'] else None
        )

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

        self.stdout.write('=' * 70)
        self.stdout.write('CONTAGEM DJEN — ' + str(info['label']).upper())
        self.stdout.write('=' * 70)
        self.stdout.write(f'Disponibilização bruta ..: {_fmt(dispo)}')
        self.stdout.write(
            f'Disponibilização efetiva .: '
            f'{_fmt(res.data_disponibilizacao_efetiva)}')
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
            tempestivo = protocolo <= res.ultimo_dia
            self.stdout.write(
                f'Protocolo ................: {_fmt(protocolo)}')
            self.stdout.write(self.style.SUCCESS(
                f'Tempestividade ...........: '
                f'{"TEMPESTIVO" if tempestivo else "INTEMPESTIVO"}'))
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

        if not options['sem_html']:
            self._gerar_html(res, protocolo, options, info)

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
        texto = (
            f'Intimação eletrônica (DJEN): disponibilização em '
            f'{_fmt(res.data_disponibilizacao)}, considerada em '
            f'{_fmt(res.data_disponibilizacao_efetiva)}; publicação no DJEN '
            f'em {_fmt(res.data_publicacao)}; início do prazo em '
            f'{_fmt(res.data_inicio_contagem)}; prazo de '
            f'{res.prazo_dias} dias úteis para {str(info["label"]).lower()}; '
            f'último dia do prazo em {_fmt(res.ultimo_dia)}.'
        )
        if protocolo:
            tempestivo = protocolo <= res.ultimo_dia
            texto += (
                f' {info["protocolo_frase"]} em {_fmt(protocolo)}, '
                f'{"dentro" if tempestivo else "fora"} do prazo '
                f'({"TEMPESTIVO" if tempestivo else "INTEMPESTIVO"}).'
            )
        elif info['transito']:
            texto += (
                f' Não havendo {info["ato"]}, o trânsito em julgado ocorre '
                f'em {_fmt(res.data_decurso)}.'
            )
        else:
            texto += (
                f' O decurso do prazo ocorre em {_fmt(res.data_decurso)}.'
            )
        return texto

    def _gerar_html(self, res, protocolo, options, info):
        from processes.models import DocumentTemplate

        tpl = DocumentTemplate.objects.filter(
            name='Certidão de Tempestividade / Trânsito (DJEN)',
            active=True,
        ).first()

        ctx = {
            'processo': options['processo'] or '—',
            'parte': options['parte'] or 'as partes',
            'observacao_prazo': self._observacao(res, protocolo, info),
            'data': date.today().strftime('%d/%m/%Y'),
            'servidor': options['servidor'],
        }

        titulo = (
            'CERTIDÃO DE TRÂNSITO EM JULGADO'
            if info['transito'] else 'CERTIDÃO DE PRAZO'
        )

        if tpl:
            html = Template(tpl.html_template).render(Context(ctx))
            html = html.replace(
                'CERTIDÃO DE TEMPESTIVIDADE E TRÂNSITO', titulo)
            nome_template = tpl.name
        else:
            html = (
                '<div style="font-family:Times New Roman,serif;font-size:12pt;">'
                f'<h3>{titulo}</h3>'
                f'<p>Processo: {ctx["processo"]}</p>'
                f'<p>Para: {ctx["parte"]}</p>'
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
            f'{res.data_disponibilizacao.isoformat()}.html')
        saida.parent.mkdir(parents=True, exist_ok=True)

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
Template: {nome_template}. {self._observacao(res, protocolo, info)}</div>
<div class="folha">{html}</div>
</body></html>"""
        saida.write_text(pagina, encoding='utf-8')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Preview: {saida}'))
        self.stdout.write('Abra no Firefox e confira antes de lançar no Projudi.')
