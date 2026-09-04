import asyncio
import logging
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.bot.handlers import router as bot_router
from src.db.mysql_db import MySQLDB
from src.healthcheck import start_server_in_thread, set_scheduler
from src.scheduler.jobs import (
    auto_libur_and_reminder,
    morning_followup,
    monthly_report_generation
)

BASE_DIR = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Jakarta")

(BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "logs" / "app.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

async def main():
    load_dotenv(BASE_DIR / ".env")
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.critical("TELEGRAM_BOT_TOKEN tidak ditemukan di .env")
        sys.exit(1)

    logger.info("=== KOMPU Report Automation - Bot & Scheduler Starting ===")
    
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(bot_router)
    
    # Inisialisasi Database
    try:
        db = MySQLDB()
        logger.info("Database MySQL berhasil terkoneksi.")
    except Exception as e:
        logger.critical(f"Gagal koneksi Database: {e}")
        sys.exit(1)

    # Start HTTP /health endpoint (for Uptime Kuma)
    start_server_in_thread()

    # Setup Scheduler
    scheduler = AsyncIOScheduler(timezone=TZ)
    
    # Job 1: Reminder Sore & Auto-Libur (Jam 16:00)
    scheduler.add_job(
        auto_libur_and_reminder,
        CronTrigger(hour=16, minute=0, timezone=TZ),
        args=(bot, db),
        misfire_grace_time=7200, # Toleransi 2 jam jika laptop sleep
        coalesce=True,           # Gabungkan job yang terlewat jadi 1 eksekusi
        id="daily_reminder"
    )
    
    # Job 2: Reminder Pagi (Jam 08:00)
    scheduler.add_job(
        morning_followup,
        CronTrigger(hour=8, minute=0, timezone=TZ),
        args=(bot, db),
        misfire_grace_time=7200,
        coalesce=True,
        id="morning_followup"
    )

    # Job 3: Auto Generate Laporan (Tanggal 1 Pukul 00:15)
    scheduler.add_job(
        monthly_report_generation,
        CronTrigger(day=1, hour=0, minute=15, timezone=TZ),
        args=(bot, db),
        misfire_grace_time=86400, # Toleransi 1 hari jika laptop mati total di tanggal 1
        coalesce=True,
        id="monthly_generation"
    )
    
    # Inject DB ke dispatcher agar bisa diakses handler jika perlu
    dp["db"] = db
    
    scheduler.start()
    set_scheduler(scheduler)
    logger.info("Scheduler aktif. Menunggu pesan masuk...")
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception("Error saat polling: %s", e)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot dihentikan oleh sistem/user.")