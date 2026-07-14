"""TokenTracker — drop-in LLM cost tracker. Change one import line, see where your money goes."""

__version__ = "0.2.0"

from tokentracker.budgets import (
    Budget,
    check_all,
    check_budget,
    list_budgets,
    remove_budget,
    set_budget,
)
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
    "Budget",
    "set_budget",
    "list_budgets",
    "remove_budget",
    "check_budget",
    "check_all",
]
