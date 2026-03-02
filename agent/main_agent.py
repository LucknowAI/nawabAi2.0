import os
from pydantic_ai import Agent, RunContext
from pydantic_ai.ui import StateDeps
from agent.prompts.nawab_agent import prompt
from src.config.settings import Settings
from src.tools.serper import APIHandler

# Ensure the GEMINI_API_KEY env var is set for pydantic-ai's Google provider
if Settings.GEMINI_API_KEY:
    os.environ.setdefault("GEMINI_API_KEY", Settings.GEMINI_API_KEY)

_serper = APIHandler()

# Shared agent instance used by the AG-UI streaming endpoint
nawab_agent = Agent(
    "openai:gpt-5.2",
    system_prompt=prompt,
    deps_type=StateDeps[dict],
)


@nawab_agent.tool
async def google_search(ctx: RunContext[StateDeps[dict]], query: str) -> dict:
    """Search the web using Google (via Serper) and return organic results.

    Args:
        query: The search query string.
    """
    return await _serper.search_api(query)


@nawab_agent.tool
async def google_news(ctx: RunContext[StateDeps[dict]], keywords: list[str]) -> dict:
    """Search Google News via Serper for recent news articles.

    Args:
        keywords: List of keywords to search for (e.g. ["latest", "technology"]).
    """
    return await _serper.news_api(keywords)


@nawab_agent.tool
async def google_maps(ctx: RunContext[StateDeps[dict]], keywords: list[str]) -> dict:
    """Search Google Maps via Serper for local places or businesses.

    Args:
        keywords: List of keywords describing the place (e.g. ["hospitals", "Lucknow"]).
    """
    return await _serper.maps_api(keywords)


@nawab_agent.tool
async def google_videos(ctx: RunContext[StateDeps[dict]], keywords: list[str]) -> dict:
    """Search Google Videos via Serper for relevant video content.

    Args:
        keywords: List of keywords to search for (e.g. ["about lucknow"]).
    """
    return await _serper.video_api(keywords)
