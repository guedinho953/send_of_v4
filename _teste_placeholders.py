"""Teste do preenchimento dinâmico de placeholders de evento no rag_router."""
import re

def _extrair_eventos(texto: str) -> list:
    if not texto:
        return []
    eventos = []
    for m in re.finditer(r'evento\s*([^.\n;,]{0,40})', texto, re.IGNORECASE):
        trecho = m.group(1).strip()
        nums = re.findall(r'\d+', trecho)
        eventos.extend(nums)
    vistos = set()
    resultado = []
    for e in eventos:
        if e not in vistos:
            vistos.add(e)
            resultado.append(e)
    return resultado

def _preencher_eventos_observacao(obs: str, texto: str) -> str:
    if not obs or not texto:
        return obs
    eventos = _extrair_eventos(texto)
    if not eventos:
        return (obs.replace('{{evento_autora}}', '')
                   .replace('{{eventos_reus}}', '')
                   .replace('{{evento}}', '')
                   .replace('{{eventos}}', '').strip())
    primeiro = eventos[0]
    restantes = eventos[1:]
    todos = ' e '.join(eventos)
    res = ' e '.join(restantes) if restantes else ''
    obs = (obs.replace('{{evento_autora}}', primeiro)
              .replace('{{eventos_reus}}', res)
              .replace('{{evento}}', primeiro)
              .replace('{{eventos}}', todos))
    obs = re.sub(r'\s{2,}', ' ', obs).replace('  ', ' ').strip()
    return obs

OBS = ('Intime-se a parte autora para ciência do evento {{evento_autora}}. '
       'Intime-se a(s) parte(s) ré(s) para ciência dos eventos indicados '
       'nos autos {{eventos_reus}}')

testes = [
    ('Intime-se para juntar petição do evento 94',
     'um evento'),
    ('Intime-se para juntar petição do evento 94 e intime os eventos 25 e 26',
     'dois eventos'),
    ('Intime-se para juntar petição do evento retro',
     'evento retro (sem número)'),
    ('DESPACHO normal sem eventos aqui',
     'sem eventos'),
    ('... evento 120 ... eventos indicados autos',
     'múltiplos eventos'),
]

for texto, desc in testes:
    eventos = _extrair_eventos(texto)
    obs_final = _preencher_eventos_observacao(OBS, texto)
    print('=== %s ===' % desc)
    print('  Texto: %s' % texto)
    print('  Eventos: %s' % eventos)
    print('  Obs final: %s' % obs_final)
    print()
