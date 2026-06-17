"""TokenTracker — drop-in LLM cost tracker. Change one import line, see where your money goes."""

__version__ = "0.1.0"

from tokentracker.client import AsyncOpenAI, OpenAI
from tokentracker.db import get_db, tag
from tokentracker.query import (
    cost_by_day,
    cost_by_model,
    cost_by_tag,
    insights,
    model_comparison,
    recent,
    spend_forecast,
    summary,
)

__all__ = [
    "OpenAI",
    "AsyncOpenAI",
    "get_db",
    "tag",
    "summary",
    "recent",
    "cost_by_model",
    "cost_by_day",
    "cost_by_tag",
    "spend_forecast",
    "insights",
    "model_comparison",
]
