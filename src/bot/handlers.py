import os
from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

from src.db.mysql_db import MySQLDB
from src.ai.opencode_client import OpencodeAI

from pathlib import Path
from src.utils.image_optimizer import compress_image
import logging
from datetime import timedelta
from src.scheduler.jobs import auto_libur_and_reminder, morning_followup, TZ, id_holidays
from src.reports.generator import ReportGenerator
from config.constants import DEFAULT_CATEGORIES

logger = logging.getLogger(__name__)

router = Router()

# Inisialisasi DB, AI, dan Report Generator
try:
    db = MySQLDB()
    ai = OpencodeAI()
    report_gen = ReportGenerator(db)
    SERVICES_READY = True
except Exception as e:
    logger.error(f"Gagal inisialisasi DB/AI/ReportGenerator: {e}")
    SERVICES_READY = False
    report_gen = None

BASE_DIR = Path(__file__).resolve().parents[2] # Naik 2 level dari src/bot/ ke root project

# Kategori default (sementara hardcode untuk Darnell, nanti diambil dari DB)
DEFAULT_CATEGORIES = ["Website", "Rapat", "Dokumentasi","Dll"]

class ReportStates(StatesGroup):
    waiting_text = State()
    waiting_confirmation = State()
    waiting_revision = State()
    waiting_bulk_text = State()
    waiting_bulk_confirm = State()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "Halo! Saya adalah Bot Otomasi Laporan KOMPU.\n\n"
        "Gunakan /help untuk melihat daftar perintah yang tersedia."
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "<b>Daftar Perintah KOMPU Bot:</b>\n\n"
        "/start - Mulai bot\n"
        "/help - Bantuan & daftar perintah\n"
        "/whoami - Lihat identitas & Chat ID Telegram\n"
        "/today - Isi laporan kegiatan hari ini\n"
        "/sampun - Input laporan massal / multi-hari sekaligus\n"
        "/fill [YYYY-MM-DD] - Isi laporan tanggal lampau\n"
        "/edit [YYYY-MM-DD] - Edit laporan tanggal tertentu\n"
        "/status [YYYY-MM] - Cek status kelengkapan laporan\n"
        "/preview [YYYY-MM] - Preview laporan bulanan\n"
        "/generate [YYYY-MM] - Generate laporan (PDF/DOCX/Keduanya)\n"
        "/cek_libur [YYYY-MM-DD] - Cek status hari libur / kerja\n"
        "/list_libur [YYYY-MM] - Daftar hari libur pada periode\n"
        "/tambah_libur YYYY-MM-DD [Ket] - Tambah libur kustom (Admin)\n"
        "/hapus_libur YYYY-MM-DD - Hapus libur kustom (Admin)\n"
        "/cek_pending - Rekap anggota yang belum kirim laporan (Admin)\n"
        "/batal - Batalkan proses yang sedang berjalan\n\n"
        "<i>Kirim foto langsung ke bot untuk lampiran dokumentasi.</i>"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("whoami"))
async def cmd_whoami(message: types.Message):
    chat_id = message.chat.id
    full_name = message.from_user.full_name
    username = message.from_user.username or "(tidak ada)"
    
    text = (
        f"<b>Identitas Telegram Anda</b>\n\n"
        f"Nama: {full_name}\n"
        f"Username: @{username}\n"
        f"Chat ID: <code>{chat_id}</code>"
    )
    await message.answer(text, parse_mode="HTML")

# --- LOGIKA FSM UNTUK LAPORAN ---

@router.message(Command("today"))
async def cmd_today(message: types.Message, state: FSMContext):
    if not SERVICES_READY:
        await message.answer("Sistem database atau AI sedang tidak siap. Hubungi Admin.")
        return

    user_info = db.get_user_by_chat_id(message.from_user.id)
    if not user_info:
        await message.answer("Anda belum terdaftar di database Users. Hubungi Admin.")
        return
        
    user_id = user_info["user_id"]
    now = datetime.now(TZ)
    yesterday = now - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    is_holiday, _ = db.is_holiday(yesterday)
    
    if not is_holiday:
        if not db.has_log_for_date(user_id, yesterday_str):
            await message.answer(
                f"<b>Akses Ditolak</b>\n\nAnda belum mengisi laporan kemarin (<b>{yesterday_str}</b>).\n"
                f"Isi tanggal tersebut dahulu dengan:\n<code>/fill {yesterday_str}</code>",
                parse_mode="HTML"
            )
            return

    today_str = now.strftime("%Y-%m-%d")
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        await _ask_ai_optimization(message, state, user_id, today_str, parts[1].strip())
        return

    await state.update_data(user_id=user_id, target_date=today_str, raw_text="")
    await message.answer(
        f"Silakan kirimkan teks laporan beserta keterangannya untuk hari ini (<b>{today_str}</b>).\n\n"
        f"<b>Contoh Format:</b>\n"
        f"<code>Melakukan perbaikan halaman web | Website</code>\n\n"
        f"Ketik /batal untuk membatalkan.",
        parse_mode="HTML"
    )
    await state.set_state(ReportStates.waiting_text)

