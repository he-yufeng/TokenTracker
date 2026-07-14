"""Tests for pricing estimation."""

from tokentracker.pricing import estimate_cost


def test_known_model():
    cost = estimate_cost("gpt-4o", input_tokens=1000, output_tokens=500)
    assert cost is not None
    # 1000 * 2.50/1M + 500 * 10.00/1M = 0.0025 + 0.005 = 0.0075
    assert abs(cost - 0.0075) < 0.0001


def test_unknown_model():
    cost = estimate_cost("some-random-model", input_tokens=1000, output_tokens=500)
    assert cost is None


def test_openrouter_prefix():
    cost = estimate_cost("openai/gpt-4o", input_tokens=1000, output_tokens=500)
    assert cost is not None
    assert cost > 0


def test_zero_tokens():
    cost = estimate_cost("gpt-4o", input_tokens=0, output_tokens=0)
    assert cost == 0.0


def test_date_suffix():
    """OpenAI returns model names like gpt-4o-2024-08-06."""
    cost = estimate_cost("gpt-4o-2024-08-06", input_tokens=1000, output_tokens=500)
    assert cost is not None
    assert abs(cost - 0.0075) < 0.0001


def test_date_suffix_mini():
    cost = estimate_cost("gpt-4o-mini-2024-07-18", input_tokens=1000, output_tokens=500)
    assert cost is not None
    assert cost > 0


def test_prefix_plus_date_suffix():
    cost = estimate_cost("openai/gpt-4o-2024-08-06", input_tokens=1000, output_tokens=500)
    assert cost is not None


def test_openrouter_wrapper_prefix():
    cost = estimate_cost(
        "openrouter/openai/gpt-4o-2024-08-06",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost is not None
    assert abs(cost - 0.0075) < 0.0001


def test_variant_suffix():
    cost = estimate_cost("openai/gpt-4o:nitro", input_tokens=1000, output_tokens=500)
    assert cost is not None
    assert abs(cost - 0.0075) < 0.0001


def test_model_matching_is_case_insensitive():
    cost = estimate_cost("OPENAI/GPT-4O", input_tokens=1000, output_tokens=500)
    assert cost is not None
    assert abs(cost - 0.0075) < 0.0001


def test_current_anthropic_opus():
    """Claude Opus 4.8: $5 input / $25 output per 1M."""
    cost = estimate_cost("claude-opus-4-8", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost is not None
    assert abs(cost - (5.00 + 25.00)) < 0.0001


def test_current_anthropic_sonnet():
    """Claude Sonnet 5: $3 input / $15 output per 1M."""
    cost = estimate_cost("claude-sonnet-5", input_tokens=1000, output_tokens=500)
    assert cost is not None
    # 1000 * 3.00/1M + 500 * 15.00/1M = 0.003 + 0.0075
    assert abs(cost - 0.0105) < 0.0001


def test_current_openai_flagship():
    """GPT-5.5: $5 input / $30 output per 1M."""
    cost = estimate_cost("gpt-5.5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost is not None
    assert abs(cost - (5.00 + 30.00)) < 0.0001


def test_current_model_openrouter_prefix():
    cost = estimate_cost("anthropic/claude-opus-4-8", input_tokens=1000, output_tokens=500)
    assert cost is not None
    assert cost > 0


def test_anthropic_compact_date_suffix():
    """Anthropic API ids carry a compact date suffix, e.g. claude-haiku-4-5-20251001;
    it must normalize to the base model rather than falling through as unknown."""
    cost = estimate_cost("claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=500)
    assert cost is not None
    assert cost > 0
