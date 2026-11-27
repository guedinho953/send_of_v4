"""Geração e registro da certidão de decurso de pagamento voluntário."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.template import Context, Template

from projudi.models import PrazoDjenRecord

NOME_TEMPLATE = 'Certidão de Decurso de Prazo para Pagamento Voluntário'


def _fmt_data(valor):
    if isinstance(valor, date):
        return valor.strftime('%d/%m/%Y')
    if isinstance(valor, str) and valor.strip():
        for formato in ('%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
            try:
                return datetime.strptime(
                    valor.strip()[:10], formato).strftime('%d/%m/%Y')
            except ValueError:
                continue
    return ''


def texto_certidao(resultado) -> str:
    """Texto público da certidão (sem a memória de cálculo)."""
    info = resultado.get('prazo_info') or {}
    publicacao = _fmt_data(
        resultado.get('data_publicacao')
        or info.get('data_publicacao'))
    inicio = _fmt_data(
        resultado.get('data_inicio_contagem')
        or info.get('data_inicio_contagem')
        or resultado.get('data_inicio'))
    decurso = resultado['ultimo_dia'].strftime('%d/%m/%Y')
    evento = str(resultado.get('evento_intimacao') or '').strip()
    evento_txt = (
        f', evento {evento}' if evento.isdigit()
        else ', evento não informado'
    )
    return (
        'Certifico, para os devidos fins, o DECURSO DO PRAZO de 15 (quinze) '
        'dias úteis para cumprimento voluntário da sentença/impugnação '
        'pelo(a)(s) executado(a)(s), referente à intimação eletrônica '
        f'(DJEN){evento_txt}. Publicação em {publicacao or "?"}; início do '
        f'prazo em {inicio or "?"}; decurso em {decurso}.'
    )


def motivo(resultado) -> str:
    """Memória completa, só para controle interno."""
    origem = 'automático' if resultado.get('despacho_auto') else 'informado'
    linhas = [
        'Certidão de decurso de pagamento voluntário — 15 dias úteis',
        f'Processo: {resultado["processo"]}',
        f'Executado(a): {resultado["executado"]}',
        f'Despacho: evento {resultado["evento_despacho"]} ({origem})',
    ]
    if resultado.get('despacho_trecho'):
        linhas.append(f'Trecho do despacho: {resultado["despacho_trecho"]}')
    linhas.extend([
        f'Intimação: evento {resultado.get("evento_intimacao") or "?"} em '
        f'{resultado["data_intimacao"].strftime("%d/%m/%Y")} '
        f'({resultado.get("meio_label") or resultado.get("meio")})',
        f'Início do prazo: '
        f'{(resultado.get("data_inicio_contagem") or resultado["data_inicio"]).strftime("%d/%m/%Y")}',
        f'Último dia: {resultado["ultimo_dia"].strftime("%d/%m/%Y")}',
        f'Decurso: {resultado["data_decurso"].strftime("%d/%m/%Y")}',
    ])
    return '\n'.join(linhas)


def _contexto(resultado, servidor, servidor_cargo):
    info = resultado.get('prazo_info') or {}
    return {
        'processo': resultado['processo'],
        'executado': resultado['executado'],
        'evento_despacho': resultado['evento_despacho'],
        'evento_intimacao': resultado.get('evento_intimacao') or '',
        'data_intimacao': resultado['data_intimacao'].strftime('%d/%m/%Y'),
        'data_publicacao': _fmt_data(
            resultado.get('data_publicacao')
            or info.get('data_publicacao')),
        'data_inicio_contagem': _fmt_data(
            resultado.get('data_inicio_contagem')
            or info.get('data_inicio_contagem')
            or resultado.get('data_inicio')),
        'ultimo_dia': resultado['ultimo_dia'].strftime('%d/%m/%Y'),
        'data_decurso': resultado['data_decurso'].strftime('%d/%m/%Y'),
        'data': date.today().strftime('%d/%m/%Y'),
        'servidor': servidor,
        'servidor_cargo': servidor_cargo,
    }


def gerar_preview(resultado, servidor, servidor_cargo, saida=None):
    """Renderiza o template e salva o HTML de preview em ``var/``."""
    from processes.models import DocumentTemplate

    tpl = DocumentTemplate.objects.filter(
        name=NOME_TEMPLATE, active=True).first()
    if not tpl:
        raise RuntimeError(
            f'Template "{NOME_TEMPLATE}" não encontrado. '
            'Rode as migrações do app processes.'
        )

    html_certidao = Template(tpl.html_template).render(
        Context(_contexto(resultado, servidor, servidor_cargo))
    )

    pasta = Path(settings.BASE_DIR) / 'var'
    pasta.mkdir(parents=True, exist_ok=True)
    if not saida:
        processo = ''.join(
            c for c in resultado['processo'] if c.isdigit())
        saida = pasta / (
            f'certidao_decurso_{processo}_'
            f'{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
        )
    caminho = Path(saida)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Preview certidão — {resultado['processo']}</title>
<style>
body{{background:#eee;padding:20px;}}
.folha{{background:#fff;padding:40px;max-width:850px;margin:0 auto;
box-shadow:0 2px 12px rgba(0,0,0,.2);}}
.aviso{{max-width:850px;margin:0 auto 12px;padding:8px 12px;
background:#fef3c7;border:1px solid #f59e0b;font-family:Arial,sans-serif;
font-size:13px;}}
</style></head><body>
<div class="aviso"><strong>PREVIEW — CONFERIR ANTES DE EXPEDIR.</strong>
Template: {NOME_TEMPLATE}. {texto_certidao(resultado)}</div>
<div class="folha">{html_certidao}</div>
</body></html>"""
    caminho.write_text(pagina, encoding='utf-8')
    return html_certidao, str(caminho)


def registrar(resultado, certidao_path='', servidor='',
              texto='', motivo_texto=''):
    """Grava o controle no dashboard, na aba Movimentações."""
    info = resultado.get('prazo_info') or {}
    return PrazoDjenRecord.objects.create(
        processo=resultado['processo'],
        parte=resultado['executado'],
        origem='movimentacao',
        tipo_prazo='decurso_pagamento',
        prazo_dias=resultado['dias'],
        data_disponibilizacao=resultado['data_intimacao'],
        data_disponibilizacao_efetiva=resultado['data_intimacao'],
        data_publicacao=info.get('data_publicacao'),
        data_inicio_contagem=(
            resultado.get('data_inicio_contagem')
            or info.get('data_inicio_contagem')
            or resultado['data_inicio']),
        ultimo_dia=resultado['ultimo_dia'],
        data_decurso=resultado['data_decurso'],
        evento_origem=resultado['evento_despacho'],
        evento_intimacao=resultado.get('evento_intimacao') or '',
        texto_certidao=texto or texto_certidao(resultado),
        motivo=motivo_texto or motivo(resultado),
        prazo_info=info,
        certidao_path=certidao_path,
        servidor=servidor,
        tempestivo=None,
    )


def gerar_e_registrar(resultado, servidor, servidor_cargo,
                      saida=None, nao_registrar=False):
    html, caminho = gerar_preview(
        resultado, servidor, servidor_cargo, saida=saida)
    registro = None
    if not nao_registrar:
        registro = registrar(
            resultado,
            certidao_path=caminho,
            servidor=servidor,
            texto=texto_certidao(resultado),
            motivo_texto=motivo(resultado),
        )
    return html, caminho, registro
