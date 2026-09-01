import os
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm

from src.db.mysql_db import MySQLDB
from src.utils.terbilang import terbilang, BULAN_NAMES, HARI_NAMES

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parents[2]

class ReportGenerator:
    def __init__(self, db: MySQLDB):
        self.db = db

    def _find_template(self, user: dict) -> Path:
        """Cari file template DOCX dengan fallback bertingkat."""
        names = [
            user.get("template"),
            user.get("template_file"),
            "Darnell_template.docx",
            f"{user.get('display_name', '')}.docx",
            f"{user.get('user_id', '')}.docx",
            "Darnell.docx"
        ]
        for name in names:
            if not name:
                continue
            path = BASE_DIR / name if str(name).startswith("templates") else BASE_DIR / "templates" / Path(name).name
            if path.is_file():
                return path
                
        docx_files = list((BASE_DIR / "templates").glob("*.docx"))
        if docx_files:
            return docx_files[0]
        raise FileNotFoundError(f"Template DOCX tidak ditemukan di {BASE_DIR / 'templates'}")

    def _get_month_rows(self, user: dict, year_month: str) -> list:
        """Ambil dan format baris kegiatan bulanan."""
        # Gunakan method MySQLDB
        user_id = str(user.get("user_id"))
        if not user_id and user.get("telegram_chat_id"):
            user_id = str(user.get("telegram_chat_id"))
            
        logs = self.db.get_logs_by_month(user_id, year_month)
        logs.sort(key=lambda x: str(x.get("date", "")))
        
        rows = []
        for r in logs:
            dt = datetime.strptime(r["date"], "%Y-%m-%d")
            date_label = f"{dt.day} {BULAN_NAMES[dt.month]} {dt.year}".upper()
            rows.append({
                "date_label": date_label,
                "activity": r.get("final_text") or r.get("raw_text", ""),
                "category": r.get("category", "")
            })
        return rows

    def _get_month_images(self, user: dict, user_id: str, year_month: str, tpl: DocxTemplate) -> list:
        """Ambil gambar lampiran kegiatan."""
        images = []
        ids_to_check = {str(user_id), str(user.get("user_id", "")), str(user.get("telegram_chat_id", ""))}
        for uid in ids_to_check:
            if not uid:
                continue
            img_dir = BASE_DIR / "storage" / "images" / uid / year_month
            if img_dir.exists():
                for img_file in sorted(img_dir.glob("*.jpg")):
                    images.append(InlineImage(tpl, str(img_file), width=Mm(125), height=Mm(80)))
        return images

    def _build_context(self, user: dict, user_id: str, year_month: str, tpl: DocxTemplate) -> tuple[dict, str]:
        """Susun context dictionary untuk rendering template."""
        y, m = map(int, year_month.split("-"))
        bast_date = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
        month_name = BULAN_NAMES[m]
        
        context = {
            "name_upper": user.get("name_upper", user.get("display_name", "").upper()),
            "full_name": user.get("full_name", user.get("display_name", "")),
            "role": user.get("role") or "Tenaga Web Master",
            "area": user.get("area") or user.get("area_pekerjaan") or "POLITEKNIK PEKERJAAN UMUM",
            "placement": user.get("placement") or user.get("penempatan") or "KOMPU",
            "nik": os.getenv(f"NIK_{user_id.upper()}", "3306150206040003"),
            "report_month_upper": month_name.upper(),
            "report_year": y,
            "bast_day_name": HARI_NAMES[bast_date.weekday()],
            "bast_date_terbilang": terbilang(bast_date.day),
            "bast_month_name": BULAN_NAMES[bast_date.month],
            "bast_year_terbilang": terbilang(bast_date.year),
            "bast_date_numeric": bast_date.strftime("%d-%m-%Y"),
            "rows": self._get_month_rows(user, year_month),
            "images": self._get_month_images(user, user_id, year_month, tpl),
        }
        return context, month_name

    def generate(self, user_id: str, year_month: str) -> tuple[str, str]:
        """Generate DOCX dan PDF laporan bulanan."""
        users = self.db.get_active_users()
        user = next((u for u in users if str(u.get("user_id")) == user_id or str(u.get("telegram_chat_id")) == user_id), None)
        if not user:
            user = users[0] if users else {"user_id": user_id, "display_name": user_id}

        tpl_path = self._find_template(user)
        tpl = DocxTemplate(str(tpl_path))
        
        context, month_name = self._build_context(user, user_id, year_month, tpl)
        out_dir = BASE_DIR / "storage" / "output" / year_month
        out_dir.mkdir(parents=True, exist_ok=True)
        
        docx_path = out_dir / f"Laporan Bulanan {month_name} - {user.get('display_name', user_id)}.docx"
        tpl.render(context)
        tpl.save(str(docx_path))
        
        pdf_path = self._convert_to_pdf(docx_path, out_dir)
        return str(docx_path), str(pdf_path)

    def _convert_to_pdf(self, docx_path: Path, out_dir: Path) -> str:
        """Convert DOCX ke PDF via LibreOffice headless."""
        try:
            subprocess.run([
                'libreoffice', '--headless', '--convert-to', 'pdf',
                '--outdir', str(out_dir), str(docx_path)
            ], check=True, capture_output=True)
            return str(out_dir / f"{docx_path.stem}.pdf")
        except subprocess.CalledProcessError as e:
            logger.error(f"Gagal convert PDF: {e.stderr.decode('utf-8')}")
            raise RuntimeError("Gagal convert PDF dengan LibreOffice.")