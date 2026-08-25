from typing import Any

import httpx

from app.core.config import get_settings


async def current_weather() -> dict[str, Any]:
    settings = get_settings()
    if settings.pipilot_weather_latitude is None or settings.pipilot_weather_longitude is None:
        return {"available": False, "message": "Configure PIPILOT_WEATHER_LATITUDE and PIPILOT_WEATHER_LONGITUDE"}
    params = {"latitude": settings.pipilot_weather_latitude, "longitude": settings.pipilot_weather_longitude,
              "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
              "timezone": settings.pipilot_timezone}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
        return {"available": True, "location": settings.pipilot_weather_location or "Configured location",
                "current": response.json().get("current", {}), "source": "Open-Meteo", "internet_used": True}
    except (httpx.HTTPError, ValueError) as exc:
        return {"available": False, "message": f"Weather service unavailable: {type(exc).__name__}"}