@router.message(Command("sampun"))
async def cmd_sampun(message: types.Message, state: FSMContext):
    """Input laporan massal (multi-hari sekaligus)."""
    user_info = db.get_user_by_chat_id(message.from_user.id)
    if not user_info:
        await message.answer("Anda belum terdaftar di database Users. Hubungi Admin.")
        return

    user_id = user_info["user_id"]
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        await _process_bulk_input(message, state, user_id, parts[1].strip())
        return

    guide_text = (
        "<b>Panduan Input Laporan Massal (/sampun):</b>\n\n"
        "Gunakan fitur ini untuk memasukkan data laporan beberapa hari sekaligus (misal copy-paste tabel Word/Excel).\n\n"
        "<b>Contoh Format:</b>\n"
        "<code>1 Juli 2026\t• Membuat Page Prestasi Mahasiswa\n"
        "• Melakukan Update Prestasi Mahasiswa\tWebsite\n"
        "2 Juli 2026\tMembuat Form Pemuktahiran Data UKM\tWebsite\n"
        "3 Juli 2026\t• Diskusi website SPM\tRapat\n"
        "4 Juli 2026\tLibur\n"
        "5 Juli 2026\tLibur</code>\n\n"
        "<b>PENTING:</b> Anda <b>wajib</b> menyertakan Keterangan (Kategori) di setiap harinya (misalnya: <i>Website</i> atau <i>Rapat</i>) yang ditaruh di akhir kalimat menggunakan pemisah Tab, spasi, atau tanda |.\n\n"
        "Silakan kirimkan teks kumpulan laporan Anda sekarang."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Batal", callback_data="cancel_action")]
    ])
    await state.update_data(user_id=user_id)
    await message.answer(guide_text, parse_mode="HTML", reply_markup=keyboard)
    await state.set_state(ReportStates.waiting_bulk_text)

@router.message(ReportStates.waiting_bulk_text, F.text)
async def handle_bulk_text_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id") or str(message.from_user.id)
    await _process_bulk_input(message, state, user_id, message.text)

async def _process_bulk_input(message: types.Message, state: FSMContext, user_id: str, raw_text: str):
    """Proses teks massal dengan AI dan tampilkan preview."""
    await message.answer("AI sedang memproses dan merapikan seluruh entri laporan Anda...")
    current_year = datetime.now(TZ).year
    parsed_entries = ai.parse_bulk_report(raw_text, default_year=current_year, categories=DEFAULT_CATEGORIES)
    
    if not parsed_entries:
        await message.answer("AI gagal mem-parsing format tanggal/kegiatan. Pastikan format sesuai contoh.\nKetik /batal untuk membatalkan.")
        return

    # Validasi Keterangan Kosong
    for i, item in enumerate(parsed_entries):
        if item.get("category") == "KETERANGAN_KOSONG":
            await message.answer(
                f"<b>Gagal:</b> Ditemukan entri tanpa Keterangan pada baris {i+1} (Tanggal: {item.get('date')}).\n"
                f"Harap perbaiki teks Anda dan pastikan semua baris memiliki Keterangan (sebagai kolom ketiga).\n"
                f"Contoh: <code>Kegiatan... | Keterangan</code>",
                parse_mode="HTML"
            )
            return

    await state.update_data(user_id=user_id, parsed_entries=parsed_entries)
    summary_lines = [
        f"• <b>{item.get('date')}</b> [{item.get('category')}]: {item.get('activity')[:40]}..."
        for item in parsed_entries[:6]
    ]
    if len(parsed_entries) > 6:
        summary_lines.append(f"... dan {len(parsed_entries) - 6} entri lainnya.")

    preview_msg = (
        f"<b>Berhasil mengekstrak {len(parsed_entries)} entri laporan:</b>\n\n"
        + "\n".join(summary_lines) + "\n\n"
        "Apakah Anda ingin menyimpan seluruh entri ini ke database?"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Simpan Semua ke Database", callback_data="save_bulk_yes")],
        [InlineKeyboardButton(text="Batal", callback_data="cancel_action")]
    ])
    await message.answer(preview_msg, parse_mode="HTML", reply_markup=keyboard)
    await state.set_state(ReportStates.waiting_bulk_confirm)

