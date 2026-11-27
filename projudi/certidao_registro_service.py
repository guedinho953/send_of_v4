"""Registro unificado de certidões (ponte entre os modelos existentes)."""

from __future__ import annotations

from pathlib import Path

from .models import CertidaoRegistro


def _origem_documento(doc):
    recipient = (getattr(doc, 'recipient_name', '') or '')
    template = getattr(getattr(doc, 'template', None), 'name', '') or ''
    alvo = f'{recipient} {template}'.upper()
    if recipient.startswith('Petição:') or 'RECURSO INOMINADO' in alvo:
        return 'peticao'
    return 'movimentacao'


def registrar_decurso(user, resultado, doc, servidor='', servidor_cargo=''):
    """Cria o registro unificado para uma certidão de decurso."""
    existente = CertidaoRegistro.objects.filter(
        generated_document=doc).first()
    if existente:
        return existente
    return CertidaoRegistro.objects.create(
        tenant=getattr(user, 'tenant', None),
        user=user,
        processo=resultado.get('processo', ''),
        numero_processo_cnj=resultado.get('processo', ''),
        parte=resultado.get('executado', ''),
        origem='movimentacao',
        tipo_prazo='decurso_pagamento',
        prazo_dias=resultado.get('dias') or 15,
        evento_despacho=str(resultado.get('evento_despacho') or ''),
        evento_intimacao=str(resultado.get('evento_intimacao') or ''),
        data_intimacao=resultado.get('data_intimacao'),
        data_inicio=resultado.get('data_inicio'),
        ultimo_dia=resultado.get('ultimo_dia'),
        data_decurso=resultado.get('data_decurso'),
        texto_certidao=doc.html_content or '',
        motivo=(
            'Certidão de decurso do pagamento voluntário. '
            f"Despacho evento {resultado.get('evento_despacho')}; "
            f"intimação evento {resultado.get('evento_intimacao')}; "
            f"decurso {resultado.get('data_decurso')}."
        ),
        generated_document=doc,
        template_used=getattr(doc, 'template', None),
        servidor=servidor,
        servidor_cargo=servidor_cargo,
        status='gerada',
        prazo_info=resultado.get('prazo_info') or {},
    )


def registrar_documento(user, doc, tipo_prazo='', origem='',
                        parte='', servidor='', servidor_cargo='',
                        status='gerada', **extra):
    """Registra um GeneratedDocument já existente."""
    existente = CertidaoRegistro.objects.filter(
        generated_document=doc).first()
    if existente:
        return existente
    origem = origem or _origem_documento(doc)
    dados = {
        'tenant': getattr(user, 'tenant', None),
        'user': user,
        'processo': doc.process.number if doc.process else '',
        'numero_processo_cnj': doc.process.number if doc.process else '',
        'parte': parte,
        'origem': origem,
        'tipo_prazo': tipo_prazo,
        'texto_certidao': doc.html_content or '',
        'generated_document': doc,
        'template_used': getattr(doc, 'template', None),
        'rag_example': getattr(doc, 'rag_example', None),
        'servidor': servidor,
        'servidor_cargo': servidor_cargo,
        'status': status,
        'prazo_info': extra.pop('prazo_info', {}) or {},
    }
    dados.update({
        k: v for k, v in extra.items()
        if v is not None
    })
    return CertidaoRegistro.objects.create(**dados)


def sincronizar_documento(doc, status=None, **campos):
    """Atualiza o registro ligado a um GeneratedDocument, se existir."""
    qs = CertidaoRegistro.objects.filter(generated_document=doc)
    registro = qs.order_by('-created_at').first()
    if not registro:
        return None
    if status:
        registro.status = status
    for campo, valor in campos.items():
        if hasattr(registro, campo) and valor is not None:
            setattr(registro, campo, valor)
    registro.save()
    return registro


def html_do_registro(registro):
    """HTML da certidão, preferindo o documento gerado."""
    doc = getattr(registro, 'generated_document', None)
    if doc and (doc.html_content or '').strip():
        return doc.html_content
    if (registro.texto_certidao or '').strip():
        return registro.texto_certidao
    caminho = Path(registro.preview_path or '')
    if caminho.is_file():
        try:
            return caminho.read_text(encoding='utf-8')
        except OSError:
            pass
    return ''
