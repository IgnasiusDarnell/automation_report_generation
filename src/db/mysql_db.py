import os
import json
import logging
from datetime import datetime
import holidays

from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, Date
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)
id_holidays = holidays.Indonesia(years=range(2024, 2029))

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100))
    full_name = Column(String(100))
    name_upper = Column(String(100))
    role = Column(String(100))
    placement = Column(String(100))
    area = Column(String(100))
    telegram_chat_id = Column(String(50))
    template = Column(String(200))
    categories = Column(Text) # Stored as JSON string
    active = Column(Boolean, default=True)

class DailyLog(Base):
    __tablename__ = 'daily_logs'
    log_id = Column(String(100), primary_key=True)
    date = Column(String(20))
    user_id = Column(String(50))
    year_month = Column(String(10))
    raw_text = Column(Text)
    final_text = Column(Text)
    category = Column(String(100))
    status = Column(String(50), default="APPROVED")
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    source = Column(String(50), default="TELEGRAM")

class ImageMetadata(Base):
    __tablename__ = 'images'
    image_id = Column(String(100), primary_key=True)
    user_id = Column(String(50))
    date = Column(String(20))
    year_month = Column(String(10))
    telegram_file_id = Column(String(255))
    local_path = Column(String(255))
    selected = Column(Boolean, default=True)
    caption = Column(Text)
    created_at = Column(DateTime)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime)
    user_id = Column(String(50))
    action = Column(String(100))
    details = Column(Text)
    actor = Column(String(50))

class Holiday(Base):
    __tablename__ = 'holidays'
    date = Column(String(20), primary_key=True)
    description = Column(String(255))
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime)

