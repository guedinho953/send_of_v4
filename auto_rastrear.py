#!/usr/bin/env python3
"""Loop de auto-rastreamento de movimentações a cada 5 minutos.
Uso:
  python auto_rastrear.py          # Iniciar loop
  python auto_rastrear.py --stop   # Parar loop
  python auto_rastrear.py --status # Verificar se está rodando
"""
import os, sys, time, json, signal

PID_FILE = '/tmp/auto_rastrear.pid'

def _pid_info():
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

def esta_rodando():
    info = _pid_info()
    if not info:
        return False
    pid = info.get('pid')
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        os.remove(PID_FILE)
        return False

def iniciar():
    if esta_rodando():
        print('❌ Auto-rastrear já está rodando')
        return

    os.chdir('/home/ivan/PythonProjects/send_of_v4')
    os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
    os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'

    pid = os.getpid()
    with open(PID_FILE, 'w') as f:
        json.dump({'pid': pid, 'started': time.time()}, f)

    print(f'✅ Auto-rastrear iniciado (PID {pid}, a cada 5 min)')
    print(f'   Para parar: python auto_rastrear.py --stop')

    try:
        while True:
            print(f'\n[{time.strftime("%d/%m/%Y %H:%M")}] 🔍 Rastreando...')
            os.system(f'{sys.executable} expedir_rapido.py 2>&1')
            print(f'[{time.strftime("%d/%m/%Y %H:%M")}] ⏳ Aguardando 5 min...')
            time.sleep(300)
    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        print('\n👋 Auto-rastrear parado')

def parar():
    info = _pid_info()
    if not info:
        print('⚠️ Auto-rastrear não está rodando')
        return
    pid = info['pid']
    try:
        os.kill(pid, signal.SIGTERM)
        print(f'✅ Auto-rastrear parado (PID {pid})')
    except ProcessLookupError:
        print('⚠️ Processo já encerrado')
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

def status():
    if esta_rodando():
        info = _pid_info()
        rodando_desde = time.strftime('%d/%m/%Y %H:%M', time.localtime(info['started']))
        print(f'✅ Rodando (PID {info["pid"]} desde {rodando_desde})')
    else:
        print('⏹️ Parado')

if __name__ == '__main__':
    if '--stop' in sys.argv:
        parar()
    elif '--status' in sys.argv:
        status()
    else:
        iniciar()
