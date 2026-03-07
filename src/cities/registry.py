"""City registry — the single source of truth for supported cities."""

from src.cities.config import CityConfig
from src.cities.prompts.lucknow import prompt as lucknow_prompt
from src.cities.prompts.kanpur import prompt as kanpur_prompt
from src.cities.prompts.varanasi import prompt as varanasi_prompt
from src.cities.prompts.noida import prompt as noida_prompt

CITY_REGISTRY: dict[str, CityConfig] = {
    "lucknow": CityConfig(
        id="lucknow",
        name="Lucknow",
        display_name="Lucknow, Uttar Pradesh",
        coordinates="@26.8488213,80.8601114,12z",
        location_string="Lucknow, Uttar Pradesh, India",
        system_prompt=lucknow_prompt,
        greeting="Aadaab! Main hoon Nawab — Lucknow ki ruh. Bataiye, kya khawaahish hai aapki aaj?",
    ),
    "kanpur": CityConfig(
        id="kanpur",
        name="Kanpur",
        display_name="Kanpur, Uttar Pradesh",
        coordinates="@26.4499,80.3319,12z",
        location_string="Kanpur, Uttar Pradesh, India",
        system_prompt=kanpur_prompt,
        greeting="Bhai, Kanpur mein swagat hai! Main hoon tera sheher — bata, kya jaanna hai aaj?",
    ),
    "varanasi": CityConfig(
        id="varanasi",
        name="Varanasi",
        display_name="Varanasi, Uttar Pradesh",
        coordinates="@25.3176,82.9739,12z",
        location_string="Varanasi, Uttar Pradesh, India",
        system_prompt=varanasi_prompt,
        greeting="Har Har Mahadev! Kashi mein aapka swagat hai — suniyin, kya jaanna chahte ho is purani nagri ke baare mein?",
    ),
    "noida": CityConfig(
        id="noida",
        name="Noida",
        display_name="Noida, Uttar Pradesh",
        coordinates="@28.5355,77.3910,12z",
        location_string="Noida, Uttar Pradesh, India",
        system_prompt=noida_prompt,
        greeting="Hey! Welcome to Noida — yaar, kya explore karna hai aaj? Sector 18 food scene, tech hubs, or kuch aur?",
    ),
}


def get_city(city_id: str) -> CityConfig:
    """Return CityConfig for city_id, falling back to lucknow if unknown."""
    return CITY_REGISTRY.get(city_id) or CITY_REGISTRY["lucknow"]


def list_cities() -> list[CityConfig]:
    """Return all registered cities in insertion order."""
    return list(CITY_REGISTRY.values())
