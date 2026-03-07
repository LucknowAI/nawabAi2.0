"""City configuration dataclass."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CityConfig:
    """Immutable configuration for a supported city."""

    id: str
    """Slug used as a URL/state key, e.g. 'lucknow'."""

    name: str
    """Short display name, e.g. 'Lucknow'."""

    display_name: str
    """Long display name, e.g. 'Lucknow, Uttar Pradesh'."""

    coordinates: str
    """Google Maps ll parameter, e.g. '@26.8488213,80.8601114,12z'."""

    location_string: str
    """Human-readable location for news/video searches, e.g. 'Lucknow, Uttar Pradesh, India'."""

    system_prompt: str
    """Full system prompt / persona for the AI agent."""

    greeting: str
    """City-specific welcome message shown to users."""
