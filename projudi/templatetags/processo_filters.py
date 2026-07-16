import re
from django import template

register = template.Library()


@register.filter
def formatar_processo(numero):
    """
    Formata numero do processo no padrao CNJ.
    Aceita tanto 20 digitos completos quanto numeros ja formatados.
    """
    if not numero:
        return ''
    
    numero_str = str(numero).strip()
    
    # Se ja estiver formatado, retorna como esta
    if '.' in numero_str and '-' in numero_str:
        return numero_str
    
    # Remove tudo que nao for digito
    digits = re.sub(r'\D', '', numero_str)
    
    if len(digits) >= 20:
        # Formato completo CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO
        return f"{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13:14]}.{digits[14:16]}.{digits[16:20]}"
    
    # Se tiver 14 digitos (formato interno Projudi), tenta formatar como CNJ
    # Nota: isso cria um formato visual, mas pode nao ser o numero CNJ real
    if len(digits) == 14:
        return f"{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13:14]}.{digits[14:16]}.{digits[16:]}"
    
    # Fallback: retorna original
    return numero_str
