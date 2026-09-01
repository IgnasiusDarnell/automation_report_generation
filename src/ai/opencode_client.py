import os
import yaml
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

class OpencodeAI:
    def __init__(self):
        api_key = os.getenv("OPENCODE_API_KEY")
        if not api_key:
            raise ValueError("OPENCODE_API_KEY not set")
            
        base_url = os.getenv("OPENCODE_BASE_URL")
        
        # Membaca konfigurasi dari settings.yaml
        with open("config/settings.yaml", "r", encoding="utf-8") as f:
            settings = yaml.safe_load(f)
        self.model_name = settings.get("ai", {}).get("model", "minmaxm3")
        
        # Inisialisasi OpenAI client
        # Jika base_url diset, akan override default URL OpenAI. 
        # Jika None, fallback ke default openai atau endpoint yang sesuai jika opencode itu OpenAI api.
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
            
        self.client = OpenAI(**kwargs)
        logger.info(f"Opencode AI initialized with model: {self.model_name}")

    def refine_report(self, raw_text: str, categories: list) -> dict:
        system_prompt = (
            "Kamu adalah asisten yang membantu merapikan laporan kegiatan harian tenaga pramubakti.\n"
            "Kembalikan HANYA format JSON valid tanpa markdown block (jangan pakai ```json)."
        )
        
        user_prompt = f"""
        Teks asli dari user:
        "{raw_text}"

        Tugas kamu:
        1. Ubah menjadi kalimat formal, profesional, dan baku dalam bahasa Indonesia.
        2. Jika ada beberapa kegiatan, pisahkan menjadi list bernomor (1. ..., 2. ..., dst).
        3. User WAJIB memasukkan "Keterangan" atau "Kategori" dalam teks (biasanya di akhir kalimat, dipisah dengan garis lurus | atau spasi/tab).
        4. Jika user mencantumkan Keterangan, pilih SATU kategori dari daftar berikut yang paling mendekati keterangan user: {', '.join(categories)}.
        5. PENTING: Jika di dalam teks asli TIDAK ADA informasi Keterangan (Kategori) sama sekali, kamu HARUS mengisi field category dengan nilai "KETERANGAN_KOSONG".
        6. Jika teks bermakna "Libur", "Cuti", atau "Sakit", set is_libur=true dan category="Libur".

        Kembalikan HANYA format JSON valid dengan schema berikut:
        {{
            "is_libur": false,
            "final_text": "1. Melakukan perbaikan bug pada website SPM\\n2. Mengikuti rapat koordinasi PMB",
            "category": "Website"
        }}
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            text = response.choices[0].message.content.strip()
            
            if text.startswith("```json"): text = text[7:]
            if text.startswith("```"): text = text[3:]
            if text.endswith("```"): text = text[:-3]
            text = text.strip()
            
            return json.loads(text)
        except Exception as e:
            logger.error(f"Opencode error: {e}. Mengembalikan teks asli.")
            return {"is_libur": False, "final_text": raw_text, "category": "KETERANGAN_KOSONG"}

    def parse_bulk_report(self, raw_bulk_text: str, default_year: int = 2026, categories: list = None) -> list:
        """Parse teks kegiatan multi-tanggal menjadi list entri terstruktur."""
        cats = ", ".join(categories) if categories else "Website, Rapat, Dokumentasi, Dll"
        
        system_prompt = (
            "Kamu adalah asisten ekstraksi data laporan. Kembalikan HANYA format JSON valid array tanpa markdown block (jangan pakai ```json)."
        )
        
        user_prompt = f"""
        Ekstraksi teks laporan harian multi-tanggal berikut (yang biasanya disalin dari tabel Excel/Word):
        "{raw_bulk_text}"
        Tahun default: {default_year}. Kategori yang diizinkan: {cats}.
        
        Aturan:
        1. Ubah tanggal ke format YYYY-MM-DD.
        2. Teks kegiatan dibuat formal dan rapi.
        3. User WAJIB memasukkan "Keterangan" (Kategori) untuk setiap laporan. Biasanya ditaruh di bagian paling kanan (setelah pemisah Tab, spasi ganda, atau |).
        4. Jika dalam satu entri tanggal TIDAK DITEMUKAN informasi Keterangan/Kategori yang eksplisit, beri nilai "KETERANGAN_KOSONG" pada category.
        5. Jika hari libur, activity: "Libur", category: "Libur".
        
        Kembalikan HANYA JSON array tanpa markdown:
        [{{
            "date": "YYYY-MM-DD",
            "activity": "...",
            "category": "..."
        }}]
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            txt = response.choices[0].message.content.strip()
            
            if txt.startswith("```json"): txt = txt[7:]
            if txt.startswith("```"): txt = txt[3:]
            if txt.endswith("```"): txt = txt[:-3]
            txt = txt.strip()
            
            data = json.loads(txt)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"Opencode bulk parse error: {e}")
            return []
