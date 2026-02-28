"""Ambient — weather fetch and diegetic mapping. No LLM."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import clock

logger = logging.getLogger(__name__)


@dataclass
class AmbientContext:
    condition: str          # clear | cloudy | rain | snow | fog | storm | hot | cold
    temp_c: float
    humidity: int
    wind_kph: float
    diegetic_text: str      # how it feels inside the shop
    mood_nudge: float       # -0.1 to +0.1 valence shift
    season: str             # spring | summer | autumn | winter
    season_text: str        # seasonal flavor
    fetched_at: datetime


# ── Weather → Diegetic mapping ──

WEATHER_DIEGETIC = {
    'clear': (
        "Sunlight falls across the counter. The shop is warm.",
        0.05,
    ),
    'cloudy': (
        "Overcast. The light in the shop is even and soft.",
        0.0,
    ),
    'rain': (
        "Rain on the windows. The shop feels smaller, closer.",
        0.02,
    ),
    'snow': (
        "Snow outside. Everything is muffled. The shop is an island.",
        0.03,
    ),
    'fog': (
        "Fog. The street outside is gone. Just the shop.",
        0.01,
    ),
    'storm': (
        "Thunder outside. The shelves rattle faintly.",
        -0.05,
    ),
    'hot': (
        "Heat seeps in. The fan turns slowly.",
        -0.02,
    ),
    'cold': (
        "Cold air leaks through the door frame. The tea stays warm.",
        0.0,
    ),
}

_WEATHER_DIEGETIC_DIGITAL = {
    'clear': ("Clear skies outside.", 0.05),
    'cloudy': ("Overcast.", 0.0),
    'rain': ("Rain outside.", 0.02),
    'snow': ("Snow outside. Everything muffled.", 0.03),
    'fog': ("Fog. The outside world is hidden.", 0.01),
    'storm': ("Thunder outside.", -0.05),
    'hot': ("It's hot.", -0.02),
    'cold': ("Cold.", 0.0),
}


# ── Season context (Tokyo-centric) ──

SEASON_CONTEXT = {
    'spring': "Cherry blossom season. Something about beginnings.",
    'summer': "Humid Tokyo summer. The shop fan does its best.",
    'autumn': "Autumn light. The shop smells like old books and tea.",
    'winter': "Winter. The shop is warm. Outside is sharp.",
}


def _month_to_season(month: int) -> str:
    if month in (3, 4, 5):
        return 'spring'
    elif month in (6, 7, 8):
        return 'summer'
    elif month in (9, 10, 11):
        return 'autumn'
    else:
        return 'winter'


def _classify_wmo(wmo_code: int, temp_c: float) -> str:
    """Map WMO weather interpretation codes to our condition categories.

    Codes: https://open-meteo.com/en/docs#weathervariables (WMO 4677)
    """
    if wmo_code in (0, 1):
        # Clear / mainly clear
        if temp_c > 33:
            return 'hot'
        if temp_c < 3:
            return 'cold'
        return 'clear'
    if wmo_code in (2, 3):
        return 'cloudy'
    if wmo_code in (45, 48):
        return 'fog'
    if wmo_code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return 'rain'
    if wmo_code in (71, 73, 75, 77, 85, 86):
        return 'snow'
    if wmo_code in (95, 96, 99):
        return 'storm'
    return 'cloudy'  # safe default


async def fetch_ambient_context(*, has_physical: bool = True) -> Optional[AmbientContext]:
    """Fetch current weather from Open-Meteo (free, no API key).

    In simulation mode, returns deterministic weather instead.
    Returns AmbientContext or None on failure.
    """
    if clock.is_simulating():
        return _simulated_weather(clock.now(), has_physical=has_physical)

    import aiohttp

    from config.location import LOCATION
    lat, lon = LOCATION['lat'], LOCATION['lon']

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
    )

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("[Ambient] Open-Meteo returned %d", resp.status)
                    return None
                data = await resp.json()
    except Exception as e:
        logger.warning("[Ambient] Weather fetch failed: %s", e)
        return None

    try:
        current = data['current']
        temp_c = float(current['temperature_2m'])
        humidity = int(current['relative_humidity_2m'])
        wind_kph = float(current['wind_speed_10m'])
        wmo_code = int(current['weather_code'])

        condition = _classify_wmo(wmo_code, temp_c)
        return map_to_diegetic(condition, temp_c, humidity, wind_kph,
                               has_physical=has_physical)

    except (KeyError, IndexError, ValueError, TypeError) as e:
        logger.warning("[Ambient] Weather parse failed: %s", e)
        return None


def map_to_diegetic(condition: str, temp_c: float = 20.0,
                    humidity: int = 50, wind_kph: float = 0.0,
                    *, has_physical: bool = True) -> AmbientContext:
    """Deterministic weather → feeling conversion."""
    from db import JST

    mapping = WEATHER_DIEGETIC if has_physical else _WEATHER_DIEGETIC_DIGITAL
    diegetic_text, mood_nudge = mapping.get(
        condition, ("The weather outside.", 0.0)
    )

    now = clock.now()
    season = _month_to_season(now.month)
    season_text = SEASON_CONTEXT.get(season, "")

    return AmbientContext(
        condition=condition,
        temp_c=temp_c,
        humidity=humidity,
        wind_kph=wind_kph,
        diegetic_text=diegetic_text,
        mood_nudge=mood_nudge,
        season=season,
        season_text=season_text,
        fetched_at=clock.now_utc(),
    )


# ── Deterministic weather for simulation mode ──

# 5 time-of-day slots (morning → night)
SIMULATED_WEATHER_CYCLE = [
    # (hour_start, hour_end, condition, temp_c, humidity, wind_kph)
    (6, 9, 'clear', 14.0, 55, 5.0),        # cool morning
    (9, 12, 'clear', 18.0, 50, 8.0),       # warming up
    (12, 15, 'cloudy', 22.0, 55, 10.0),    # midday clouds
    (15, 18, 'clear', 20.0, 50, 7.0),      # afternoon clearing
    (18, 6, 'clear', 12.0, 60, 3.0),       # evening/night
]

# 7-day rotation for variety
DAY_VARIATIONS = [
    # (condition_override, temp_offset, humidity_offset)
    (None, 0, 0),           # Day 0: baseline
    ('rain', -2, +20),      # Day 1: rainy
    (None, +3, -5),         # Day 2: warmer
    ('cloudy', -1, +10),    # Day 3: overcast
    (None, +1, 0),          # Day 4: baseline+
    ('rain', -3, +25),      # Day 5: rainy
    ('clear', +2, -10),     # Day 6: sunny
]


def _simulated_weather(now_jst: datetime, *, has_physical: bool = True) -> AmbientContext:
    """Deterministic weather based on time-of-day and day-of-week rotation."""
    hour = now_jst.hour
    day_index = now_jst.toordinal() % 7

    # Find time slot
    condition, temp_c, humidity, wind_kph = 'clear', 16.0, 55, 5.0
    for h_start, h_end, cond, temp, hum, wind in SIMULATED_WEATHER_CYCLE:
        if h_start <= h_end:
            if h_start <= hour < h_end:
                condition, temp_c, humidity, wind_kph = cond, temp, hum, wind
                break
        else:
            # Wraps midnight (18-6)
            if hour >= h_start or hour < h_end:
                condition, temp_c, humidity, wind_kph = cond, temp, hum, wind
                break

    # Apply day variation
    override, temp_off, hum_off = DAY_VARIATIONS[day_index]
    if override:
        condition = override
    temp_c += temp_off
    humidity = max(20, min(95, humidity + hum_off))

    return map_to_diegetic(condition, temp_c, humidity, wind_kph,
                           has_physical=has_physical)
