"""
expedir_oficio_windows.py - Roda no Windows nativo

Expede Ofícios no Projudi via Selenium.

Requisitos:
    pip install selenium webdriver-manager

Uso:
    python scripts/expedir_oficio_windows.py
    python scripts/expedir_oficio_windows.py --codigo 581
    python scripts/expedir_oficio_windows.py --processo 41020261733480
    python scripts/expedir_oficio_windows.py --observacao "Ofício ref. sentença"
"""

import argparse, json, time, random, re, sys
from pathlib import Path
from datetime import datetime

COOKIES_PATH = Path("D:/Projudi/cookies.json")


def pausa(min_s=0.8, max_s=2.5):
    time.sleep(random.uniform(min_s, max_s))


def digitar(texto, elemento):
    for letra in texto:
        elemento.send_keys(letra)
        time.sleep(random.uniform(0.02, 0.07))


def main():
    parser = argparse.ArgumentParser(description="Expede Ofício no Projudi via Selenium")
    parser.add_argument("--codigo", default="581", help="Código da movimentação (default: 581)")
    parser.add_argument("--processo", default="41020261733480", help="Número Projudi do processo")
    parser.add_argument("--observacao", default="", help="Texto da observação")
    parser.add_argument("--oficio-numero", default="", help="Número do ofício (ex: 001/2026)")
    parser.add_argument("--destinatario", default="", help="Nome do destinatário")
    parser.add_argument("--html", default="", help="Caminho do arquivo HTML do ofício (opcional)")
    args = parser.parse_args()

    # Carrega cookies
    if not COOKIES_PATH.exists():
        print(f"[ERRO] Cookies nao encontrados em {COOKIES_PATH}")
        print("       Rode primeiro: python scripts/capture_cookies_windows.py")
        return 1

    with open(COOKIES_PATH) as f:
        cookies = json.load(f)

    if "JSESSIONID" not in cookies:
        print("[ERRO] JSESSIONID nao encontrado. Faca login no Projudi e capture os cookies.")
        return 1

    print(f"[OK] Cookies carregados: {list(cookies.keys())}")

    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.firefox import GeckoDriverManager

    options = Options()

    driver = webdriver.Firefox(
        service=Service(GeckoDriverManager().install()),
        options=options
    )
    wait = WebDriverWait(driver, 30)

    try:
        driver.set_window_size(random.randint(1200, 1400), random.randint(700, 900))

        # Abre domínio e injeta cookies
        driver.get("https://projudi.tjba.jus.br/projudi/")
        for name, value in cookies.items():
            try:
                driver.add_cookie({"name": name, "value": value, "path": "/"})
            except:
                pass
        pausa()

        # Navega para movimentação
        url = f"https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso={args.processo}"
        print(f"[INFO] Abrindo: {url}")
        driver.get(url)
        pausa(1.5, 3)

        # 1. Preenche código da movimentação
        print("[1/6] Preenchendo código...")
        codigo = wait.until(EC.presence_of_element_located((By.ID, "seqCategoriaMovimentacao")))
        codigo.clear()
        digitar(args.codigo, codigo)
        pausa()

        # 2. Clica em Buscar
        print("[2/6] Buscando movimentação...")
        btn_busca = wait.until(EC.element_to_be_clickable((By.ID, "btnBuscaMovimentacao")))
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", btn_busca)
        pausa_curta()
        btn_busca.click()

        # Aguarda grid carregar
        pausa(1, 3)

        # 3. Seleciona "Ofício" na grid de resultados
        print("[3/6] Selecionando Ofício na grid...")
        try:
            # Tenta achar radio button na linha que contém "Ofício"
            radio = driver.find_element(
                By.XPATH,
                "//tr[contains(td, 'Ofício') or contains(td, 'Oficio')]//input[@type='radio']"
            )
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", radio)
            pausa_curta()
            radio.click()
            print("       Ofício selecionado!")
        except Exception:
            print("       Radio nao encontrado, tentando fallback...")
            try:
                # Tenta clicar no texto "Ofício"
                driver.find_element(By.XPATH, "//td[contains(text(), 'Ofício')]").click()
            except Exception:
                print("       Fallback falhou - continuando mesmo assim")

        pausa()

        # 4. Preenche observação
        print("[4/6] Preenchendo observação...")
        wait.until(lambda d: d.find_element(By.ID, "observacao").is_enabled())
        obs = wait.until(EC.presence_of_element_located((By.ID, "observacao")))
        obs.clear()
        obs_texto = args.observacao or f"Ofício {args.oficio_numero} - {args.destinatario}".strip(", -")
        digitar(obs_texto, obs)
        pausa()

        # 5. Scroll e Concluir
        print("[5/6] Concluindo...")
        driver.execute_script("window.scrollBy(0, 300);")
        pausa()

        concluir = wait.until(EC.element_to_be_clickable((By.ID, "Concluir")))
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", concluir)
        pausa_curta()
        concluir.click()

        # 6. Aceita alerta se houver
        pausa()
        try:
            alert = WebDriverWait(driver, 10).until(EC.alert_is_present())
            print(f"[6/6] Alerta: {alert.text}")
            alert.accept()
        except Exception:
            print("[6/6] Sem alerta (pode ter ido direto)")

        pausa(1, 3)
        print(f"\n[URL FINAL] {driver.current_url}")

        if "DadosProcesso" in driver.current_url or "Historico" in driver.current_url:
            print("\n[SUCESSO] Movimentacao criada!")
        else:
            print("\n[AVISO] Verifique se a movimentacao foi criada manualmente.")

        # Opcional: substituir HTML do ofício
        if args.html and Path(args.html).exists():
            print("\n[INFO] Substituindo HTML do ofício no CumprimentoCartorio...")
            with open(args.html, encoding="utf-8") as f:
                html_content = f.read()
            substituir_html(driver, wait, args.processo, html_content)

    except Exception as e:
        print(f"\n[ERRO] {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        input("\nPressione Enter para fechar o navegador...")
        driver.quit()

    return 0


def substituir_html(driver, wait, proc_number, html_content):
    """Navega ate o oficio no CumprimentoCartorio e substitui o HTML."""
    url_expedidos = (
        f"https://projudi.tjba.jus.br/projudi/listagens/"
        f"CumprimentoCartorio?tipo=oficio&acao=expedidos"
    )
    driver.get(url_expedidos)
    pausa(2, 4)

    # Procura pelo numero do processo
    links = driver.find_elements(By.PARTIAL_LINK_TEXT, proc_number[:15])
    if not links:
        print("       Oficio nao encontrado no CumprimentoCartorio")
        return

    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", links[0])
    pausa()
    links[0].click()
    pausa(2, 4)

    try:
        btn_fonte = wait.until(EC.element_to_be_clickable((By.ID, "btnCodigoFonte")))
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", btn_fonte)
        pausa()
        btn_fonte.click()
        pausa()

        fonte = wait.until(EC.presence_of_element_located((By.ID, "codigoFonte")))
        fonte.clear()
        digitar(html_content, fonte)
        pausa()

        btn_salvar = wait.until(EC.element_to_be_clickable((By.ID, "btnSalvarCodigoFonte")))
        btn_salvar.click()
        pausa(1, 3)
        print("       HTML do oficio substituido!")
    except Exception as e:
        print(f"       Erro ao substituir HTML: {e}")


def pausa_curta():
    time.sleep(random.uniform(0.3, 1.2))


if __name__ == "__main__":
    sys.exit(main())
