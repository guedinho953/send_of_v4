import re


def mask_cpf(cpf):
    if not cpf or len(cpf) < 11:
        return cpf
    return f'***.{cpf[3:7]}.' + cpf[-2:] + '**'


def mask_phone(phone):
    if not phone or len(phone) < 8:
        return phone
    return phone[:3] + '****' + phone[-2:]


def mask_email(email):
    if not email or '@' not in email:
        return email
    user, domain = email.split('@')
    if len(user) <= 2:
        return f'**@{domain}'
    return f'{user[0]}**{user[-1]}@{domain}'


def normalize_process_number(number):
    return re.sub(r'[^\d]', '', number)


def format_process_number(number):
    digits = normalize_process_number(number)
    if len(digits) == 20:
        return f'{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13:14]}.{digits[14:16]}.{digits[16:20]}'
    return number