@router.callback_query(F.data == "save_bulk_yes", ReportStates.waiting_bulk_confirm)
async def save_bulk_entries(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id") or str(callback.from_user.id)
    entries = data.get("parsed_entries", [])
    
    saved_count = 0
    for e in entries:
        dt, act = e.get("date"), e.get("activity")
        cat = e.get("category", "Lainnya")
        if dt and act:
            if db.save_log(user_id, dt, act, act, cat, "APPROVED"):
                saved_count += 1
                
    await callback.message.edit_text(f"Berhasil menyimpan {saved_count} dari {len(entries)} entri laporan ke Database MySQL.")
    await state.clear()
    await callback.answer()

async def _ask_ai_optimization(message: types.Message, state: FSMContext, user_id: str, target_date: str, raw_text: str):
    """Menampilkan opsi validasi optimasi AI untuk teks laporan."""
    await state.update_data(user_id=user_id, target_date=target_date, raw_text=raw_text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Ya, Sempurnakan AI", callback_data="use_ai_yes"),
            InlineKeyboardButton(text="Tidak, Simpan Langsung", callback_data="use_ai_no")
        ],
        [
            InlineKeyboardButton(text="Batal", callback_data="cancel_action")
        ]
    ])
    await message.answer(
        f"Laporan tanggal <b>{target_date}</b> diterima:\n<i>{raw_text}</i>\n\n"
        "Apakah Anda ingin teks ini disempurnakan dan dirapikan oleh AI?",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await state.set_state(ReportStates.waiting_confirmation)

@router.message(Command("batal"))
async def cmd_batal(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Proses pengisian laporan dibatalkan.")

@router.message(ReportStates.waiting_text, F.text)
async def process_report_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id") or str(message.from_user.id)
    target_date = data.get("target_date") or datetime.now(TZ).strftime("%Y-%m-%d")
    await _ask_ai_optimization(message, state, user_id, target_date, message.text)

@router.callback_query(F.data == "use_ai_no", ReportStates.waiting_confirmation)
async def save_directly(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id") or str(callback.from_user.id)
    date_str = data["target_date"]
    raw_text = data["raw_text"]
    
    # Validasi Keterangan
    if "|" not in raw_text:
        await callback.message.edit_text(
            "<b>Gagal:</b> Anda belum menyertakan Keterangan.\n"
            "Gunakan format: <code>Kegiatan Anda | Keterangan</code>\n\n"
            "Silakan ketik ulang laporan Anda:", parse_mode="HTML"
        )
        await state.set_state(ReportStates.waiting_text)
        await callback.answer()
        return

    parts = raw_text.rsplit("|", 1)
    act = parts[0].strip()
    cat = parts[1].strip()

    # Simpan langsung tanpa AI
    success = db.save_log(user_id, date_str, raw_text, act, cat, "APPROVED")
    
    if success:
        await callback.message.edit_text(f"Laporan untuk {date_str} berhasil disimpan langsung ke database.")
    else:
        await callback.message.edit_text("Gagal menyimpan ke database. Cek log server.")
        
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "use_ai_yes", ReportStates.waiting_confirmation)
async def refine_with_ai(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("AI sedang menyempurnakan laporan Anda... (Mohon tunggu 3-5 detik)")
    
    data = await state.get_data()
    raw_text = data["raw_text"]
    
    result = ai.refine_report(raw_text, DEFAULT_CATEGORIES)
    
    # Validasi Keterangan Kosong
    if result.get("category") == "KETERANGAN_KOSONG":
        await callback.message.edit_text(
            "<b>Gagal:</b> Anda belum menyertakan Keterangan (atau format tidak terbaca).\n"
            "Gunakan format: <code>Kegiatan Anda | Keterangan</code>\n\n"
            "Silakan ketik ulang laporan Anda:", parse_mode="HTML"
        )
        await state.set_state(ReportStates.waiting_text)
        await callback.answer()
        return
        
    await state.update_data(ai_result=result)
    
    final_text = result.get("final_text", raw_text)
    category = result.get("category", "Lainnya")
    
    text_preview = (
        f"<b>Preview Hasil AI:</b>\n\n"
        f"<b>Kegiatan:</b>\n{final_text}\n\n"
        f"<b>Kategori:</b> <code>{category}</code>\n\n"
        f"Apakah hasil ini sudah sesuai?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Setuju & Simpan", callback_data="approve_ai")],
        [InlineKeyboardButton(text="Perbaiki AI", callback_data="revise_ai")],
        [InlineKeyboardButton(text="Edit Manual", callback_data="edit_manual")]
    ])
    
    await callback.message.edit_text(text_preview, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "approve_ai")
