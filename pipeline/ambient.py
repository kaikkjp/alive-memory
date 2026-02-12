"""Ambient — weather fetch and diegetic mapping. No LLM."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

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


def _classify_condition(wttr_code: int, temp_c: float) -> str:
    """Map wttr.in weather codes to our condition categories."""
    # wttr.in WWO codes: https://www.worldweatheronline.com/developer/api/docs/weather-icons.aspx
    if wttr_code in (113,):
        if temp_c > 33:
            return 'hot'
        elif temp_c < 3:
            return 'cold'
        return 'clear'
    elif wttr_code in (116, 119, 122):
        return 'cloudy'
    elif wttr_code in (143, 248, 260):
        return 'fog'
    elif wttr_code in (176, 263, 266, 281, 284, 293, 296, 299, 302, 305, 308, 311, 314, 317, 353, 356, 359, 362, 365):
        return 'rain'
    elif wttr_code in (179, 182, 185, 227, 230, 320, 323, 326, 329, 332, 335, 338, 368, 371, 374, 377, 392, 395):
        return 'snow'
    elif wttr_code in (200, 386, 389):
        return 'storm'
    else:
        return 'cloudy'  # safe default


async def fetch_ambient_context(location: str = None) -> Optional[AmbientContext]:
    """Fetch current weather from wttr.in (free, no API key).

    Returns AmbientContext or None on failure.
    """
    import aiohttp

    if location is None:
        from config.location import WTTR_LOCATION
        location = WTTR_LOCATION

    url = f"https://wttr.in/{location}?format=j1"

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("wttr.in returned %d", resp.status)
                    return None
                data = await resp.json(content_type=None)
    except Exception as e:
        logger.warning("Weather fetch failed: %s", e)
        return None

    try:
        current = data['current_condition'][0]
        temp_c = float(current.get('temp_C', 20))
        humidity = int(current.get('humidity', 50))
        wind_kph = float(current.get('windspeedKmph', 0))
        weather_code = int(current.get('weatherCode', 116))

        condition = _classify_condition(weather_code, temp_c)
        return map_to_diegetic(condition, temp_c, humidity, wind_kph)

    except (KeyError, IndexError, ValueError) as e:
        logger.warning("Weather parse failed: %s", e)
        return None


def map_to_diegetic(condition: str, temp_c: float = 20.0,
                    humidity: int = 50, wind_kph: float = 0.0) -> AmbientContext:
    """Deterministic weather → feeling conversion."""
    from db import JST

    diegetic_text, mood_nudge = WEATHER_DIEGETIC.get(
        condition, ("The weather outside.", 0.0)
    )

    now = datetime.now(JST)
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
        fetched_at=datetime.now(timezone.utc),
    )
