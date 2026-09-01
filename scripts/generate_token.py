from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]
BASE_DIR = Path(__file__).resolve().parents[1]

def main() -> None:
    secrets_path = BASE_DIR / "credentials" / "client_secrets.json"
    if not secrets_path.exists():
        print(f"Error: {secrets_path} tidak ditemukan.")
        return

    print("Memulai proses autentikasi Google Drive...")
    print("Salin URL otorisasi berikut dan buka di browser host Anda jika tidak terbuka otomatis.\n")
    
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    creds = flow.run_local_server(
        host="localhost",
        bind_addr="0.0.0.0",
        port=8080,
        open_browser=False
    )
    
    token_path = BASE_DIR / "credentials" / "token.json"
    with open(token_path, "w") as token_file:
        token_file.write(creds.to_json())
        
    print(f"\nSukses! Token berhasil disimpan di {token_path}")
    print("Sekarang Anda bisa menjalankan bot dengan: docker compose up -d")

if __name__ == '__main__':
    main()