class MySQLDB:
    def __init__(self):
        host = os.getenv("MYSQL_HOST", "localhost")
        port = os.getenv("MYSQL_PORT", "3306")
        user = os.getenv("MYSQL_USER", "root")
        password = os.getenv("MYSQL_PASSWORD", "")
        db_name = os.getenv("MYSQL_DATABASE", "remindre")
        
        # Use PyMySQL driver
        database_url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}"
        
        self.engine = create_engine(database_url, pool_recycle=3600, echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        
        logger.info(f"Connected to MySQL database at {host}:{port}/{db_name}")

    def save_log(self, user_id: str, date_str: str, raw_text: str, final_text: str, category: str, status: str = "APPROVED"):
        timestamp = datetime.now()
        year_month = date_str[:7]
        log_id = f"log_{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}"
        
        try:
            with self.Session() as session:
                existing = session.query(DailyLog).filter_by(user_id=str(user_id), date=str(date_str)).first()
                if existing:
                    existing.raw_text = raw_text
                    existing.final_text = final_text
                    existing.category = category
                    existing.status = status
                    existing.updated_at = timestamp
                    self.log_audit(user_id, "UPDATE_LOG", f"Date: {date_str}, Cat: {category}", "USER")
                    logger.info(f"Updated log for user {user_id} on {date_str}")
                else:
                    new_log = DailyLog(
                        log_id=log_id,
                        date=date_str,
                        user_id=str(user_id),
                        year_month=year_month,
                        raw_text=raw_text,
                        final_text=final_text,
                        category=category,
                        status=status,
                        created_at=timestamp,
                        updated_at=timestamp,
                        source="TELEGRAM"
                    )
                    session.add(new_log)
                    self.log_audit(user_id, "SAVE_LOG", f"Date: {date_str}, Cat: {category}", "USER")
                    logger.info(f"Inserted log for user {user_id} on {date_str}")
                session.commit()
            return True
        except Exception as e:
            logger.error(f"Gagal menyimpan ke MySQL: {e}")
            return False

    def get_user_by_chat_id(self, chat_id: int):
        try:
            with self.Session() as session:
                user = session.query(User).filter_by(telegram_chat_id=str(chat_id)).first()
                if user:
                    # Convert to dict to match gspread output
                    d = {col.name: getattr(user, col.name) for col in user.__table__.columns}
                    # Convert JSON string to list for categories if needed
                    if d.get("categories"):
                        try:
                            d["categories"] = json.loads(d["categories"])
                        except json.JSONDecodeError:
                            pass
                    return d
                return None
        except Exception as e:
            logger.error(f"Error get user: {e}")
            return None

    def save_image(self, user_id: str, date_str: str, year_month: str, telegram_file_id: str, local_path: str):
        try:
            timestamp = datetime.now()
            image_id = f"img_{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}"
            with self.Session() as session:
                new_image = ImageMetadata(
                    image_id=image_id,
                    user_id=str(user_id),
                    date=date_str,
                    year_month=year_month,
                    telegram_file_id=telegram_file_id,
                    local_path=local_path,
                    selected=True,
                    caption="",
                    created_at=timestamp
                )
                session.add(new_image)
                self.log_audit(user_id, "UPLOAD_IMAGE", f"Date: {date_str}, File: {local_path}", "USER")
                session.commit()
            return True
        except Exception as e:
            logger.error(f"Error save image: {e}")
            return False

    def get_active_users(self):
        try:
            with self.Session() as session:
                users = session.query(User).filter(User.active == True, User.telegram_chat_id != None).all()
                result = []
                for u in users:
                    d = {col.name: getattr(u, col.name) for col in u.__table__.columns}
                    if d.get("categories"):
                        try:
                            d["categories"] = json.loads(d["categories"])
                        except json.JSONDecodeError:
                            pass
                    result.append(d)
                return result
        except Exception as e:
            logger.error(f"Error get active users: {e}")
            return []

    def get_all_users(self):
        """Ambil semua user (untuk web admin)."""
        try:
            with self.Session() as session:
                users = session.query(User).order_by(User.id.asc()).all()
                result = []
                for u in users:
                    d = {col.name: getattr(u, col.name) for col in u.__table__.columns}
                    if d.get("categories"):
                        try:
                            d["categories"] = json.loads(d["categories"])
                        except json.JSONDecodeError:
                            pass
                    result.append(d)
                return result
        except Exception as e:
            logger.error(f"Error get all users: {e}")
            return []

    def get_user_by_user_id(self, user_id: str):
        """Ambil user by user_id (bukan chat_id)."""
        try:
            with self.Session() as session:
                user = session.query(User).filter_by(user_id=str(user_id)).first()
                if not user:
                    return None
                d = {col.name: getattr(user, col.name) for col in user.__table__.columns}
                if d.get("categories"):
                    try:
                        d["categories"] = json.loads(d["categories"])
                    except json.JSONDecodeError:
                        pass
                return d
        except Exception as e:
            logger.error(f"Error get user by user_id: {e}")
            return None

    def create_user(self, data: dict, actor: str = "ADMIN") -> tuple[bool, str]:
        """Insert user baru. Return (success, message)."""
        try:
            with self.Session() as session:
                # Validasi user_id unik
                if session.query(User).filter_by(user_id=str(data.get("user_id", ""))).first():
                    return False, f"user_id '{data.get('user_id')}' sudah dipakai."
                user = User(
                    user_id=str(data.get("user_id", "")).strip(),
                    display_name=data.get("display_name", "").strip() or None,
                    full_name=data.get("full_name", "").strip() or None,
                    name_upper=data.get("name_upper", "").strip().upper() or None,
                    role=data.get("role", "").strip() or None,
                    placement=data.get("placement", "").strip() or None,
                    area=data.get("area", "").strip() or None,
                    telegram_chat_id=str(data.get("telegram_chat_id", "")).strip() or None,
                    template=data.get("template", "").strip() or None,
                    categories=json.dumps(data.get("categories") or [], ensure_ascii=False),
                    active=bool(data.get("active", True)),
                )
                session.add(user)
                self.log_audit(user.user_id, "CREATE_USER", f"User baru: {user.user_id}", actor)
                session.commit()
                return True, f"User '{user.user_id}' berhasil dibuat."
        except Exception as e:
            logger.error(f"Error create user: {e}")
            return False, f"Gagal membuat user: {e}"

    def update_user(self, user_id: str, data: dict, actor: str = "ADMIN") -> tuple[bool, str]:
        """Update field user by user_id."""
        try:
            with self.Session() as session:
                user = session.query(User).filter_by(user_id=str(user_id)).first()
                if not user:
                    return False, f"User '{user_id}' tidak ditemukan."
                for field in ("display_name", "full_name", "role", "placement", "area",
                              "template", "telegram_chat_id"):
                    if field in data:
                        val = data[field]
                        setattr(user, field, val.strip() if isinstance(val, str) else val)
                if "name_upper" in data:
                    user.name_upper = (data["name_upper"] or "").strip().upper() or None
                if "categories" in data:
                    user.categories = json.dumps(data["categories"] or [], ensure_ascii=False)
                if "active" in data:
                    user.active = bool(data["active"])
                user.telegram_chat_id = str(user.telegram_chat_id).strip() or None if user.telegram_chat_id else None
                self.log_audit(user.user_id, "UPDATE_USER", f"Update user: {user.user_id}", actor)
                session.commit()
                return True, f"User '{user.user_id}' diperbarui."
        except Exception as e:
            logger.error(f"Error update user: {e}")
            return False, f"Gagal memperbarui user: {e}"

    def delete_user(self, user_id: str, actor: str = "ADMIN") -> tuple[bool, str]:
        """Hapus user (beserta logs dan images-nya)."""
        try:
            with self.Session() as session:
                user = session.query(User).filter_by(user_id=str(user_id)).first()
                if not user:
                    return False, f"User '{user_id}' tidak ditemukan."
                # Hapus logs
                logs_deleted = session.query(DailyLog).filter_by(user_id=str(user_id)).delete()
                # Hapus images
                images_deleted = session.query(ImageMetadata).filter_by(user_id=str(user_id)).delete()
                session.delete(user)
                self.log_audit(user_id, "DELETE_USER",
                               f"User dihapus (logs: {logs_deleted}, images: {images_deleted})", actor)
                session.commit()
                return True, f"User '{user_id}' dihapus (beserta {logs_deleted} logs dan {images_deleted} images)."
        except Exception as e:
            logger.error(f"Error delete user: {e}")
            return False, f"Gagal menghapus user: {e}"

    def update_log(self, log_id: str, data: dict, actor: str = "ADMIN") -> tuple[bool, str]:
        """Edit log by log_id."""
        try:
            with self.Session() as session:
                log = session.query(DailyLog).filter_by(log_id=str(log_id)).first()
                if not log:
                    return False, f"Log '{log_id}' tidak ditemukan."
                if "raw_text" in data:
                    log.raw_text = data["raw_text"]
                if "final_text" in data:
                    log.final_text = data["final_text"]
                if "category" in data:
                    log.category = data["category"]
                if "status" in data:
                    log.status = data["status"]
                log.updated_at = datetime.now()
                self.log_audit(log.user_id, "UPDATE_LOG_WEB",
                               f"log_id={log_id}, date={log.date}, cat={log.category}", actor)
                session.commit()
                return True, f"Log {log.date} diperbarui."
        except Exception as e:
            logger.error(f"Error update log: {e}")
            return False, f"Gagal memperbarui log: {e}"

    def delete_log(self, log_id: str, actor: str = "ADMIN") -> tuple[bool, str]:
        """Hapus log by log_id."""
        try:
            with self.Session() as session:
                log = session.query(DailyLog).filter_by(log_id=str(log_id)).first()
                if not log:
                    return False, f"Log '{log_id}' tidak ditemukan."
                info = f"log_id={log_id}, date={log.date}, user={log.user_id}"
                session.delete(log)
                self.log_audit(log.user_id, "DELETE_LOG_WEB", info, actor)
                session.commit()
                return True, f"Log {log.date} dihapus."
        except Exception as e:
            logger.error(f"Error delete log: {e}")
            return False, f"Gagal menghapus log: {e}"

    def get_log_by_log_id(self, log_id: str):
        try:
            with self.Session() as session:
                log = session.query(DailyLog).filter_by(log_id=str(log_id)).first()
                if not log:
                    return None
                return {col.name: getattr(log, col.name) for col in log.__table__.columns}
        except Exception as e:
            logger.error(f"Error get log by id: {e}")
            return None

    def get_images_for_user_month(self, user_id: str, year_month: str) -> list:
        try:
            with self.Session() as session:
                imgs = session.query(ImageMetadata).filter_by(
                    user_id=str(user_id), year_month=str(year_month)
                ).order_by(ImageMetadata.date.asc(), ImageMetadata.created_at.asc()).all()
                return [{col.name: getattr(i, col.name) for col in i.__table__.columns} for i in imgs]
        except Exception as e:
            logger.error(f"Error get images: {e}")
            return []

    def has_log_for_date(self, user_id: str, date_str: str) -> bool:
        try:
            with self.Session() as session:
                log = session.query(DailyLog).filter_by(user_id=str(user_id), date=str(date_str)).first()
                return log is not None
        except Exception as e:
            logger.error(f"Error check log date: {e}")
            return False

    def get_logs_by_month(self, user_id: str, year_month: str) -> list:
        try:
            with self.Session() as session:
                logs = session.query(DailyLog).filter_by(user_id=str(user_id), year_month=str(year_month)).all()
                return [{col.name: getattr(log, col.name) for col in log.__table__.columns} for log in logs]
        except Exception as e:
            logger.error(f"Error get month logs: {e}")
            return []

    def get_log_by_date(self, user_id: str, date_str: str) -> dict | None:
        try:
            with self.Session() as session:
                log = session.query(DailyLog).filter_by(user_id=str(user_id), date=str(date_str)).first()
                if log:
                    return {col.name: getattr(log, col.name) for col in log.__table__.columns}
                return None
        except Exception as e:
            logger.error(f"Error get log date: {e}")
            return None

    def log_audit(self, user_id: str, action: str, details: str, actor: str = "SYSTEM"):
        try:
            timestamp = datetime.now()
            with self.Session() as session:
                log = AuditLog(
                    timestamp=timestamp,
                    user_id=str(user_id),
                    action=action,
                    details=details,
                    actor=str(actor)
                )
                session.add(log)
                session.commit()
            return True
        except Exception as e:
            logger.error(f"Error log audit: {e}")
            return False

    def get_custom_holidays(self) -> dict:
        try:
            with self.Session() as session:
                holidays = session.query(Holiday).all()
                return {str(h.date): {col.name: getattr(h, col.name) for col in h.__table__.columns} for h in holidays}
        except Exception as e:
            logger.error(f"Error get custom holidays: {e}")
            return {}

    def add_or_update_holiday(self, date_str: str, description: str, is_active: bool = True) -> bool:
        try:
            timestamp = datetime.now()
            with self.Session() as session:
                existing = session.query(Holiday).filter_by(date=date_str).first()
                if existing:
                    existing.description = description
                    existing.is_active = is_active
                    existing.updated_at = timestamp
                    self.log_audit("ALL", "UPDATE_HOLIDAY", f"Date: {date_str}, Desc: {description}", "ADMIN")
                else:
                    new_holiday = Holiday(
                        date=date_str,
                        description=description,
                        is_active=is_active,
                        updated_at=timestamp
                    )
                    session.add(new_holiday)
                    self.log_audit("ALL", "ADD_HOLIDAY", f"Date: {date_str}, Desc: {description}", "ADMIN")
                session.commit()
            return True
        except Exception as e:
            logger.error(f"Error save holiday: {e}")
            return False

    def delete_holiday(self, date_str: str) -> bool:
        try:
            with self.Session() as session:
                existing = session.query(Holiday).filter_by(date=date_str).first()
                if existing:
                    session.delete(existing)
                    self.log_audit("ALL", "DELETE_HOLIDAY", f"Date: {date_str}", "ADMIN")
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"Error delete holiday: {e}")
            return False

    def is_holiday(self, dt) -> tuple[bool, str]:
        if isinstance(dt, str):
            dt = datetime.strptime(dt[:10], "%Y-%m-%d")
        
        if dt.weekday() >= 5:
            day_name = "Sabtu" if dt.weekday() == 5 else "Minggu"
            return True, f"Akhir Pekan ({day_name})"
            
        date_str = dt.strftime("%Y-%m-%d")
        custom_holidays = self.get_custom_holidays()
        if date_str in custom_holidays:
            ch = custom_holidays[date_str]
            if str(ch.get("is_active", "")).upper() == "TRUE" or ch.get("is_active") is True:
                return True, ch.get("description", "Libur Kustom")
            return False, "Hari Kerja (Override)"
            
        if dt in id_holidays:
            return True, f"Libur Nasional ({id_holidays.get(dt)})"
        return False, "Hari Kerja"
