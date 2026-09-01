import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)


def mask(value: str) -> str:
    """
    Masking secret agar tidak tampil penuh di log.
    """
    if not value:
        return "(kosong)"

    if len(value) <= 8:
        return "***"

    return f"{value[:4]}...{value[-4:]}"


def get_env(key: str) -> str:
    """
    Ambil environment variable dan bersihkan spasi/quote berlebih.
    """
    value = os.getenv(key, "")
    return value.strip().strip('"').strip("'")


def check_env():
    """
    Cek variable environment penting.
    """
    print("=== Cek Environment ===")

    required_keys = [
        "TELEGRAM_BOT_TOKEN",
        "OPENCODE_API_KEY",
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DATABASE"
    ]

    optional_keys = [
        "ADMIN_CHAT_ID",
    ]

    ok = True

    for key in required_keys:
        value = get_env(key)
        if not value:
            print(f"[ERROR] {key} masih kosong")
            ok = False
        else:
            print(f"[OK] {key} terisi: {mask(value)}")

    for key in optional_keys:
        value = get_env(key)
        if not value:
            print(f"[WARN] {key} masih kosong. Ini bisa diisi nanti.")
        else:
            print(f"[OK] {key} terisi: {mask(value)}")

    return ok


def check_telegram(token: str):
    """
    Cek token Telegram dengan endpoint getMe.
    """
    print("")
    print("=== Cek Telegram Bot ===")

    if not token:
        print("[ERROR] TELEGRAM_BOT_TOKEN kosong")
        return False

    url = f"https://api.telegram.org/bot{token}/getMe"

    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)

        if data.get("ok"):
            result = data.get("result", {})
            username = result.get("username", "")
            first_name = result.get("first_name", "")
            print(f"[OK] Telegram token valid")
            print(f"[OK] Bot name: {first_name}")
            print(f"[OK] Bot username: @{username}")
            return True

        print("[ERROR] Respons Telegram tidak ok")
        return False

    except urllib.error.HTTPError as err:
        print(f"[ERROR] Telegram HTTP error: {err.code}")
        return False
    except urllib.error.URLError as err:
        print(f"[ERROR] Tidak bisa mengakses Telegram API: {err.reason}")
        return False
    except Exception as err:
        print(f"[ERROR] Telegram check gagal: {err}")
        return False


def check_opencode(api_key: str):
    """
    Cek Opencode API key.
    Karena endpoint model openai-compatible bervariasi, kita hanya cek ketersediaan API key.
    """
    print("")
    print("=== Cek Opencode API ===")

    if not api_key:
        print("[ERROR] OPENCODE_API_KEY kosong")
        return False
        
    print("[OK] OPENCODE_API_KEY terisi")
    return True


def main():
    print("=== KOMPU Report Automation - Fase 2 Check Integrasi ===")
    print("")

    env_ok = check_env()

    telegram_token = get_env("TELEGRAM_BOT_TOKEN")
    opencode_key = get_env("OPENCODE_API_KEY")

    telegram_ok = check_telegram(telegram_token)
    opencode_ok = check_opencode(opencode_key)

    print("")
    print("=== Ringkasan ===")
    print(f"Environment      : {'OK' if env_ok else 'ADA MASALAH'}")
    print(f"Telegram         : {'OK' if telegram_ok else 'ADA MASALAH'}")
    print(f"Opencode         : {'OK' if opencode_ok else 'ADA MASALAH'}")

    if env_ok and telegram_ok and opencode_ok:
        print("")
        print("[SUCCESS] Fase 2 siap lanjut ke Fase 3.")
        return 0

    print("")
    print("[FAILED] Masih ada konfigurasi yang perlu diperbaiki.")
    return 1


if __name__ == "__main__":
    sys.exit(main())