async def approve_ai_result(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id") or str(callback.from_user.id)
    date_str = data["target_date"]
    raw_text = data["raw_text"]
    ai_result = data["ai_result"]
    
    final_text = ai_result.get("final_text", raw_text)
    category = ai_result.get("category", "Lainnya")
    
    success = db.save_log(user_id, date_str, raw_text, final_text, category, "APPROVED")
    
    if success:
        await callback.message.edit_text(f"Laporan AI untuk {date_str} berhasil disetujui dan disimpan ke database.")
    else:
        await callback.message.edit_text("Gagal menyimpan ke database.")
        
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "revise_ai")
async def ask_revision_instruction(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Silakan ketik instruksi perbaikan untuk AI.\n"
        "Contoh: <i>'Buat lebih formal', 'Ganti kategori jadi Rapat', 'Hapus poin nomor 2'</i>.",
        parse_mode="HTML"
    )
    await state.set_state(ReportStates.waiting_revision)
    await callback.answer()

@router.message(ReportStates.waiting_revision, F.text)
async def process_revision(message: types.Message, state: FSMContext):
    instruction = message.text
    data = await state.get_data()
    raw_text = data["raw_text"]
    
    await message.answer("AI sedang merevisi berdasarkan instruksi Anda...")
    
    # Gabungkan teks asli dan instruksi untuk AI
    revised_prompt = f"Teks asli: {raw_text}\nInstruksi revisi dari user: {instruction}"
    result = ai.refine_report(revised_prompt, DEFAULT_CATEGORIES)
    
    await state.update_data(ai_result=result)
    
    final_text = result.get("final_text", raw_text)
    category = result.get("category", "Lainnya")
    
    text_preview = (
        f"<b>Preview Hasil Revisi AI:</b>\n\n"
        f"<b>Kegiatan:</b>\n{final_text}\n\n"
        f"<b>Kategori:</b> <code>{category}</code>\n\n"
        f"Apakah hasil ini sudah sesuai?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Setuju & Simpan", callback_data="approve_ai")],
        [InlineKeyboardButton(text="Perbaiki AI Lagi", callback_data="revise_ai")],
        [InlineKeyboardButton(text="Edit Manual", callback_data="edit_manual")]
    ])
    
    await message.answer(text_preview, parse_mode="HTML", reply_markup=keyboard)
    await state.set_state(ReportStates.waiting_confirmation)

@router.callback_query(F.data == "edit_manual")
async def handle_edit_manual(callback: types.CallbackQuery, state: FSMContext):
    """Kembali ke input teks manual."""
    await callback.message.edit_text(
        "Silakan ketik ulang teks laporan Anda secara manual.\nKetik /batal untuk membatalkan."
    )
    await state.set_state(ReportStates.waiting_text)
    await callback.answer() 

async def _process_local_photo(bot, photo, user_id: str, year_month: str, date_str: str) -> tuple[Path, str]:
    """Download dan kompresi foto ke penyimpanan lokal."""
    file = await bot.get_file(photo.file_id)
    local_dir = BASE_DIR / "storage" / "images" / user_id / year_month
    local_dir.mkdir(parents=True, exist_ok=True)
    
    file_name = f"{date_str}_{photo.file_unique_id}.jpg"
    local_path = local_dir / file_name
    
    await bot.download_file(file.file_path, local_path)
    compress_image(local_path)
    return local_path, file_name



