"""Tests for prompt/budget.py — token counting and section enforcement."""

import json
import pytest
from pathlib import Path
from prompt.budget import (
    estimate_tokens,
    enforce_section,
    enforce_prompt,
    get_reserved_output_tokens,
    reload_config,
    get_config,
    TrimResult,
    BudgetReport,
    CHARS_PER_TOKEN,
)


# ── Fixtures ──

@pytest.fixture(autouse=True)
def load_default_config():
    """Ensure config is loaded from default path for each test."""
    reload_config()
    yield


# ── Token Estimation ──

class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens('') == 0

    def test_short_text(self):
        # "Hello" = 5 chars → 5/3.5 ≈ 1.4 → rounds to 1
        result = estimate_tokens('Hello')
        assert result >= 1

    def test_medium_text(self):
        # 100 chars → ~29 tokens
        text = 'a' * 100
        result = estimate_tokens(text)
        assert 25 <= result <= 35

    def test_realistic_text(self):
        text = "I feel deeply lonely. The shop has been too quiet. I could use some company."
        result = estimate_tokens(text)
        # ~76 chars → ~22 tokens
        assert 15 <= result <= 30

    def test_long_text(self):
        text = 'word ' * 1000  # ~5000 chars
        result = estimate_tokens(text)
        # ~5000/3.5 ≈ 1429 tokens
        assert 1300 <= result <= 1600


# ── Config Loading ──

class TestConfigLoading:
    def test_default_config_loads(self):
        cfg = get_config()
        assert 'model_context_window' in cfg
        assert 'reserved_output_tokens' in cfg
        assert 'sections' in cfg

    def test_config_has_system_sections(self):
        cfg = get_config()
        system = cfg['sections']['system']
        assert 'S1_preamble' in system
        assert 'S13_output_schema' in system

    def test_config_has_user_sections(self):
        cfg = get_config()
        user = cfg['sections']['user']
        assert 'U1_perceptions' in user
        assert 'U11_routing_metadata' in user

    def test_reserved_output_tokens(self):
        assert get_reserved_output_tokens() == 1500

    def test_reload_config(self):
        cfg = reload_config()
        assert cfg is not None

    def test_missing_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            reload_config(tmp_path / 'nonexistent.json')
        # Restore default
        reload_config()


# ── Section Enforcement: Under Budget ──

class TestUnderBudget:
    def test_short_text_passes_through(self):
        result = enforce_section('U1_perceptions', 'Short text', 'user')
        assert not result.trimmed
        assert result.text == 'Short text'
        assert result.tokens_cut == 0

    def test_empty_text_passes_through(self):
        result = enforce_section('U1_perceptions', '', 'user')
        assert not result.trimmed
        assert result.text == ''
        assert result.original_tokens == 0

    def test_fixed_section_under_budget(self):
        result = enforce_section('S1_preamble', 'Short preamble', 'system')
        assert not result.trimmed
        assert result.text == 'Short preamble'


# ── Section Enforcement: Over Budget ──

class TestOverBudget:
    def test_truncate_tail_strategy(self):
        # U5_consume_framing has max_tokens=600 and truncation=truncate_tail
        # Generate text way over 600 tokens (~2100 chars)
        long_text = "WHAT I'M CONSUMING:\n" + ("This is a very long content block. " * 100)
        result = enforce_section('U5_consume_framing', long_text, 'user')
        assert result.trimmed
        assert result.final_tokens <= 600
        assert result.text.endswith('...')
        assert result.tokens_cut > 0

    def test_drop_oldest_strategy(self):
        # S10_recent_suppressions has max_tokens=100, truncation=drop_oldest
        lines = ['WHAT YOU ALMOST DID (but held back):']
        for i in range(20):
            lines.append(f"  - wanted to do thing {i} (impulse 0.8) — held back: reason {i}")
        long_text = '\n'.join(lines)

        result = enforce_section('S10_recent_suppressions', long_text, 'system')
        assert result.trimmed
        assert result.final_tokens <= 100
        # Header should be preserved
        assert 'WHAT YOU ALMOST DID' in result.text

    def test_drop_least_relevant_strategy(self):
        # U3_memories has max_tokens=1000, truncation=drop_least_relevant_first
        lines = ['MEMORIES SURFACING:']
        for i in range(30):
            lines.append(f"  [Memory {i}]")
            lines.append(f"  This is the content of memory {i}, which is quite detailed and long enough to take up some tokens in the prompt.")
        long_text = '\n'.join(lines)

        result = enforce_section('U3_memories', long_text, 'user')
        assert result.trimmed
        assert result.final_tokens <= 1000
        # Header should be preserved
        assert 'MEMORIES SURFACING' in result.text

    def test_header_preserved_with_leading_newline(self):
        """Sections built with leading \\n (e.g. '\\nMEMORIES SURFACING:') must
        keep the header after trimming — not drop it as an 'oldest item'."""
        lines = ["\nMEMORIES SURFACING:"]
        for i in range(60):
            lines.append(f"  [Memory {i}]")
            lines.append(f"  Content of memory {i} with enough detailed text to fill the budget and force trimming to occur.")
        long_text = "\n".join(lines)

        result = enforce_section('U3_memories', long_text, 'user')
        assert result.trimmed
        assert 'MEMORIES SURFACING' in result.text

    def test_header_preserved_drop_oldest_with_leading_newline(self):
        """drop_oldest must preserve header even when text starts with \\n."""
        lines = ["\nTHINGS ON MY MIND:"]
        for i in range(20):
            lines.append(f"  [question] Thread {i} — some extended content here about the topic.")
        long_text = "\n".join(lines)

        result = enforce_section('U4_active_threads', long_text, 'user')
        assert result.trimmed
        assert 'THINGS ON MY MIND' in result.text

    def test_fixed_section_warns_but_no_truncation(self, capsys):
        # S13_output_schema is fixed=true, truncation=none
        # Generate text over 550 tokens (~1925 chars)
        long_text = "OUTPUT SCHEMA:\n" + ("x" * 2500)
        result = enforce_section('S13_output_schema', long_text, 'system')
        # Fixed sections should NOT be truncated
        assert not result.trimmed
        assert result.text == long_text
        # But should warn
        captured = capsys.readouterr()
        assert 'WARNING' in captured.out
        assert 'S13_output_schema' in captured.out


