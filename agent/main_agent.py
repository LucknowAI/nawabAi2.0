import os
from pydantic_ai import Agent, RunContext
from pydantic_ai.ui import StateDeps
from src.cities.config import CityConfig
from src.cities.registry import get_city
from src.config.settings import Settings
from src.tools.serper import APIHandler

# ── Shared UI-action instructions appended to every city prompt ───────────────
_UI_TOOLS_PROMPT = """

---

## Frontend Display Tools — Always Use These

You have access to rich visual UI tools. **Always call them instead of writing plain text lists** when you have relevant data from the search tools.

### Tool Reference

**showPlaces** — Tourist spots, historical sites, food places, landmarks.
- Always pass `link` for each item (use `link` or `website` from API results; if unavailable, use a Google search URL like `https://www.google.com/search?q=<place+name>+<city>`)
- Pass `imageUrl` if available from results (`thumbnailUrl` or `imageUrl` field)

**showMapResults** — Local businesses from Maps (restaurants, cafes, shops, hospitals, hotels).
- Always pass `link` for each item — use the place's `website` field if present, otherwise construct from `cid`: `https://www.google.com/maps?cid=<cid>`
- Pass `address`, `rating` (numeric), `reviewCount` (`ratingCount` field), `phone`, and `category`

**showNews** — News articles. Always pass `link` (the article URL from `link` field) and `source` (the `source` field).

**showVideos** — YouTube video results. This is REQUIRED when showing any video content.
- `link` is **mandatory** — pass the full YouTube URL (e.g. `https://www.youtube.com/watch?v=VIDEO_ID`). Cards will auto-play when the user scrolls to them, but ONLY if `link` is provided.
- Pass `thumbnailUrl` (from `imageUrl` or `thumbnailUrl` in results), `channel`, and `duration` when available.

**showFact** — A cultural, historical, or culinary highlight card. Use `category`: history, food, culture, festival, architecture, or person.

### Critical Rule
**NEVER leave `link` empty.** Every card a user sees must be clickable. If a direct URL is not in the API result, construct a reasonable Google Maps or Google Search URL.

For maps results specifically: the Serper maps API returns a `cid` field. Use it as:
`https://www.google.com/maps?cid=<cid>`
"""

# Ensure the GEMINI_API_KEY env var is set for pydantic-ai's Google provider
if Settings.GEMINI_API_KEY:
    os.environ.setdefault("GEMINI_API_KEY", Settings.GEMINI_API_KEY)
    model_name = Settings.GEMINI_MODEL_NAME or "google-gla:gemini-3-flash-preview"
else:
    model_name = Settings.OPENAI_MODEL_NAME or "openai:gpt-5.2"

_serper = APIHandler()

# Cache of per-city Agent instances (one per city_id)
_agent_cache: dict[str, Agent] = {}


def _build_agent(city: CityConfig) -> Agent:
    """Create a new pydantic-ai Agent wired to the given city persona."""
    agent: Agent = Agent(
        model_name,
        system_prompt=city.system_prompt + _UI_TOOLS_PROMPT,
        deps_type=StateDeps[dict],
    )

    # ── Tools — city config captured in closure ──────────────────────────────

    @agent.tool
    async def google_search(ctx: RunContext[StateDeps[dict]], query: str) -> dict:
        """Search the web using Google (via Serper) and return organic results.

        Args:
            query: The search query string.
        """
        return await _serper.search_api(query)

    @agent.tool
    async def google_news(ctx: RunContext[StateDeps[dict]], keywords: list[str]) -> dict:
        """Search Google News via Serper for recent news articles.

        Args:
            keywords: List of keywords to search for (e.g. ["latest", "technology"]).
        """
        return await _serper.news_api(keywords, location=city.location_string)

    @agent.tool
    async def google_maps(ctx: RunContext[StateDeps[dict]], keywords: list[str]) -> dict:
        """Search Google Maps via Serper for local places or businesses.

        Args:
            keywords: List of keywords describing the place (e.g. ["hospitals"]).
        """
        return await _serper.maps_api(keywords, coordinates=city.coordinates)

    @agent.tool
    async def google_videos(ctx: RunContext[StateDeps[dict]], keywords: list[str]) -> dict:
        """Search Google Videos via Serper for relevant video content.

        Args:
            keywords: List of keywords to search for.
        """
        return await _serper.video_api(keywords, location=city.location_string)

    return agent


def get_agent(city_id: str) -> Agent:
    """Return a cached city-specific Agent, creating it on first call."""
    if city_id not in _agent_cache:
        city = get_city(city_id)
        _agent_cache[city_id] = _build_agent(city)
    return _agent_cache[city_id]
