"""
Busca os atos (movimentações) de um processo no Projudi e salva no banco
(Process + Movement), prontos para alimentar o ComunicacaoTracker / certidão
de prazo.

Uso:
  python manage.py shell < scripts/pegar_atos_processo.py
  # ou: python scripts/pegar_atos_processo.py --interno 41020263379522

Exemplo:
  python scripts/pegar_atos_processo.py --interno 41020263379522
"""
import re, sys, json, os
from datetime import datetime

# Bootstrap Django p/ rodar como script direto (python scripts/pegar_atos_processo.py)
if os.environ.get('DJANGO_SETTINGS_MODULE') is None:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _BASE not in sys.path:
        sys.path.insert(0, _BASE)
    os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
import django
django.setup()

def run(interno: str, salvar: bool = True):
    from django.conf import settings
    if str(settings.BASE_DIR) not in sys.path:
        sys.path.insert(0, str(settings.BASE_DIR))

    from accounts.models import User
    from projudi.services import ProjudiService
    from projudi.models import CumprimentoRecord
    from processes.models import Process, Movement

    user = User.objects.filter(is_active=True).first()
    if not user:
        print('ERRO: nenhum usuario ativo'); return None

    cr = (CumprimentoRecord.objects.filter(processo=interno).first()
          or CumprimentoRecord.objects.filter(numero_processo_cnj__icontains=interno).first())
    cnj = (cr.numero_processo_cnj if cr else None) or interno
    print(f'[OK] usuario={user.email}  CR interno={interno} cnj={cnj}')

    service = ProjudiService(user=user)
    sess = service._get_session_from_cookies()
    if not sess:
        print('ERRO: sem sessao Projudi (cookies). Rode capture_cookies.'); return None
    sess = sess[0] if isinstance(sess, tuple) else sess

    warm = sess.get('https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao')
    if warm.status_code != 200 or 'expirou' in warm.text.lower() or len(warm.text) < 1000:
        print('ERRO: sessao Projudi expirada'); return None
    print('[OK] sessao ativa')

    url = (f'https://projudi.tjba.jus.br/projudi/listagens/'
           f'DadosProcesso?numeroProcesso={interno}')
    r = sess.get(url)
    if r.status_code != 200 or len(r.text) < 500:
        print(f'ERRO: pagina {r.status_code}'); return None
    print(f'[OK] pagina DadosProcesso baixada ({len(r.text)} bytes)')

    from projudiProcessNavigator import ProcessoParser
    try:
        parser = ProcessoParser(r.text)
        movs, raw = parser.extrair_movimentacoes()
        partes = parser.extrair_partes(parser.soup) if hasattr(parser, 'soup') else []
    except Exception as e:
        import traceback; traceback.print_exc()
        print('ERRO parser:', e); return None

    print(f'\n[OK] {len(movs)} atos extraidos | {len(partes)} partes')
    print('='*90)
    for m in movs:
        dest = m.get('destinatario')
        if isinstance(dest, dict):
            dest_nome = dest.get('nome', '')
        elif isinstance(dest, list):
            dest_nome = ', '.join(str(d) for d in dest)
        else:
            dest_nome = str(dest or '')
        print(
            f"ev={m.get('evento',''):>5} | {m.get('data_texto',''):>8} | "
            f"cat={str(m.get('categoria',''))[:10]:<10} | sit={str(m.get('situacao_comunicacao','')):<9} | "
            f"meio={str(m.get('meio_comunicacao',''))[:11]:<11} | ref={str(m.get('evento_referenciado','')):<6} | "
            f"prazo={m.get('prazo_dias_ev_ref')} | djen={str(m.get('data_djen',''))[:10]:<10} | "
            f"leitura={str(m.get('data_leitura',''))[:10]:<10} | dest={dest_nome[:22]}"
        )
        print(f"      ato: {m.get('ato','')[:120]}")
        if m.get('observacao'):
            print(f"      obs: {m.get('observacao','')[:160]}")
    print('='*90)

    if not salvar:
        print('[SKIP] sem salvar (salvar=False)')
        return movs

    # ── Salvar Process + Movements ──
    proc_obj, _ = Process.objects.get_or_create(
        number=cnj,
        tenant=user.tenant,
        defaults={
            'number_normalized': re.sub(r'\D', '', cnj),
            'status': 'analyzing',
            'projudi_url': url,
            'assigned_to': user,
        },
    )
    def parse_data(texto):
        if not texto: return None
        if isinstance(texto, datetime): return texto.date()
        for fmt in ('%d/%m/%y', '%d/%m/%Y', '%Y-%m-%d'):
            try: return datetime.strptime(str(texto).strip(), fmt).date()
            except ValueError: pass
        return None

    def baixar_doc_texto(url, max_chars=6000):
        """Baixa o HTML do documento anexado e devolve o texto limpo.

        Usa o MESMO DocumentAnalyzer.extrair_texto_documento do fluxo
        expedir_oficio_ciap (corta cabeçalho/rodapé, pega o despacho).
        O parser minúsculiza a href; 'downloadarquivo' (minúsculo) dá 404,
        o correto é 'DownloadArquivo' (maiúsculo).
        """
        url = url.replace('/downloadarquivo?', '/DownloadArquivo?')
        try:
            rr = sess.get(url, timeout=20)
            if rr.status_code != 200 or len(rr.content) < 50:
                return None, None
            # ── PDF: extrai o texto com PyMuPDF ──
            if rr.content.lstrip().startswith(b'%PDF'):
                try:
                    import fitz
                    doc = fitz.open(stream=rr.content, filetype='pdf')
                    texto = '\n'.join(
                        pg.get_text() for pg in doc if pg.get_text())
                    texto = re.sub(r'\s+', ' ', texto).strip()
                    return (texto[:max_chars] or None), 'PDF'
                except Exception:
                    return None, None
            # ── HTML: mesma limpeza do DocumentAnalyzer.extrair_texto_documento
            # do fluxo expedir_oficio_ciap (o módulo não importa por causa do
            # projudi_command_analyzer inexistente → replicado inline). ──
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(rr.text, 'html.parser')
            for tag in soup(['script', 'style', 'head', 'meta', 'noscript']):
                tag.decompose()
            texto = soup.get_text(separator='\n')
            texto = re.sub(r'(\w+)\n(\w+)', r'\1\2', texto)
            texto = re.sub(r'\n+', '\n', texto)
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = re.sub(
                r'(DESPACHO|SENTENÇA|DECISÃO|FORÇA DE MANDADO)',
                r'\n\1\n', texto, flags=re.IGNORECASE)
            inicio = re.search(
                r'(DESPACHO|SENTENÇA|DECISÃO|FORÇA DE MANDADO)',
                texto, re.IGNORECASE)
            if inicio:
                texto = texto[inicio.start():]
            fim = re.search(r'Documento Assinado Eletronicamente',
                            texto, re.IGNORECASE)
            if fim:
                texto = texto[:fim.start()]
            texto = texto.replace('\x00', '')  # NUL quebra psycopg2
            texto = re.sub(r'\s+', ' ', texto).strip()
            if (len(texto) < 20
                    or texto.lstrip().startswith('%PDF')  # binário PDF
                    or texto.lstrip().startswith('%{\x00')  # binário
                    or sum(ord(c) < 32 for c in texto[:200]) > 20):  # altamente binário
                return None, None
            return texto[:max_chars] or None, rr.text[:200]
        except Exception:
            return None, None

    created = updated = 0
    for m in movs:
        dest = m.get('destinatario')
        if isinstance(dest, dict):
            dest_nome = dest.get('nome', '')
        elif isinstance(dest, list):
            dest_nome = ', '.join(str(d) for d in dest)
        else:
            dest_nome = str(dest or '')
        data_obj = m.get('data_obj')
        if isinstance(data_obj, str):
            data_obj = parse_data(data_obj)

        obs = m.get('observacao', '') or ''
        doc_url = ''
        docs = m.get('documentos') or []
        # Baixa o (primeiro) documento anexado p/ ler o conteúdo do ato
        # (despacho/decisão referenciada está no HTML, não no resumo do ato).
        for d in docs:
            url_doc = d.get('url', '')
            if not url_doc:
                continue
            if not doc_url:
                doc_url = url_doc.replace('/downloadarquivo?', '/DownloadArquivo?')
            texto_doc, _ = baixar_doc_texto(url_doc)
            if texto_doc:
                obs = (obs + f"\n\n\[DOC: {d.get('nome','')}]\n{texto_doc}").strip()
                break  # 1 documento basta p/ contexto

        defaults = {
            'tenant': user.tenant,
            'process': proc_obj,
            'act_description': m.get('ato', '') or '',
            'act_normalized': m.get('ato_normalizado', '') or '',
            'act_date': data_obj or parse_data(m.get('data_texto')),
            'reading_date': parse_data(m.get('data_leitura')) if m.get('data_leitura') else None,
            'reference_date': (parse_data(m.get('data_djen'))
                               if m.get('data_djen')
                               else (parse_data(m.get('data_referencia'))
                                     if m.get('data_referencia') else None)),
            'author': m.get('autor', '') or '',
            'category': (m.get('categoria') or 'outro'),
            'communication_status': (m.get('situacao_comunicacao') or ''),
            'communication_means': (m.get('meio_comunicacao') or ''),
            'recipient': (dest_nome or '')[:200],
            'observation': obs,
            'deadline_days': m.get('prazo_dias_ev_ref'),
            'referenced_event': str(m.get('evento_referenciado') or '')[:200],
            'document_url': doc_url,
        }
        mv, is_new = Movement.objects.update_or_create(
            process=proc_obj,
            tenant=user.tenant,
            event_number=str(m.get('evento', '')),
            defaults=defaults,
        )
        if is_new: created += 1
        else: updated += 1

    print(f'\n[OK] Mov  criados={created} atualizados={updated}  Process id={proc_obj.id}')
    print(f'[OK] Procurar no admin /processes/process/{proc_obj.id}/')
    return movs

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--interno', default='41020263379522')
    ap.add_argument('--nao-salvar', action='store_true')
    a = ap.parse_args()
    run(a.interno, salvar=not a.nao_salvar)
