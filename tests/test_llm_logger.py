"""Unit tests for llm_logger cost estimation."""

import pytest
import llm_logger


def test_estimate_cost_claude_sonnet():
    """Test cost estimation for Claude Sonnet 4.5."""
    cost = llm_logger.estimate_cost(
        provider='anthropic',
        model='claude-sonnet-4-5-20250929',
        input_tokens=1000,
        output_tokens=500,
    )
    # 1000 input @ $0.003/1K = $0.003
    # 500 output @ $0.015/1K = $0.0075
    # Total = $0.0105
    assert abs(cost - 0.0105) < 0.0001


def test_estimate_cost_claude_opus():
    """Test cost estimation for Claude Opus 4."""
    cost = llm_logger.estimate_cost(
        provider='anthropic',
        model='claude-opus-4-20250514',
        input_tokens=2000,
        output_tokens=1000,
    )
    # 2000 input @ $0.015/1K = $0.03
    # 1000 output @ $0.075/1K = $0.075
    # Total = $0.105
    assert abs(cost - 0.105) < 0.0001


def test_estimate_cost_imagen():
    """Test cost estimation for Gemini Imagen."""
    cost = llm_logger.estimate_cost(
        provider='google',
        model='imagen-4.0-generate-001',
        images_generated=3,
    )
    # 3 images @ $0.04 = $0.12
    assert abs(cost - 0.12) < 0.0001


def test_estimate_cost_unknown_model_fallback():
    """Test fallback pricing for unknown models."""
    cost = llm_logger.estimate_cost(
        provider='unknown',
        model='some-future-model',
        input_tokens=1000,
        output_tokens=500,
    )
    # Should fallback to Sonnet 4.5 pricing
    # 1000 input @ $0.003/1K = $0.003
    # 500 output @ $0.015/1K = $0.0075
    # Total = $0.0105
    assert abs(cost - 0.0105) < 0.0001


def test_estimate_cost_zero_tokens():
    """Test cost estimation with zero tokens."""
    cost = llm_logger.estimate_cost(
        provider='anthropic',
        model='claude-sonnet-4-5-20250929',
        input_tokens=0,
        output_tokens=0,
    )
    assert cost == 0.0


def test_estimate_cost_realistic_cortex_call():
    """Test realistic cortex call cost."""
    # Typical cortex call: ~2K input, ~800 output
    cost = llm_logger.estimate_cost(
        provider='anthropic',
        model='claude-sonnet-4-5-20250929',
        input_tokens=2000,
        output_tokens=800,
    )
    # 2000 input @ $0.003/1K = $0.006
    # 800 output @ $0.015/1K = $0.012
    # Total = $0.018
    assert abs(cost - 0.018) < 0.0001
    assert cost < 0.02  # Should be under 2 cents per call


if __name__ == '__main__':
    # Run tests
    test_estimate_cost_claude_sonnet()
    test_estimate_cost_claude_opus()
    test_estimate_cost_imagen()
    test_estimate_cost_unknown_model_fallback()
    test_estimate_cost_zero_tokens()
    test_estimate_cost_realistic_cortex_call()
    print('✓ All llm_logger cost estimation tests passed')