@router.message(F.photo)
async def handle_photo(message: types.Message, state: FSMContext):
    if await state.get_state() is not None:
        await message.answer("Anda sedang dalam proses pengisian laporan. Selesaikan atau ketik /batal.")
        return

    user_info = db.get_user_by_chat_id(message.from_user.id)
    if not user_info:
        await message.answer("Anda belum terdaftar di database Users. Hubungi Admin.")
        return

    user_id = user_info["user_id"]
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    year_month = today.strftime("%Y-%m")

    await message.answer(f"Memproses dan mengompres foto untuk tanggal {date_str}...")
    try:
        photo = message.photo[-1]
        local_path, file_name = await _process_local_photo(message.bot, photo, user_id, year_month, date_str)
        
        # Mode lokal saja
        db.save_image(
            user_id=user_id,
            date_str=date_str,
            year_month=year_month,
            telegram_file_id=photo.file_id,
            local_path=str(local_path)
        )
        await message.answer(
            f"Foto berhasil disimpan!\n\n"
            f"Tanggal: {date_str}\n"
            f"Tersimpan di server lokal.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error upload foto: {e}")
        await message.answer("Gagal menyimpan foto. Silakan cek log server atau hubungi Admin.")

@router.message(Command("fill"))
async def cmd_fill(message: types.Message, state: FSMContext):
    """Mengisi laporan untuk tanggal lampau."""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Format salah. Contoh: <code>/fill 2026-08-20</code>", parse_mode="HTML")
        return
        
    target_date = parts[1]
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        await message.answer("Format tanggal tidak valid. Gunakan format YYYY-MM-DD.")
        return

    user_info = db.get_user_by_chat_id(message.from_user.id)
    user_id = user_info["user_id"] if user_info else str(message.from_user.id)
    
    if len(parts) > 2 and parts[2].strip():
        await _ask_ai_optimization(message, state, user_id, target_date, parts[2].strip())
        return

    await state.update_data(user_id=user_id, target_date=target_date, raw_text="")
    await message.answer(
        f"Silakan kirimkan teks laporan beserta keterangannya untuk tanggal <b>{target_date}</b>.\n\n"
        f"<b>Contoh Format:</b>\n"
        f"<code>Melakukan perbaikan halaman web | Website</code>\n\n"
        f"Ketik /batal untuk membatalkan.",
        parse_mode="HTML"
    )
    await state.set_state(ReportStates.waiting_text)

@router.message(Command("edit"))
async def cmd_edit(message: types.Message, state: FSMContext):
    """Mengedit laporan pada tanggal tertentu."""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Format salah. Contoh: <code>/edit 2026-08-20</code>", parse_mode="HTML")
        return

    target_date = parts[1]
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        await message.answer("Format tanggal tidak valid. Gunakan format YYYY-MM-DD.")
        return

    user_info = db.get_user_by_chat_id(message.from_user.id)
    user_id = user_info["user_id"] if user_info else str(message.from_user.id)

    if len(parts) > 2 and parts[2].strip():
        await _ask_ai_optimization(message, state, user_id, target_date, parts[2].strip())
        return

    existing_log = db.get_log_by_date(user_id, target_date)
    msg = f"<b>Edit Laporan Tanggal {target_date}</b>\n\n"
    if existing_log:
        curr_text = existing_log.get('final_text') or existing_log.get('raw_text', '')
        msg += f"<b>Laporan saat ini:</b>\n{curr_text}\n\n"
    msg += "Kirimkan teks laporan baru untuk memperbarui tanggal ini.\nKetik /batal untuk membatalkan."

    await state.update_data(user_id=user_id, target_date=target_date, raw_text="")
    await message.answer(msg, parse_mode="HTML")
    await state.set_state(ReportStates.waiting_text)

