"""Model pricing data (cost per 1M tokens)."""

from __future__ import annotations

# Prices in USD per 1M tokens: (input_cost, output_cost)
# Updated March 2026. Add new models as needed.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o1-mini": (1.10, 4.40),
    "o3-mini": (1.10, 4.40),
    # Anthropic
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    # Anthropic via OpenRouter
    "anthropic/claude-sonnet-4": (3.00, 15.00),
    "anthropic/claude-opus-4-6": (15.00, 75.00),
    "anthropic/claude-haiku-4-5": (0.80, 4.00),
    # OpenAI via OpenRouter
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    # Google
    "google/gemini-2.5-pro": (1.25, 10.00),
    "google/gemini-2.5-flash": (0.15, 0.60),
    # DeepSeek
    "deepseek/deepseek-chat": (0.14, 0.28),
    "deepseek/deepseek-reasoner": (0.55, 2.19),
    # Meta (via OpenRouter)
    "meta-llama/llama-3.1-405b-instruct": (2.00, 2.00),
    "meta-llama/llama-3.1-70b-instruct": (0.52, 0.75),
    "meta-llama/llama-3.1-8b-instruct": (0.05, 0.08),
}


def _normalize_model_name(model: str) -> str | None:
    """Try to match a model name to our pricing table, handling date suffixes and prefixes.

    OpenAI returns names like 'gpt-4o-2024-08-06', OpenRouter uses 'openai/gpt-4o', etc.
    """
    import re

    cleaned = model.strip().lower()
    candidates = [cleaned]

    # OpenRouter sometimes adds a variant marker, e.g. openai/gpt-4o:nitro.
    if ":" in cleaned:
        candidates.append(cleaned.split(":", 1)[0])

    # Some proxy logs include an extra routing prefix before the provider.
    if cleaned.startswith("openrouter/"):
        candidates.append(cleaned[len("openrouter/"):])

    provider_prefixes = ("openai/", "anthropic/", "google/", "deepseek/", "meta-llama/")
    for candidate in list(candidates):
        for prefix in provider_prefixes:
            if candidate.startswith(prefix):
                candidates.append(candidate[len(prefix):])

    for candidate in list(candidates):
        candidates.append(re.sub(r"-\d{4}-\d{2}-\d{2}$", "", candidate))

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate in MODEL_PRICES:
            return candidate

    return None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate cost in USD for a given model and token counts.

    Returns None if the model isn't in the pricing table.
    """
    key = _normalize_model_name(model)
    if key is None:
        return None
    input_cost, output_cost = MODEL_PRICES[key]
    return (input_tokens * input_cost + output_tokens * output_cost) / 1_000_000


def blended_price(model: str) -> float | None:
    """Average of input and output price per 1M tokens, or None if the model is unknown.

    Useful for ranking models by rough relative cost without knowing the token mix.
    """
    key = _normalize_model_name(model)
    if key is None:
        return None
    input_cost, output_cost = MODEL_PRICES[key]
    return (input_cost + output_cost) / 2
