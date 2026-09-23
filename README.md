# Production Multilingual Telegram Bot



## Features

- Registration with Uzbek, Russian, and English UI.
- Inline-keyboard main application menu.
- Seven-day weather forecasts for 12 Uzbekistan regions.
- Current weather lookup for arbitrary coordinates.
- Straight-line Haversine distance calculation.
- Approximate walking-time estimate from a 5 km/h base speed.
- Weather-aware speed adjustment with explicit precedence: heavy rain/snow, then extreme heat, then extreme cold, then normal weather.
- Telegram Location and manual coordinate input.
- Environment-based administrator credentials.
- Optional Telegram user-ID allowlist for the administrator.
- Expiring in-memory administrator sessions.
- Metrics and paginated activity logs.
- Text, photo, and video broadcasts with confirmation, batch delays, and RetryAfter handling.
- Structured logging and global user-safe error handling.
- Portable SQLAlchemy models with no SQLite-only SQL.

## Architecture

```text
Telegram Update
    |
    v
aiogram Router
    |
    +--> DB Session Middleware ---> AsyncSession
    |
    +--> i18n Middleware ---------> Saved application language
    |
    v
Handler
    |
    +--> Service Layer -----------> Weather / distance / broadcast logic
    |
    +--> SQLAlchemy 2.x ----------> SQLite or PostgreSQL
    |
    v
Localized Telegram response
```

## Project Tree

```text
telegram_weather_distance_bot/
├── bot/
│   ├── __init__.py
│   ├── config.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── connection.py
│   │   └── models.py
│   ├── middlewares/
│   │   ├── __init__.py
│   │   ├── db.py
│   │   └── i18n.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py
│   │   ├── weather.py
│   │   ├── distance.py
│   │   ├── admin.py
│   │   ├── about.py
│   │   ├── settings.py
│   │   └── common.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── activity_log.py
│   │   ├── broadcast.py
│   │   ├── weather_api.py
│   │   └── distance_calc.py
│   ├── keyboards/
│   │   ├── __init__.py
│   │   ├── callbacks.py
│   │   ├── main.py
│   │   ├── language.py
│   │   ├── weather.py
│   │   ├── distance.py
│   │   ├── about.py
│   │   ├── settings.py
│   │   └── admin.py
│   ├── states/
│   │   ├── __init__.py
│   │   ├── registration.py
│   │   ├── distance.py
│   │   └── admin.py
│   ├── locales/
│   │   ├── ru.json
│   │   ├── uz.json
│   │   └── en.json
│   └── main.py
├── tests/
│   └── test_distance_calc.py
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
└── README.md
```

## Installation

### Linux / macOS

```bash
git clone <your-repository-url>
cd telegram_weather_distance_bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

### Windows PowerShell

```powershell
git clone <your-repository-url>
cd telegram_weather_distance_bot
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Configuration

Edit `.env`:

```env
BOT_TOKEN=
DATABASE_URL=sqlite+aiosqlite:///bot.db
ADMIN_USERNAME=
ADMIN_PASSWORD=
# ADMIN_TELEGRAM_ID=
GITHUB_URL=
YOUTUBE_URL=
CREATOR_TELEGRAM_URL=
DEFAULT_LANGUAGE=ru
ADMIN_SESSION_TIMEOUT=1800
BROADCAST_BATCH_SIZE=20
BROADCAST_DELAY=1.0
REQUEST_TIMEOUT=15.0
```

All secrets are loaded from environment variables. The application fails at startup when mandatory settings are absent or invalid.

`ADMIN_TELEGRAM_ID` is optional. When configured, the bot requires both valid admin credentials and the matching Telegram user ID.

## Weather API

The weather service is keyless. It uses Open-Meteo as the primary provider, so no weather API key is required. The `/v1/forecast` endpoint provides the seven-day forecast and current weather variables used by this bot. If Open-Meteo is unavailable, the service falls back to `wttr.in` and parses its JSON response.

This removes the OpenWeather One Call 3.0 subscription dependency that caused HTTP 401 errors in the previous version. Open-Meteo's free API is intended for non-commercial use and is rate-limited, so review the provider's current terms before commercial or ad-supported deployment.

## Run

```bash
python -m bot.main
```

The bot creates database tables on startup for this project. The database layer is isolated so migrations can be introduced later without changing handlers or services.

## SQLite → PostgreSQL

Development:

```env
DATABASE_URL=sqlite+aiosqlite:///bot.db
```

Production:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/database
```

Changing only `DATABASE_URL` is sufficient. No Python source change is required.

## Registration Test

1. Start the bot with `/start`.
2. Select Russian, Uzbek, or English.
3. Send a first and last name.
4. Confirm the localized main menu appears.
5. Send `/start` again and verify registration is not repeated.

## Language Test

1. Open Settings.
2. Choose Change Language.
3. Select another language.
4. Verify the screen and all subsequent UI use the saved language.

## Weather Test

1. Open 7-Day Weather.
2. Select one of the twelve regions.
3. Verify seven daily entries are returned.
4. Stop or invalidate the weather API key and verify a friendly localized error appears instead of a traceback.

## Distance Test

1. Open Distance & Walking Time.
2. Send coordinates such as `41.2995, 69.2401`.
3. Send another coordinate pair.
4. Verify straight-line distance, approximate walking time, base speed, current weather, and any single applicable weather adjustment are shown.
5. Repeat with Telegram Location messages instead of coordinate text.

The distance calculation uses the Haversine formula and does not call a routing provider for the mathematical distance.

## Admin Test

1. Run `/admin` in a private chat.
2. Enter the configured username and password.
3. Open Metrics and Activity Log.
4. Start Broadcast.
5. Send text, photo, or video.
6. Review the confirmation screen.
7. Confirm delivery.
8. Verify success/failure counts are shown.
9. Use Logout.
10. Wait beyond `ADMIN_SESSION_TIMEOUT` and verify the session is rejected.

For production, set `ADMIN_TELEGRAM_ID` as an additional identity restriction.

## Security Notes

- No passwords, API keys, or bot tokens are logged.
- Admin passwords are never stored in FSM data after verification.
- Broadcast content is held only in temporary in-memory FSM state until confirmation/completion.
- User locations used for distance calculations are not written to the database.
- All user-controlled names, log fields, and broadcast previews are escaped before being inserted into HTML messages.
- Every admin callback performs server-side authorization checks.
- Login failures use a common message and a temporary lockout after repeated failures.
- Bot-side FSM storage is `MemoryStorage`; admin sessions and in-progress conversations are lost on process restart. A multi-instance deployment should use shared FSM storage such as Redis when that operational requirement exists.

## Bot Command List

The bot registers localized command descriptions for `ru`, `uz`, and `en` using Telegram's language-specific command support. A default command set is also registered using `DEFAULT_LANGUAGE` for users without a dedicated language scope. The in-chat application UI is localized from the user's saved database language.

## Verification Commands

Syntax-only verification:

```bash
python -m compileall bot tests
```

Unit tests:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The test suite focuses on pure distance-calculation functions and does not require Telegram credentials or a running database server.

## Production Deployment

The project is suitable for running behind systemd, Docker, or Docker Compose without architectural changes. Keep secrets outside the image/repository and use PostgreSQL for a persistent multi-instance deployment.
