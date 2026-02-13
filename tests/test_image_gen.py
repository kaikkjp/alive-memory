"""Tests for pipeline.image_gen — adapter selection, resolution mapping, errors."""

import os
import pytest

# Import module internals for unit testing.
from pipeline.image_gen import (
    _resolve_seedream_image_size,
    _SEEDREAM_SIZE_MAP,
    _init_adapter,
    SeedreamAdapter,
    GenericFalAdapter,
)


# ─── _resolve_seedream_image_size ────────────────────────────────────────


class TestResolveSeedreamImageSize:
    """Verify aspect_ratio × resolution → image_size mapping."""

    # ── 1K tier: all ratios should return a preset string ──

    @pytest.mark.parametrize(
        'aspect_ratio, expected',
        [
            ('1:1', 'square'),
            ('16:9', 'landscape_16_9'),
            ('9:16', 'portrait_16_9'),
            ('4:3', 'landscape_4_3'),
            ('3:4', 'portrait_4_3'),
            ('3:2', 'landscape_4_3'),
            ('2:3', 'portrait_4_3'),
        ],
    )
    def test_1k_returns_preset_string(self, aspect_ratio, expected):
        result = _resolve_seedream_image_size(aspect_ratio, '1K')
        assert result == expected
        assert isinstance(result, str)

    # ── 2K tier: should differ from 1K (P2 regression check) ──

    @pytest.mark.parametrize('aspect_ratio', ['16:9', '9:16', '4:3', '3:4', '3:2', '2:3'])
    def test_2k_returns_explicit_dimensions(self, aspect_ratio):
        result = _resolve_seedream_image_size(aspect_ratio, '2K')
        assert isinstance(result, dict), (
            f'2K for {aspect_ratio} should return {{width, height}}, got {result!r}'
        )
        assert 'width' in result
        assert 'height' in result

    @pytest.mark.parametrize('aspect_ratio', ['16:9', '9:16', '4:3', '3:4', '3:2', '2:3'])
    def test_2k_differs_from_1k(self, aspect_ratio):
        r1k = _resolve_seedream_image_size(aspect_ratio, '1K')
        r2k = _resolve_seedream_image_size(aspect_ratio, '2K')
        assert r1k != r2k, (
            f'1K and 2K should produce different sizes for {aspect_ratio}'
        )

    def test_1_1_2k_returns_square_hd(self):
        assert _resolve_seedream_image_size('1:1', '2K') == 'square_hd'

    # ── 4K tier: all ratios should return auto_4K ──

    @pytest.mark.parametrize('aspect_ratio', list(_SEEDREAM_SIZE_MAP.keys()))
    def test_4k_returns_auto_4k(self, aspect_ratio):
        assert _resolve_seedream_image_size(aspect_ratio, '4K') == 'auto_4K'

    # ── Case insensitivity ──

    def test_resolution_case_insensitive(self):
        assert _resolve_seedream_image_size('1:1', '1k') == 'square'
        assert _resolve_seedream_image_size('1:1', '4k') == 'auto_4K'

    # ── Error paths ──

    def test_unsupported_resolution_raises(self):
        with pytest.raises(ValueError, match='Unsupported resolution tier'):
            _resolve_seedream_image_size('1:1', '8K')

    def test_unsupported_aspect_ratio_raises(self):
        with pytest.raises(ValueError, match='No Seedream mapping for aspect_ratio'):
            _resolve_seedream_image_size('21:9', '1K')

    # ── Completeness: every ratio has all three tiers ──

    @pytest.mark.parametrize('aspect_ratio', list(_SEEDREAM_SIZE_MAP.keys()))
    def test_all_tiers_present(self, aspect_ratio):
        for tier in ('1K', '2K', '4K'):
            result = _resolve_seedream_image_size(aspect_ratio, tier)
            assert result is not None


# ─── Adapter selection (_init_adapter) ───────────────────────────────────


class TestInitAdapter:
    """Verify adapter auto-selection from FAL_IMAGE_MODEL."""

    def test_default_is_seedream(self, monkeypatch):
        monkeypatch.setenv('FAL_KEY', 'test-key')
        monkeypatch.delenv('FAL_IMAGE_MODEL', raising=False)
        adapter = _init_adapter()
        assert isinstance(adapter, SeedreamAdapter)

    def test_explicit_seedream(self, monkeypatch):
        monkeypatch.setenv('FAL_KEY', 'test-key')
        monkeypatch.setenv('FAL_IMAGE_MODEL', 'fal-ai/bytedance/seedream/v4/text-to-image')
        adapter = _init_adapter()
        assert isinstance(adapter, SeedreamAdapter)

    def test_explicit_other_model(self, monkeypatch):
        monkeypatch.setenv('FAL_KEY', 'test-key')
        monkeypatch.setenv('FAL_IMAGE_MODEL', 'fal-ai/nano-banana-pro')
        adapter = _init_adapter()
        assert isinstance(adapter, GenericFalAdapter)

    def test_missing_fal_key_raises(self, monkeypatch):
        monkeypatch.delenv('FAL_KEY', raising=False)
        with pytest.raises(RuntimeError, match='FAL_KEY not set'):
            _init_adapter()


# ─── SeedreamAdapter.TIMEOUT_SECONDS ─────────────────────────────────────


class TestSeedreamTimeout:
    """Verify timeout constant is present and sensible."""

    def test_timeout_is_set(self):
        assert hasattr(SeedreamAdapter, 'TIMEOUT_SECONDS')
        assert SeedreamAdapter.TIMEOUT_SECONDS > 0

    def test_timeout_is_finite(self):
        assert SeedreamAdapter.TIMEOUT_SECONDS <= 300  # max 5 min