@router.message(Command("status"))
async def cmd_status(message: types.Message):
    """Melihat status kelengkapan laporan untuk bulan tertentu."""
    user_info = db.get_user_by_chat_id(message.from_user.id)
    if not user_info:
        await message.answer("Anda belum terdaftar di database Users. Hubungi Admin.")
        return

    parts = message.text.split()
    year_month = parts[1] if len(parts) > 1 else datetime.now(TZ).strftime("%Y-%m")
    try:
        datetime.strptime(year_month, "%Y-%m")
    except ValueError:
        await message.answer("Format bulan tidak valid. Gunakan format YYYY-MM (contoh: 2026-08).")
        return

    user_id = user_info["user_id"]
    logs = db.get_logs_by_month(user_id, year_month)
    filled_dates = sorted(list({str(r.get("date")) for r in logs if r.get("date")}))

    text = (
        f"<b>Status Laporan: {year_month}</b>\n"
        f"User: {user_info.get('display_name', user_id)}\n"
        f"Total Terisi: <b>{len(filled_dates)} hari</b>\n"
    )
    if filled_dates:
        text += f"Tanggal terisi: {', '.join(filled_dates[-7:])}\n"
    text += f"\nGunakan /preview {year_month} untuk melihat dokumen."
    await message.answer(text, parse_mode="HTML")

@router.message(Command("test_scheduler"))
async def cmd_test_scheduler(message: types.Message):
    """Command khusus Admin untuk memicu job scheduler secara manual."""
    admin_id = os.getenv("ADMIN_CHAT_ID")
    if str(message.from_user.id) != str(admin_id):
        await message.answer("Command ini hanya untuk Admin.")
        return
        
    await message.answer("Memicu job <b>auto_libur_and_reminder</b> secara manual...", parse_mode="HTML")
    await auto_libur_and_reminder(message.bot, db)
    await message.answer("Job selesai dieksekusi. Cek chat user atau database.")

@router.message(Command("preview"))
@router.message(Command("generate"))
async def cmd_generate_report(message: types.Message):
    """Memicu pembuatan laporan bulanan dengan pilihan format dokumen."""
    parts = message.text.split()
    year_month = parts[1] if len(parts) > 1 else datetime.now(TZ).strftime("%Y-%m")
    try:
        datetime.strptime(year_month, "%Y-%m")
    except ValueError:
        await message.answer("Format bulan tidak valid. Gunakan format YYYY-MM (contoh: 2026-08).")
        return

    user_info = db.get_user_by_chat_id(message.from_user.id)
    is_admin = str(message.from_user.id) == str(os.getenv("ADMIN_CHAT_ID"))
    target_user = parts[2] if (len(parts) > 2 and is_admin) else (user_info.get("user_id", "darnell") if user_info else "darnell")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="PDF Saja", callback_data=f"gen:pdf:{year_month}:{target_user}"),
            InlineKeyboardButton(text="DOCX Saja", callback_data=f"gen:docx:{year_month}:{target_user}")
        ],
        [
            InlineKeyboardButton(text="Keduanya (DOCX & PDF)", callback_data=f"gen:both:{year_month}:{target_user}")
        ],
        [
            InlineKeyboardButton(text="Batal", callback_data="cancel_action")
        ]
    ])
    await message.answer(
        f"<b>Pilih Format Laporan:</b>\n\n"
        f"Periode: <b>{year_month}</b>\n"
        f"User: <b>{target_user}</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("gen:"))
async def handle_generate_callback(callback: types.CallbackQuery):
    _, fmt, ym, target_user = callback.data.split(":")
    await callback.message.edit_text(f"Sedang merender laporan {ym} ({fmt.upper()}) untuk {target_user}...")
    try:
        docx_path, pdf_path = report_gen.generate(target_user, ym)
        if fmt in ("pdf", "both"):
            with open(pdf_path, "rb") as pdf:
                await callback.message.answer_document(
                    types.BufferedInputFile(pdf.read(), filename=Path(pdf_path).name),
                    caption=f"Dokumen PDF Laporan {ym}"
                )
        if fmt in ("docx", "both"):
            with open(docx_path, "rb") as docx:
                await callback.message.answer_document(
                    types.BufferedInputFile(docx.read(), filename=Path(docx_path).name),
                    caption=f"Dokumen DOCX Laporan {ym}"
                )
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Generate error: {e}")
        await callback.message.answer(f"Gagal generate laporan: {e}")
    await callback.answer()

@router.message(Command("cek_pending"))
async def cmd_cek_pending(message: types.Message):
    """Admin command: cek siapa saja yang belum submit laporan kemarin."""
    admin_id = os.getenv("ADMIN_CHAT_ID")
    if str(message.from_user.id) != str(admin_id):
        await message.answer("Command ini khusus Admin.")
        return

    now = datetime.now(TZ)
    yesterday = now - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    
    users = db.get_active_users()
    unsubmitted = [u for u in users if not db.has_log_for_date(u.get("user_id"), yesterday_str)]
    
    if not unsubmitted:
        await message.answer(f"Semua user ({len(users)}) telah mengisi laporan tanggal <b>{yesterday_str}</b>.", parse_mode="HTML")
        return
        
    names = "\n".join([f"- {u.get('display_name')} (ID: {u.get('user_id')})" for u in unsubmitted])
    text = (
        f"<b>Daftar User Belum Mengisi: {yesterday_str}</b>\n\n"
        f"Total: {len(unsubmitted)} dari {len(users)} user\n\n{names}"
    )
    await message.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "cancel_action")
