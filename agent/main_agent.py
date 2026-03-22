import os
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.ui import StateDeps
from ag_ui.core import EventType
from ag_ui.core.events import StateSnapshotEvent
from src.cities.config import CityConfig
from src.cities.registry import get_city
from src.config.settings import Settings
from src.tools.serper import APIHandler
from src.utils.util_logger.logger import logger


class NawabState(BaseModel):
    """Shared state synced between the Nawab agent and the frontend UI."""

    city_id: str = ""
    active_search: dict = {}
    # user_preferences holds hints the agent discovers during conversation
    # e.g. {"cuisine": ["biryani", "kebabs"], "budget": "mid-range", "dietary": ["vegetarian"]}
    user_preferences: dict = {}
    thinking_steps: list[dict] = []  # [{tool, query, tags}]

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

**showVideos** — YouTube video results. **Always use this when the user asks for videos, YouTube content, or any visual tour.** Also proactively include 2-4 videos alongside place results when the query is exploratory (e.g. "what to see in Lucknow", "food guide", "heritage walk").
- Call `google_videos` first, then pass results to `showVideos`.
- `link` is **mandatory** — pass the full YouTube URL (e.g. `https://www.youtube.com/watch?v=VIDEO_ID`). Cards will auto-play when the user scrolls to them, but ONLY if `link` is provided.
- Pass `thumbnailUrl` (from `imageUrl` or `thumbnailUrl` in results), `channel`, and `duration` when available.

**showImages** — A visual gallery of images. Use this when the user asks to "see", "show me pictures", "what does X look like", or any visually-oriented query. Also call alongside `showPlaces` for scenic/heritage/food queries to make the response visually rich.
- Call `google_images` first, then pass the results to `showImages`.
- Pass `imageUrl` (full-res URL), `thumbnailUrl`, `title`, and `link` (source page URL) for every image.
- Pass at least 6 images when available.

**showFact** — A cultural, historical, or culinary highlight card. Use `category`: history, food, culture, festival, architecture, or person.

**showSources** — Call at the END of every response (after all search and display tools) with the source URLs you referenced.
- Pass `title` (article/page title) and `url` for each source
- Collect from: organic search result `link` fields, news `link` fields, maps website URLs
- Include 3–5 of the most relevant and directly useful sources
- Call ONLY once, at the very end of your response — never mid-search

### Critical Rule
**NEVER leave `link` empty.** Every card a user sees must be clickable. If a direct URL is not in the API result, construct a reasonable Google Maps or Google Search URL.

For maps results specifically: the Serper maps API returns a `cid` field. Use it as:
`https://www.google.com/maps?cid=<cid>`

---

## Search Tools — When to Use Each

- `google_search` — general web search, facts, overviews
- `google_maps` — local businesses, restaurants, shops, hospitals with addresses and ratings
- `google_news` — current events, recent news
- `google_videos` — YouTube videos; always follow with `showVideos`
- `google_images` — photos and images; always follow with `showImages`

For exploratory queries ("tell me about X", "show me Y", "best Z in city"), **call multiple search tools** to build a rich multi-section response. A typical rich response might call: `google_maps` → `showMapResults`, `google_videos` → `showVideos`, `google_images` → `showImages`.

---

## Agentic Behaviour Tools

