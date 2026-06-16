"""TokenTracker — drop-in LLM cost tracker. Change one import line, see where your money goes."""

__version__ = "0.1.0"

from tokentracker.client import AsyncOpenAI, OpenAI
from tokentracker.db import get_db
from tokentracker.query import (
    cost_by_day,
    cost_by_model,
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
    "summary",
    "recent",
    "cost_by_model",
    "cost_by_day",
    "spend_forecast",
    "insights",
    "model_comparison",
]
