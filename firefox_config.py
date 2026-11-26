"""Detecção do Firefox local e captura de cookies do Projudi.

Funciona nos três cenários do projeto:

* Windows nativo (uso atual)
* WSL acessando o Firefox instalado no Windows
* Linux nativo (Ubuntu)

Todos os caminhos são resolvidos em tempo de execução. Nada aqui depende de
Django, então o módulo pode ser importado por scripts soltos (projudi_bot.py,
scripts/capture_cookies_windows.py, etc.).
"""

from __future__ import annotations

import configparser
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional

APP_DATA_DIR_NAME = 'send_of_v4'

# Nome do arquivo JSON usado como ponte entre a captura e o Django.
COOKIES_FILE_NAME = 'cookies.json'


def project_root() -> Path:
    return Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Carrega .env sem depender de Django (útil para scripts soltos)."""
    arquivo = project_root() / '.env'
    if not arquivo.is_file():
        return
    try:
        linhas = arquivo.read_text(encoding='utf-8').splitlines()
    except OSError:
        return
    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith('#') or '=' not in linha:
            continue
        chave, valor = linha.split('=', 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave:
            os.environ.setdefault(chave, valor)


_load_dotenv()

DOMAIN = os.environ.get('PROJUDI_DOMAIN', 'projudi.tjba.jus.br')


# ---------------------------------------------------------------------------
# Ambiente
# ---------------------------------------------------------------------------
def is_windows() -> bool:
    return os.name == 'nt'


def is_wsl() -> bool:
    if is_windows():
        return False
    if os.environ.get('WSL_DISTRO_NAME') or os.environ.get('WSL_INTEROP'):
        return True
    try:
        return 'microsoft' in Path('/proc/version').read_text(errors='ignore').lower()
    except OSError:
        return False


def _dedupe(paths: Iterable[Path]) -> List[Path]:
    vistos = set()
    resultado = []
    for path in paths:
        try:
            chave = str(path.expanduser().resolve()).lower()
        except OSError:
            chave = str(path.expanduser()).lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        resultado.append(path.expanduser())
    return resultado


# ---------------------------------------------------------------------------
# Firefox instalado
# ---------------------------------------------------------------------------
def _firefox_windows_candidates() -> List[Path]:
    candidatos: List[Path] = []

    try:
        import winreg

        chaves = [
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Mozilla\Mozilla Firefox'),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Mozilla\Mozilla Firefox'),
            (winreg.HKEY_CURRENT_USER, r'SOFTWARE\Mozilla\Mozilla Firefox'),
        ]
        for hive, subkey in chaves:
            try:
                with winreg.OpenKey(hive, subkey) as raiz:
                    total = winreg.QueryInfoKey(raiz)[0]
                    for indice in range(total):
                        versao = winreg.EnumKey(raiz, indice)
                        try:
                            with winreg.OpenKey(raiz, versao + r'\Main') as main:
                                instalacao, _ = winreg.QueryValueEx(
                                    main, 'Install Directory')
                                if instalacao:
                                    candidatos.append(
                                        Path(instalacao) / 'firefox.exe')
                        except OSError:
                            continue
            except OSError:
                continue
    except ImportError:
        pass

    for base in (
        os.environ.get('ProgramFiles'),
        os.environ.get('ProgramFiles(x86)'),
        os.environ.get('LOCALAPPDATA'),
    ):
        if base:
            candidatos.append(Path(base) / 'Mozilla Firefox' / 'firefox.exe')
            candidatos.append(Path(base) / 'Firefox' / 'firefox.exe')

    return candidatos


def _firefox_linux_candidates() -> List[Path]:
    candidatos = [
        Path('/usr/bin/firefox'),
        Path('/usr/local/bin/firefox'),
        Path('/snap/bin/firefox'),
        Path('/snap/firefox/current/usr/lib/firefox/firefox'),
        Path('/opt/firefox/firefox'),
        Path('/opt/firefox-esr/firefox'),
        Path('/usr/lib/firefox/firefox'),
        Path('/usr/lib/firefox-esr/firefox-esr'),
        Path('/usr/lib/firefox-esr/firefox'),
        Path.home() / '.local' / 'share' / 'flatpak' / 'app'
        / 'org.mozilla.firefox' / 'current' / 'active' / 'files'
        / 'lib' / 'firefox' / 'firefox',
    ]
    if is_wsl():
        for base in ('/mnt/c/Program Files', '/mnt/c/Program Files (x86)'):
            candidatos.append(Path(base) / 'Mozilla Firefox' / 'firefox.exe')
    return candidatos


def firefox_candidates() -> List[Path]:
    """Caminhos possíveis do executável do Firefox, na ordem de preferência."""
    candidatos: List[Path] = []

    for env_name in ('FIREFOX_PATH', 'MOZILLA_FIREFOX', 'FIREFOX_BIN'):
        valor = os.environ.get(env_name)
        if valor:
            candidatos.append(Path(valor))

    if is_windows():
        candidatos.extend(_firefox_windows_candidates())
    else:
        candidatos.extend(_firefox_linux_candidates())

    return _dedupe(candidatos)


def find_firefox() -> Optional[Path]:
    """Retorna o executável do Firefox local, ou None se não encontrado."""
    for candidato in firefox_candidates():
        try:
            if candidato.is_file():
                return candidato
        except OSError:
            continue

    # Último recurso: deixa o sistema resolver pelo PATH.
    for nome in ('firefox', 'firefox.exe', 'firefox-esr'):
        achado = shutil.which(nome)
        if achado:
            return Path(achado)
    return None


# ---------------------------------------------------------------------------
# Perfis do Firefox
# ---------------------------------------------------------------------------
def _firefox_root_dirs() -> List[Path]:
    raizes: List[Path] = []

    env_profile = os.environ.get('FIREFOX_PROFILE')
    if env_profile:
        p = Path(env_profile).expanduser()
        raizes.append(p if p.is_dir() else p.parent)

    if is_windows():
        appdata = os.environ.get('APPDATA')
        if appdata:
            raizes.append(Path(appdata) / 'Mozilla' / 'Firefox')
        raizes.append(Path.home() / 'AppData' / 'Roaming' / 'Mozilla' / 'Firefox')
    else:
        raizes.append(Path.home() / '.mozilla' / 'firefox')
        # Ubuntu: Firefox via snap e via Flatpak guardam o perfil fora do
        # ~/.mozilla padrão.
        raizes.append(
            Path.home() / 'snap' / 'firefox' / 'common' / '.mozilla' / 'firefox')
        raizes.append(
            Path.home() / '.var' / 'app' / 'org.mozilla.firefox'
            / '.mozilla' / 'firefox')

    if is_wsl():
        raizes.extend(
            Path(p).parent.parent.parent
            for p in glob.glob(
                '/mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox')
            if Path(p).is_dir()
        )

    return _dedupe(raizes)


def _profiles_from_ini(raiz: Path) -> List[Path]:
    ini = raiz / 'profiles.ini'
    if not ini.is_file():
        return []

    cfg = configparser.RawConfigParser()
    try:
        cfg.read(ini, encoding='utf-8')
    except (OSError, configparser.Error):
        return []

    # O perfil marcado como Default= na seção [Install...] é o que o
    # Firefox abre ao iniciar; deve ser consultado primeiro.
    preferidos: List[Path] = []
    for secao in cfg.sections():
        if not secao.startswith('Install'):
            continue
        caminho = cfg.get(secao, 'Default', fallback='')
        if caminho:
            candidato = raiz / caminho
            if candidato.is_dir():
                preferidos.append(candidato)

    perfis: List[Path] = list(preferidos)
    for secao in cfg.sections():
        if not secao.startswith('Profile'):
            continue
        caminho = cfg.get(secao, 'Path', fallback='')
        if not caminho:
            continue
        relativo = cfg.get(secao, 'IsRelative', fallback='1') == '1'
        candidato = raiz / caminho if relativo else Path(caminho)
        if candidato.is_dir():
            perfis.append(candidato)

    return perfis


def firefox_profiles() -> List[Path]:
    """Perfis do Firefox encontrados, do mais recente para o mais antigo.

    Um perfil cujo ``cookies.sqlite`` foi usado há menos tempo tem prioridade.
    Isso evita pegar um perfil antigo (por exemplo ``default``) quando o
    usuário está logado no ``default-release``.
    """
    perfis: List[Path] = []

    env_profile = os.environ.get('FIREFOX_PROFILE')
    if env_profile:
        p = Path(env_profile).expanduser()
        perfis.append(p if p.is_dir() else p.parent)

    for raiz in _firefox_root_dirs():
        perfis.extend(_profiles_from_ini(raiz))
        pasta = raiz / 'Profiles'
        if pasta.is_dir():
            perfis.extend(sorted(p for p in pasta.iterdir() if p.is_dir()))

        if is_wsl():
            for caminho in glob.glob(
                '/mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox/Profiles/*'
            ):
                p = Path(caminho)
                if p.is_dir():
                    perfis.append(p)

    perfis = _dedupe(perfis)

    def _mtime(perfil: Path) -> float:
        arquivo = perfil / 'cookies.sqlite'
        try:
            return arquivo.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(perfis, key=_mtime, reverse=True)


def default_firefox_profile() -> Optional[Path]:
    perfis = firefox_profiles()
    return perfis[0] if perfis else None


# ---------------------------------------------------------------------------
# Arquivo JSON de cookies (ponte captura <-> Django)
# ---------------------------------------------------------------------------
def _app_data_dir() -> Path:
    if is_windows():
        base = os.environ.get('LOCALAPPDATA')
        if base:
            return Path(base) / APP_DATA_DIR_NAME
        return Path.home() / 'AppData' / 'Local' / APP_DATA_DIR_NAME
    base = os.environ.get('XDG_DATA_HOME')
    if base:
        return Path(base) / APP_DATA_DIR_NAME
    return Path.home() / '.local' / 'share' / APP_DATA_DIR_NAME


def cookies_file_candidates() -> List[Path]:
    """Locais onde o JSON de cookies pode estar (leitura e escrita)."""
    caminhos: List[Path] = []

    env_file = os.environ.get('PROJUDI_COOKIES_FILE')
    if env_file:
        caminhos.append(Path(env_file).expanduser())

    caminhos.append(_app_data_dir() / COOKIES_FILE_NAME)
    caminhos.append(project_root() / 'var' / 'projudi' / COOKIES_FILE_NAME)

    if is_windows():
        caminhos.append(Path('D:/Projudi') / COOKIES_FILE_NAME)
        caminhos.append(Path('C:/Projudi') / COOKIES_FILE_NAME)

    if is_wsl():
        caminhos.append(Path('/mnt/d/Projudi') / COOKIES_FILE_NAME)
        caminhos.append(Path('/mnt/c/Projudi') / COOKIES_FILE_NAME)

    caminhos.append(Path.home() / '.projudi_cookies.json')
    if not is_windows():
        caminhos.append(Path('/tmp') / 'projudi_cookies.json')

    return _dedupe(caminhos)


def preferred_cookies_file() -> Path:
    """Caminho onde novos cookies devem ser gravados."""
    existentes = [p for p in cookies_file_candidates() if p.is_file()]
    if existentes:
        return max(existentes, key=lambda p: p.stat().st_mtime)

    for candidato in cookies_file_candidates():
        try:
            candidato.parent.mkdir(parents=True, exist_ok=True)
            return candidato
        except OSError:
            continue
    return _app_data_dir() / COOKIES_FILE_NAME


def _normalizar_cookies(dados) -> Dict[str, str]:
    if isinstance(dados, dict):
        return {str(k): str(v) for k, v in dados.items() if v is not None}
    if isinstance(dados, list):
        cookies = {}
        for item in dados:
            if isinstance(item, dict) and item.get('name'):
                cookies[str(item['name'])] = str(item.get('value', ''))
        return cookies
    return {}


def read_cookies(caminho: Optional[os.PathLike | str] = None) -> Dict[str, str]:
    """Lê o primeiro JSON de cookies válido encontrado."""
    caminhos = [Path(caminho)] if caminho else cookies_file_candidates()
    for p in caminhos:
        try:
            if not p.is_file():
                continue
            dados = json.loads(p.read_text(encoding='utf-8'))
            cookies = _normalizar_cookies(dados)
            if cookies:
                return cookies
        except (OSError, ValueError, UnicodeDecodeError):
            continue
    return {}


def write_cookies(
    cookies: Dict[str, str],
    caminho: Optional[os.PathLike | str] = None,
) -> Path:
    destino = Path(caminho) if caminho else preferred_cookies_file()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(cookies, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    return destino


# ---------------------------------------------------------------------------
# Captura direta do cookies.sqlite do Firefox
# ---------------------------------------------------------------------------
def read_firefox_sqlite(cookies_sqlite: Path, domain: str = DOMAIN) -> Dict[str, str]:
    """Lê moz_cookies copiando antes o banco + WAL + SHM.

    O Firefox mantém os cookies recém-criados no arquivo ``-wal`` enquanto
    está aberto. Copiar apenas o ``cookies.sqlite`` faz o JSESSIONID sumir.
    """
    with tempfile.TemporaryDirectory(prefix='projudi-cookies-') as tmpdir:
        destino = Path(tmpdir) / 'cookies.sqlite'
        for sufixo in ('', '-wal', '-shm'):
            origem = Path(str(cookies_sqlite) + sufixo)
            if origem.is_file():
                shutil.copy2(origem, Path(str(destino) + sufixo))

        conexao = sqlite3.connect(str(destino))
        try:
            linhas = conexao.execute(
                'SELECT name, value FROM moz_cookies WHERE host LIKE ?',
                (f'%{domain}%',),
            ).fetchall()
        finally:
            conexao.close()

    return {str(nome): str(valor) for nome, valor in linhas}


def capture_cookies_from_profiles(domain: str = DOMAIN) -> Dict[str, str]:
    """Junta os cookies de todos os perfis, priorizando quem tem JSESSIONID."""
    encontrados: Dict[str, str] = {}

    for perfil in firefox_profiles():
        arquivo = perfil / 'cookies.sqlite'
        if not arquivo.is_file():
            continue
        try:
            cookies = read_firefox_sqlite(arquivo, domain)
        except (OSError, sqlite3.Error):
            continue
        if not cookies:
            continue
        if 'JSESSIONID' in cookies:
            return cookies
        for nome, valor in cookies.items():
            encontrados.setdefault(nome, valor)

    return encontrados


def capture_cookies(domain: str = DOMAIN) -> Dict[str, str]:
    """Captura cookies do Firefox local, com fallback para browser_cookie3."""
    cookies = capture_cookies_from_profiles(domain)

    if 'JSESSIONID' not in cookies:
        try:
            import browser_cookie3

            jar = browser_cookie3.firefox(domain_name=domain)
            for cookie in jar:
                cookies.setdefault(cookie.name, cookie.value)
        except Exception:
            pass

    return cookies


def capture_and_save(domain: str = DOMAIN) -> tuple[Dict[str, str], Path]:
    cookies = capture_cookies(domain)
    if cookies:
        destino = write_cookies(cookies)
    else:
        destino = preferred_cookies_file()
    return cookies, destino


def describe_environment() -> Dict[str, object]:
    """Diagnóstico usado pelos comandos/scripts de suporte."""
    return {
        'plataforma': sys.platform,
        'windows': is_windows(),
        'wsl': is_wsl(),
        'firefox': str(find_firefox() or ''),
        'perfil': str(default_firefox_profile() or ''),
        'perfis': [str(p) for p in firefox_profiles()],
        'arquivo_cookies': str(preferred_cookies_file()),
    }


if __name__ == '__main__':
    import pprint

    pprint.pprint(describe_environment())
    _cookies = capture_cookies()
    print(f'cookies encontrados: {len(_cookies)} '
          f'(JSESSIONID: {"sim" if "JSESSIONID" in _cookies else "nao"})')
