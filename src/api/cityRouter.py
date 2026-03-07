"""City router — exposes the list of supported cities for the frontend dropdown."""

from fastapi import APIRouter

from src.cities.registry import list_cities

city_router = APIRouter(prefix="/cities", tags=["Cities"])


@city_router.get("/")
async def get_cities():
    """
    Return the list of supported cities.

    Frontend uses this to render the city-selector dropdown.
    """
    return [
        {
            "id": city.id,
            "name": city.name,
            "display_name": city.display_name,
        }
        for city in list_cities()
    ]
