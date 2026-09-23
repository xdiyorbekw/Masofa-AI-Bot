# Render weather fix

The weather service now:
- falls back from Open-Meteo HTTP 429 to MET Norway Locationforecast 2.0;
- sends a descriptive User-Agent required by MET Norway;
- parses MET Norway hourly timeseries into seven daily forecasts;
- caches forecasts/current weather in memory to reduce provider rate-limit pressure;
- serializes forecast fetches to prevent request bursts;
- keeps wttr.in only as a last-resort provider;
- serves the last successful forecast if all providers are temporarily unavailable.

Render Web Service support was also added: when Render provides `PORT`, the bot starts
a tiny HTTP `/health` endpoint on `0.0.0.0:$PORT`. This prevents Render's port scan
from timing out while the Telegram bot continues polling.

The `.env` file is intentionally not included in this fixed archive. Set the same
environment variables in Render's Environment settings; use `.env.example` as a template.
