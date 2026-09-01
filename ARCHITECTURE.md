# Architecture Documentation

## 1. Tech Stack Summary
- **Primary Language:** Python 3.12+
- **Framework:** `aiogram` (Telegram Bot Framework)
- **Database / ORM:** MySQL 8.x / `SQLAlchemy`
- **AI Integration:** Opencode API (Model: `minmaxm3`) via `openai` SDK
- **Document Generation:** `docxtpl`, `python-docx`
- **Scheduler:** `APScheduler`
- **Containerization:** Docker & Docker Compose

## 2. Project Tree
```
remindre_project_bot/
├── config/
│   ├── secrets.yaml.example
│   ├── settings.yaml
│   └── users.yaml
├── src/
│   ├── ai/
│   │   └── opencode_client.py
│   ├── bot/
│   │   └── handlers.py
│   ├── db/
│   │   └── mysql_db.py
│   ├── reports/
│   │   └── generator.py
│   ├── scheduler/
│   │   └── jobs.py
│   ├── utils/
│   │   ├── image_optimizer.py
│   │   └── terbilang.py
│   ├── check_integrations.py
│   ├── healthcheck.py
│   └── main.py
├── templates/
│   └── Darnell.docx
├── .env
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## 3. Source Code Map
- **`src/main.py`**: The main entry point. Initializes the Bot, Dispatcher, MySQL connection, and starts the APScheduler.
- **`src/bot/`**: Telegram interface layer. Contains FSM states and message routers (`handlers.py`).
- **`src/db/`**: Data access layer. Defines SQLAlchemy ORM models (`DailyLog`, `ImageMetadata`, `User`) and connection handlers.
- **`src/ai/`**: AI logic wrapper (`opencode_client.py`). Constructs prompts and parses AI JSON responses for text refinement.
- **`src/reports/`**: Document generation logic. Parses `.docx` templates and exports PDF using LibreOffice headless.
- **`src/scheduler/`**: Background asynchronous jobs for sending morning/evening reminders and auto-generating monthly reports.
- **`src/utils/`**: Helper scripts for image compression (`Pillow`) and number-to-text formatting.

## 4. Entry Points
- **Production/Local Start:** `python -m src.main`
- **Pre-flight Check:** `python -m src.check_integrations`

## 5. Routing Layer (Telegram Handlers)
| Command/Trigger | Module/Function | Description |
|---|---|---|
| `/start`, `/help` | `cmd_start`, `cmd_help` | Basic bot greetings and instructions. |
| `/today` | `cmd_today` | Initiates single-day report FSM flow. |
| `/sampun` | `cmd_sampun` | Initiates multi-day bulk report FSM flow. |
| `F.photo` | `handle_photo` | Captures and compresses images to local storage. |
| Callback `use_ai_yes` | `save_with_ai` | Triggers AI text refinement before saving. |

## 6. Business Logic Layer
- **Report Refinement:** Users input casual text (e.g., "perbaikan web | Website"). The AI transforms this into formal Indonesian and ensures proper categorization.
- **Bulk Import:** Users can paste an entire table of activities. AI extracts dates, tasks, and categories into a JSON array, which is then batch-saved to MySQL.
- **Scheduler Policies:** 
  - 08:00 AM: Checks if the previous day's report is missing.
  - 16:00 PM: Reminds users to fill today's report. Automatically inserts "Libur" if today is a national holiday.
  - 1st of Month (00:15 AM): Generates the previous month's DOCX & PDF reports.

## 7. Data Layer
Database engine is MySQL. Interactions occur via **SQLAlchemy**.
- **`User`**: Telegram Chat ID, display name, roles, active status.
- **`DailyLog`**: Master record of daily activities (`date`, `raw_text`, `final_text`, `category`).
- **`ImageMetadata`**: Paths to locally stored `.jpg` documentation linked by `year_month` and `telegram_file_id`.
- **`Holiday`**: Custom holiday configurations overriding default calendar logic.

## 8. Critical Workflows

**Workflow A: Daily Report Submission (with AI)**
1. User sends `/today`.
2. FSM switches to `waiting_text`. User sends report text.
3. System asks whether to use AI optimization. User clicks "Ya".
4. `OpencodeAI` structures and formalizes the text via API.
5. `MySQLDB.save_log()` inserts the finalized entry.
6. User receives confirmation message.

**Workflow B: Photo Documentation Upload**
1. User sends a photo directly to the bot.
2. `handlers.py` catches `F.photo`.
3. `image_optimizer.compress_image` resizes the image down to 1600px max and drops quality to 80% to save disk space.
4. The file is saved to `storage/images/{user_id}/{year_month}/`.
5. DB records metadata with `local_path`.

**Workflow C: Automated Monthly Reporting**
1. `APScheduler` triggers `monthly_report_generation()` on the 1st day of the month at 00:15.
2. The script loops over all active `Users`.
3. Calls `self.db.get_logs_by_month()` to fetch all approved logs.
4. Compiles text data and local image paths into a `.docx` template using `docxtpl`.
5. `libreoffice --headless` converts the generated `.docx` into `.pdf`.
6. Bot directly sends the `.pdf` and `.docx` file to the User's Telegram chat.