async def handle_cancel_action(callback: types.CallbackQuery, state: FSMContext):
    """Batalkan aksi inline FSM."""
    await state.clear()
    await callback.message.edit_text("Aksi dibatalkan.")
    await callback.answer()

@router.message(Command("cek_libur"))
async def cmd_cek_libur(message: types.Message):
    """Cek status hari libur pada tanggal tertentu."""
    parts = message.text.split()
    date_str = parts[1] if len(parts) > 1 else datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await message.answer("Format tanggal tidak valid. Gunakan format YYYY-MM-DD.")
        return

    is_hol, desc = db.is_holiday(dt)
    status_label = "LIBUR" if is_hol else "HARI KERJA"
    await message.answer(
        f"<b>Status Tanggal {date_str}:</b>\n\n"
        f"Status: <b>{status_label}</b>\n"
        f"Keterangan: {desc}",
        parse_mode="HTML"
    )

@router.message(Command("tambah_libur"))
async def cmd_tambah_libur(message: types.Message):
    """Admin command: Tambah atau update tanggal libur kustom."""
    admin_id = os.getenv("ADMIN_CHAT_ID")
    if str(message.from_user.id) != str(admin_id):
        await message.answer("Command ini khusus Admin.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Format: <code>/tambah_libur YYYY-MM-DD Keterangan</code>", parse_mode="HTML")
        return

    date_str, desc = parts[1], parts[2].strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await message.answer("Format tanggal tidak valid. Gunakan YYYY-MM-DD.")
        return

    if db.add_or_update_holiday(date_str, desc, is_active=True):
        await message.answer(f"Berhasil menambahkan tanggal libur <b>{date_str}</b>: {desc}", parse_mode="HTML")
    else:
        await message.answer("Gagal menyimpan data libur ke database.")

@router.message(Command("hapus_libur"))
async def cmd_hapus_libur(message: types.Message):
    """Admin command: Hapus tanggal libur kustom."""
    admin_id = os.getenv("ADMIN_CHAT_ID")
    if str(message.from_user.id) != str(admin_id):
        await message.answer("Command ini khusus Admin.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Format: <code>/hapus_libur YYYY-MM-DD</code>", parse_mode="HTML")
        return

    date_str = parts[1]
    if db.delete_holiday(date_str):
        await message.answer(f"Berhasil menghapus tanggal libur <b>{date_str}</b>.", parse_mode="HTML")
    else:
        await message.answer(f"Tanggal <b>{date_str}</b> tidak ditemukan di data libur kustom.", parse_mode="HTML")

@router.message(Command("list_libur"))
async def cmd_list_libur(message: types.Message):
    """Melihat daftar hari libur kustom dan nasional."""
    parts = message.text.split()
    ym = parts[1] if len(parts) > 1 else datetime.now(TZ).strftime("%Y-%m")
    custom = db.get_custom_holidays()
    
    lines = [f"• <b>{d}</b>: {info.get('description')} (Kustom)" for d, info in sorted(custom.items()) if d.startswith(ym)]
    for d, desc in sorted(id_holidays.items()):
        ds = d.strftime("%Y-%m-%d")
        if ds.startswith(ym) and ds not in custom:
            lines.append(f"• <b>{ds}</b>: {desc} (Nasional)")

    result = "\n".join(lines) if lines else "Tidak ada hari libur terjadwal pada periode ini."
    await message.answer(f"<b>Daftar Libur Periode {ym}:</b>\n\n{result}", parse_mode="HTML")

@router.message(~F.state())
async def echo_message(message: types.Message):
    if message.text:
        await message.answer(
            f"Anda mengetik:\n<i>{message.text}</i>\n\n"
            f"Gunakan /today atau /sampun untuk mulai mengisi laporan."
        )