"""Prompt token budget — measure and enforce per-section caps. No LLM calls."""

import json
from pathlib import Path
from dataclasses import dataclass, field

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = Path(__file__).resolve().parent / 'budget_config.json'

# Character-estimate heuristic: ~3.5 chars per token for English text.
# Slightly conservative (real average is ~4 chars/token for Claude)
# so we over-count rather than under-count.
CHARS_PER_TOKEN = 3.5

_config: dict | None = None


def _load_config(path: Path | None = None) -> dict:
    """Load budget config from JSON. Cached after first load."""
    global _config
    if _config is not None and path is None:
        return _config
    config_path = path or _DEFAULT_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(f"Budget config not found: {config_path}")
    with open(config_path) as f:
        _config = json.load(f)
    return _config


def reload_config(path: Path | None = None) -> dict:
    """Force reload config (for tests or runtime tuning)."""
    global _config
    _config = None
    return _load_config(path)


def get_config() -> dict:
    """Get the loaded config, loading from default path if needed."""
    return _load_config()


# ── Token Counting ──


def estimate_tokens(text: str) -> int:
    """Estimate token count from character length. Fast, no dependencies.

    Uses ~3.5 chars/token heuristic. Slightly conservative — will
    over-estimate rather than under-estimate, which is the safe direction
    for budget enforcement.
    """
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN + 0.5))


# ── Section Enforcement ──


@dataclass
class TrimResult:
    """Result of enforcing a budget on a text section."""
    section_name: str
    original_tokens: int
    final_tokens: int
    trimmed: bool
    strategy: str
    text: str  # the (possibly trimmed) text

    @property
    def tokens_cut(self) -> int:
        return self.original_tokens - self.final_tokens


@dataclass
class BudgetReport:
    """Full budget report for a prompt assembly."""
    sections: list[TrimResult] = field(default_factory=list)
    total_input_tokens: int = 0
    reserved_output_tokens: int = 0
    model_context_window: int = 0

    @property
    def total_trimmed(self) -> int:
        return sum(s.tokens_cut for s in self.sections if s.trimmed)

    @property
    def any_trimmed(self) -> bool:
        return any(s.trimmed for s in self.sections)

    def log_trims(self):
        """Print trim events. Spec: 'Never silently drop content — always log what was trimmed.'"""
        for s in self.sections:
            if s.trimmed:
                print(f"  [Budget] TRIM {s.section_name}: {s.original_tokens} → "
                      f"{s.final_tokens} tokens (-{s.tokens_cut}) "
                      f"strategy={s.strategy}")
        if self.any_trimmed:
            print(f"  [Budget] Total input: {self.total_input_tokens} tokens "
                  f"(trimmed {self.total_trimmed})")
        else:
            print(f"  [Budget] Total input: {self.total_input_tokens} tokens (no trims)")


def _get_section_config(section_key: str, message_type: str) -> dict | None:
    """Look up a section's config. Returns None if not found (graceful default)."""
    cfg = get_config()
    sections = cfg.get('sections', {})
    msg_sections = sections.get(message_type, {})
    return msg_sections.get(section_key)


def _truncate_tail(text: str, max_tokens: int) -> str:
    """Truncate text from the end to fit within max_tokens."""
    suffix = '...'
    # Reserve space for the suffix
    max_chars = int(max_tokens * CHARS_PER_TOKEN) - len(suffix)
    if max_chars < 0:
        max_chars = 0
    if len(text) <= int(max_tokens * CHARS_PER_TOKEN):
        return text
    truncated = text[:max_chars].rsplit(' ', 1)[0]
    return truncated + suffix


