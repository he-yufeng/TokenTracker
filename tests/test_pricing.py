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
