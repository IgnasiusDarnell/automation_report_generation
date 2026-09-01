# KOMPU Report Automation Bot

A smart Telegram Bot designed to automate the process of recording daily activities, optimizing documentation images, and generating monthly DOCX/PDF reports automatically. It leverages the Opencode AI API to transform casual inputs into formal activity reports.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Configuration](#configuration)
- [Core Features](#core-features)
- [Usage / Running the Application](#usage--running-the-application)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Versioning & Changelog](#versioning--changelog)

## Prerequisites
- **Python:** 3.12 or higher (if running locally without Docker)
- **Docker & Docker Compose:** For seamless deployment.
- **MySQL:** 8.0+ (Included in `docker-compose.yml`)
- **LibreOffice:** Required for converting DOCX to PDF reports (Included in Docker).

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/IgnasiusDarnell/automation_report_generation.git
   cd automation_report_generation
   ```

2. **Environment Variables:**
   Copy the example config and adjust your tokens.
   ```bash
   cp .env.example .env
   ```
   *(Ensure you fill in your `TELEGRAM_BOT_TOKEN`, `OPENCODE_API_KEY`, and `MYSQL_*` credentials).*

3. **Running via Docker (Recommended):**
   ```bash
   docker-compose up -d --build
   ```

4. **Running Locally (Without Docker):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Or `venv\Scripts\activate` on Windows
   pip install -r requirements.txt
   python -m src.check_integrations # Run pre-flight checks
   python -m src.main
   ```

## Configuration

Settings are managed via `.env` for secrets and `config/settings.yaml` for application behavior.

| Variable Name | Description | Required / Default |
|---------------|-------------|--------------------|
| `TELEGRAM_BOT_TOKEN` | Token provided by BotFather. | **Required** |
| `OPENCODE_API_KEY` | API key from Opencode platform. | **Required** |
| `MYSQL_HOST` | Hostname of the MySQL database. | `homelab-mysql` |
| `MYSQL_PORT` | Port of the MySQL database. | `3306` |
| `MYSQL_USER` | MySQL Username. | `remindre_user` |
| `MYSQL_PASSWORD` | MySQL Password. | **Required** |
| `MYSQL_DATABASE` | MySQL Database Name. | `remindre_bot` |
| `ADMIN_CHAT_ID` | Telegram Chat ID for admin notifications. | Optional |

## Core Features
- **AI-Powered Text Formalization:** Converts casual daily reports into professional sentences using `minmaxm3`.
- **Bulk Multi-Day Logging:** Paste entire excel/word tables directly into the bot via `/sampun`.
- **Smart Image Compression:** Automatically resizes and compresses documentation images locally.
- **Auto-Holiday Detection:** Injects "Libur" entries automatically on Indonesian national holidays.
- **Reminders:** Sends daily reminders at 08:00 AM (for missing yesterday's log) and 16:00 PM (for today's log).
- **Automated Monthly DOCX/PDF Generation:** At the end of every month, generates and sends a completed Word Document and PDF directly to the user's Telegram chat.

## Usage / Running the Application
Once the bot is running (either via `docker-compose up` or `python -m src.main`), interact with it on Telegram:
- `/start` - Start interacting with the bot.
- `/today` - Enter your daily report.
- `/sampun` - Input a bulk list of daily reports.
- *Send Photo* - Directly upload documentation images for your reports.

## API Reference
This bot primarily connects to external APIs rather than serving them:
- **Telegram Bot API:** For messaging interfaces (`aiogram`).
- **Opencode API:** For AI-powered text completions (`openai` SDK).

## Testing
To run syntax checks and integration tests locally:
```bash
python -m compileall src
python -m src.check_integrations
```

## Versioning & Changelog
- **Current Version:** 1.0.0
- **Changelog:** See the GitHub commit history.