def _split_header_items(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split lines into preserved header lines and droppable item lines.

    Header = leading empty lines + first non-indented, non-empty line.
    Items = everything after the header.
    Handles sections that start with '\\n' (leading empty line before header text).
    """
    header = []
    items_start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            # Empty/whitespace-only line — part of header prefix
            header.append(line)
            items_start = i + 1
        elif not line.startswith('  '):
            # Non-indented, non-empty line — this IS the header
            header.append(line)
            items_start = i + 1
            break
        else:
            # Indented line before any header — no header detected
            break
    items = lines[items_start:]
    return header, items


def _reassemble(header: list[str], items: list[str]) -> str:
    """Reassemble header + items into text."""
    return '\n'.join(header + items)


def _drop_oldest_items(text: str, max_tokens: int) -> str:
    """Drop items from the beginning, preserving header line(s)."""
    lines = text.split('\n')
    if len(lines) <= 1:
        return _truncate_tail(text, max_tokens)
    header, items = _split_header_items(lines)
    if not items:
        return _truncate_tail(text, max_tokens)
    while estimate_tokens(_reassemble(header, items)) > max_tokens and len(items) > 1:
        items.pop(0)
    result = _reassemble(header, items)
    if estimate_tokens(result) > max_tokens:
        return _truncate_tail(result, max_tokens)
    return result


def _drop_least_relevant_items(text: str, max_tokens: int) -> str:
    """Drop items from the end (assumed least relevant / lowest priority)."""
    lines = text.split('\n')
    if len(lines) <= 1:
        return _truncate_tail(text, max_tokens)
    header, items = _split_header_items(lines)
    if not items:
        return _truncate_tail(text, max_tokens)
    while estimate_tokens(_reassemble(header, items)) > max_tokens and len(items) > 1:
        items.pop()
    result = _reassemble(header, items)
    if estimate_tokens(result) > max_tokens:
        return _truncate_tail(result, max_tokens)
    return result


def enforce_section(
    section_name: str,
    text: str,
    message_type: str = 'system',
    max_tokens_override: int | None = None,
    strategy_override: str | None = None,
) -> TrimResult:
    """Enforce token budget on a single section.

    Args:
        section_name: Config key (e.g. 'S3_self_state', 'U6_conversation')
        text: The section text to check/trim
        message_type: 'system' or 'user'
        max_tokens_override: Override config max_tokens (for tests)
        strategy_override: Override config truncation strategy (for tests)

    Returns:
        TrimResult with possibly trimmed text
    """
    if not text:
        return TrimResult(
            section_name=section_name,
            original_tokens=0,
            final_tokens=0,
            trimmed=False,
            strategy='none',
            text='',
        )

    original_tokens = estimate_tokens(text)

    # Look up config
    section_cfg = _get_section_config(section_name, message_type)
    if section_cfg is None:
        # Missing section in config → graceful default: no enforcement
        return TrimResult(
            section_name=section_name,
            original_tokens=original_tokens,
            final_tokens=original_tokens,
            trimmed=False,
            strategy='none (no config)',
            text=text,
        )

    max_tokens = max_tokens_override if max_tokens_override is not None else section_cfg.get('max_tokens', 99999)
    strategy = strategy_override or section_cfg.get('truncation', 'none')

    # Under budget → pass through
    if original_tokens <= max_tokens:
        return TrimResult(
            section_name=section_name,
            original_tokens=original_tokens,
            final_tokens=original_tokens,
            trimmed=False,
            strategy=strategy,
            text=text,
        )

    # Fixed sections: warn but don't truncate
    if section_cfg.get('fixed', False) and strategy == 'none':
        print(f"  [Budget] WARNING: fixed section {section_name} is {original_tokens} tokens "
              f"(cap {max_tokens}) — cannot truncate")
        return TrimResult(
            section_name=section_name,
            original_tokens=original_tokens,
            final_tokens=original_tokens,
            trimmed=False,
            strategy='none (fixed)',
            text=text,
        )

    # Apply truncation strategy
    if strategy == 'none':
        trimmed_text = text  # no truncation allowed
    elif strategy == 'truncate_tail':
        trimmed_text = _truncate_tail(text, max_tokens)
    elif strategy in ('drop_oldest', 'drop_oldest_turns', 'drop_oldest_fields'):
        trimmed_text = _drop_oldest_items(text, max_tokens)
    elif strategy in ('drop_least_relevant', 'drop_least_relevant_first', 'drop_least_salient'):
        trimmed_text = _drop_least_relevant_items(text, max_tokens)
    else:
        # Unknown strategy — fall back to truncate_tail
        trimmed_text = _truncate_tail(text, max_tokens)

    final_tokens = estimate_tokens(trimmed_text)
    return TrimResult(
        section_name=section_name,
        original_tokens=original_tokens,
        final_tokens=final_tokens,
        trimmed=(trimmed_text != text),
        strategy=strategy,
        text=trimmed_text,
    )


def enforce_prompt(
    sections: list[tuple[str, str, str]],
) -> BudgetReport:
    """Enforce budget on all sections of a prompt.

    Args:
        sections: List of (section_name, text, message_type) tuples.
                  message_type is 'system' or 'user'.

    Returns:
        BudgetReport with all results and totals.
    """
    cfg = get_config()
    report = BudgetReport(
        reserved_output_tokens=cfg.get('reserved_output_tokens', 1500),
        model_context_window=cfg.get('model_context_window', 200000),
    )

    for section_name, text, message_type in sections:
        result = enforce_section(section_name, text, message_type)
        report.sections.append(result)

    report.total_input_tokens = sum(s.final_tokens for s in report.sections)
    report.log_trims()

    return report


def get_reserved_output_tokens() -> int:
    """Get the configured reserved output tokens (max_tokens for API call)."""
    cfg = get_config()
    return cfg.get('reserved_output_tokens', 1500)