# ── Missing Section in Config ──

class TestMissingSectionConfig:
    def test_unknown_section_passes_through(self):
        result = enforce_section('NONEXISTENT_SECTION', 'Some text', 'user')
        assert not result.trimmed
        assert result.text == 'Some text'
        assert 'no config' in result.strategy

    def test_unknown_message_type_passes_through(self):
        result = enforce_section('U1_perceptions', 'Some text', 'nonexistent_type')
        assert not result.trimmed
        assert result.text == 'Some text'


# ── Override Parameters ──

class TestOverrides:
    def test_max_tokens_override(self):
        text = "word " * 100  # ~500 chars → ~143 tokens
        result = enforce_section('U1_perceptions', text, 'user', max_tokens_override=10)
        assert result.trimmed
        assert result.final_tokens <= 10

    def test_strategy_override(self):
        text = "Header\n  line 1\n  line 2\n  line 3\n  line 4\n  line 5"
        result = enforce_section('U1_perceptions', text, 'user',
                                 max_tokens_override=5,
                                 strategy_override='drop_oldest')
        assert result.trimmed


# ── Full Prompt Enforcement ──

class TestEnforcePrompt:
    def test_all_under_budget(self):
        sections = [
            ('S1_preamble', 'Short preamble', 'system'),
            ('U1_perceptions', 'Short perception', 'user'),
        ]
        report = enforce_prompt(sections)
        assert not report.any_trimmed
        assert report.total_input_tokens > 0
        assert report.total_trimmed == 0

    def test_one_section_over_budget(self):
        # Build conversation with separate lines (like real conversation turns)
        convo_lines = ["CONVERSATION:"]
        for i in range(30):
            convo_lines.append(f"  Visitor: This is a fairly long message number {i} with some detail about the topic at hand.")
        long_text = "\n".join(convo_lines)
        sections = [
            ('U1_perceptions', 'Short', 'user'),
            ('U6_conversation', long_text, 'user'),
        ]
        report = enforce_prompt(sections)
        assert report.any_trimmed
        assert report.total_trimmed > 0

    def test_report_has_correct_token_totals(self):
        sections = [
            ('U1_perceptions', 'Hello world', 'user'),
            ('U11_routing_metadata', 'TOKEN BUDGET: 3000', 'user'),
        ]
        report = enforce_prompt(sections)
        expected = sum(estimate_tokens(text) for _, text, _ in sections)
        assert report.total_input_tokens == expected


# ── Log Output ──

class TestLogOutput:
    def test_trim_logged(self, capsys):
        long_text = "CONVERSATION:\n" + ("  Visitor: message. " * 100)
        enforce_section('U6_conversation', long_text, 'user')
        # The enforce_section itself doesn't log, but enforce_prompt does
        # Let's test via enforce_prompt
        sections = [('U6_conversation', long_text, 'user')]
        report = enforce_prompt(sections)
        captured = capsys.readouterr()
        assert '[Budget]' in captured.out
        assert 'TRIM' in captured.out or 'no trims' in captured.out

    def test_no_trim_logged(self, capsys):
        sections = [('U1_perceptions', 'Short', 'user')]
        report = enforce_prompt(sections)
        captured = capsys.readouterr()
        assert 'no trims' in captured.out


# ── Integration: Budget Config Consistency ──

class TestBudgetConfigIntegrity:
    def test_all_system_sections_have_max_tokens(self):
        cfg = get_config()
        for key, section in cfg['sections']['system'].items():
            if key.startswith('_'):
                continue
            assert 'max_tokens' in section, f"System section {key} missing max_tokens"

    def test_all_user_sections_have_max_tokens(self):
        cfg = get_config()
        for key, section in cfg['sections']['user'].items():
            if key.startswith('_'):
                continue
            assert 'max_tokens' in section, f"User section {key} missing max_tokens"

    def test_all_sections_have_truncation(self):
        cfg = get_config()
        for msg_type in ('system', 'user'):
            for key, section in cfg['sections'][msg_type].items():
                if key.startswith('_'):
                    continue
                assert 'truncation' in section, f"{msg_type}/{key} missing truncation"

    def test_total_budget_within_context_window(self):
        cfg = get_config()
        totals = cfg['totals']
        max_total = totals['max_system_tokens'] + totals['max_user_tokens']
        context_window = cfg['model_context_window']
        reserved_output = cfg['reserved_output_tokens']
        assert max_total + reserved_output < context_window, (
            f"Total budget ({max_total} + {reserved_output} = {max_total + reserved_output}) "
            f"exceeds context window ({context_window})"
        )