### update_exploration_context
Call this ONCE at the very start of your search with your overall intent. Then call ALL required search tools together in a single parallel batch — do not call them one at a time.
- `query`: a short human-readable description of what you're searching for (e.g. "biryani restaurants near Hazratganj")
- `search_type`: one of `places`, `restaurants`, `news`, `events`, `videos`, `shopping`, `images`
- `tags`: up to 4 relevant keywords
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
    _model_settings = None
    if model_name.startswith("openai:"):
        try:
            from pydantic_ai.models.openai import OpenAIModelSettings
            _model_settings = OpenAIModelSettings(parallel_tool_calls=True)
        except ImportError:
            pass

    agent: Agent = Agent(
        model_name,
        system_prompt=city.system_prompt + _UI_TOOLS_PROMPT,
        deps_type=StateDeps[NawabState],
        model_settings=_model_settings,
    )

    # ── Tools — city config captured in closure ──────────────────────────────

    @agent.tool
    async def google_search(ctx: RunContext[StateDeps[NawabState]], query: str) -> dict:
        """Search the web using Google (via Serper) and return organic results.

        Args:
            query: The search query string.
        """
        try:
            return await _serper.search_api(query)
        except Exception as e:
            logger.error(f"google_search tool error: {e}")
            return {"error": "Search temporarily unavailable. Please try again."}

    @agent.tool
    async def google_news(ctx: RunContext[StateDeps[NawabState]], keywords: list[str]) -> dict:
        """Search Google News via Serper for recent news articles.

        Args:
            keywords: List of keywords to search for (e.g. ["latest", "technology"]).
        """
        try:
            return await _serper.news_api(keywords, location=city.location_string)
        except Exception as e:
            logger.error(f"google_news tool error: {e}")
            return {"error": "News search temporarily unavailable. Please try again."}

    @agent.tool
    async def google_maps(ctx: RunContext[StateDeps[NawabState]], keywords: list[str]) -> dict:
        """Search Google Maps via Serper for local places or businesses.

        Args:
            keywords: List of keywords describing the place (e.g. ["hospitals"]).
        """
        try:
            return await _serper.maps_api(keywords, coordinates=city.coordinates)
        except Exception as e:
            logger.error(f"google_maps tool error: {e}")
            return {"error": "Maps search temporarily unavailable. Please try again."}

    @agent.tool
    async def google_videos(ctx: RunContext[StateDeps[NawabState]], keywords: list[str]) -> dict:
        """Search Google Videos via Serper for relevant video content.

        Args:
            keywords: List of keywords to search for.
        """
        try:
            return await _serper.video_api(keywords, location=city.location_string)
        except Exception as e:
            logger.error(f"google_videos tool error: {e}")
            return {"error": "Video search temporarily unavailable. Please try again."}

    @agent.tool
    async def google_images(ctx: RunContext[StateDeps[NawabState]], keywords: list[str]) -> dict:
        """Search Google Images via Serper for photos and visual content.

        Use this when the user asks to see pictures, photos, or images of a place,
        food, festival, or any visually-oriented topic. Always follow with showImages.

        Args:
            keywords: List of keywords describing what images to find.
        """
        try:
            return await _serper.images_api(keywords, location=city.location_string)
        except Exception as e:
            logger.error(f"google_images tool error: {e}")
            return {"error": "Image search temporarily unavailable. Please try again."}

    # ── Shared-state tool ─────────────────────────────────────────────────────

    @agent.tool
    async def update_exploration_context(
        ctx: RunContext[StateDeps[NawabState]],
        query: str,
        search_type: str,
        tags: list[str] = [],
    ) -> StateSnapshotEvent:
        """Push a live exploration context update to the frontend UI.

        Call this right before each major search so the user can see what you
        are currently looking for.

        Args:
            query: Short description of what is being searched (e.g. "top biryani spots near Hazratganj").
            search_type: Category of search — one of: places, restaurants, news, events, videos, shopping.
            tags: Up to 4 relevant keywords or tags (e.g. ["biryani", "Lucknow", "dine-in"]).
        """
        # Accumulate this search step in thinking_steps for the frontend ThinkingPanel
        ctx.deps.state.thinking_steps.append({
            "tool": search_type,
            "query": query,
            "tags": tags[:4],
        })
        return StateSnapshotEvent(
            type=EventType.STATE_SNAPSHOT,
            snapshot={
                "active_search": {
                    "query": query,
                    "type": search_type,
                    "tags": tags[:4],
                },
                "thinking_steps": ctx.deps.state.thinking_steps,
            },
        )

    return agent


def get_agent(city_id: str) -> Agent:
    """Return a cached city-specific Agent, creating it on first call."""
    if city_id not in _agent_cache:
        city = get_city(city_id)
        _agent_cache[city_id] = _build_agent(city)
    return _agent_cache[city_id]
