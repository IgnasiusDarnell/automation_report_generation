import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import holidays
from aiogram import Bot, types

from src.reports.generator import ReportGenerator

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Jakarta")

# Inisialisasi Libur Nasional Indonesia (untuk tahun 2024-2028)
id_holidays = holidays.Indonesia(years=range(2024, 2029))

async def auto_libur_and_reminder(bot: Bot, db):
    """Job jam 16.00: Auto-input Libur atau Kirim Reminder."""
    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")
    is_holiday, holiday_name = db.is_holiday(now)
    
    logger.info(f"Running 16:00 job for {today_str}. Is Holiday: {is_holiday} ({holiday_name})")
    for user in db.get_active_users():
        user_id = user.get("user_id")
        display_name = user.get("display_name")
        has_log = db.has_log_for_date(user_id, today_str)
        
        if is_holiday and not has_log:
            db.save_log(user_id, today_str, "Libur", f"Libur ({holiday_name})", "Libur", "APPROVED")
            logger.info(f"Auto-inserted Libur for {display_name} on {today_str}")
        elif not is_holiday and not has_log:
            try:
                await bot.send_message(
                    user.get("telegram_chat_id"),
                    f"⏰ <b>Reminder Sore</b>\n\nHalo {display_name}, jangan lupa mengisi laporan hari ini (<b>{today_str}</b>).\n\nKetik /today atau /sampun untuk mengisi.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to send reminder to {display_name}: {e}")

import os

async def _notify_admin_unsubmitted(bot: Bot, yesterday_str: str, unsubmitted_users: list):
    """Kirim rekap anggota yang belum mengisi laporan ke Admin."""
    admin_id = os.getenv("ADMIN_CHAT_ID")
    if not admin_id or not unsubmitted_users:
        return
    names = "\n".join([f"- {u.get('display_name')} (ID: {u.get('user_id')})" for u in unsubmitted_users])
    text = (
        f"<b>Rekap Monitoring Laporan: {yesterday_str}</b>\n\n"
        f"Berikut user yang <b>belum</b> mengisi laporan:\n{names}"
    )
    try:
        await bot.send_message(admin_id, text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

async def morning_followup(bot: Bot, db):
    """Job jam 08.00: Menagih laporan kemarin jika hari kerja."""
    now = datetime.now(TZ)
    yesterday = now - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    is_holiday, _ = db.is_holiday(yesterday)
    
    if is_holiday:
        return
        
    unsubmitted = []
    for user in db.get_active_users():
        if not db.has_log_for_date(user.get("user_id"), yesterday_str):
            unsubmitted.append(user)
            try:
                await bot.send_message(
                    user.get("telegram_chat_id"),
                    f"<b>Reminder Pagi</b>\n\nHalo {user.get('display_name')}, Anda belum mengisi laporan kemarin (<b>{yesterday_str}</b>).\nKetik /fill {yesterday_str} untuk mengisi.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to send morning reminder to {user.get('display_name')}: {e}")
    await _notify_admin_unsubmitted(bot, yesterday_str, unsubmitted)

async def monthly_report_generation(bot: Bot, db):
    """Job Tanggal 1 Pukul 00:15: Generate laporan untuk bulan sebelumnya."""
    now = datetime.now(TZ)
    # Hitung bulan sebelumnya
    if now.month == 1:
        prev_month = 12
        prev_year = now.year - 1
    else:
        prev_month = now.month - 1
        prev_year = now.year
        
    year_month = f"{prev_year}-{prev_month:02d}"
    logger.info(f"Auto-generating monthly report for {year_month}")
    
    report_gen = ReportGenerator(db)
    users = db.get_active_users()
    
    for user in users:
        chat_id = user.get("telegram_chat_id")
        user_id = user.get("user_id")
        try:
            docx_path, pdf_path = report_gen.generate(user_id, year_month)
            
            with open(pdf_path, "rb") as pdf:
                await bot.send_document(chat_id, types.BufferedInputFile(pdf.read(), filename=Path(pdf_path).name), caption=f"📄 Laporan Bulanan {year_month}")
                
            with open(docx_path, "rb") as docx:
                await bot.send_document(chat_id, types.BufferedInputFile(docx.read(), filename=Path(docx_path).name), caption=f"📝 File DOCX Final {year_month}")
                
        except Exception as e:
            logger.error(f"Failed to generate report for {user_id}: {e}")