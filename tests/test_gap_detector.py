"""Tests for pipeline/gap_detector.py — Goldilocks curve gap detection.

TASK-042: Verifies that the gap detector correctly scores text fragments
on the Goldilocks curve, classifies gap types, and computes curiosity deltas.
"""

import math
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.pipeline import TextFragment, GapScore
from pipeline.gap_detector import (
    EmbeddingEntry,
    EmbeddingIndex,
    _cosine_similarity,
    _goldilocks_curve,
    _classify_gap,
    detect_gaps,
    format_gap_annotation,
    deserialize_embedding,
    FOREIGN_THRESHOLD,
    KNOWN_THRESHOLD,
    MAX_CURIOSITY_DELTA,
)


def _make_fragment(text='Test text', source_type='notification',
                   source_id='frag-1', content_id=None):
    return TextFragment(
        text=text, source_type=source_type,
        source_id=source_id, content_id=content_id,
    )


def _make_embedding(dim=8, base=0.0):
    """Create a simple normalized embedding vector."""
    vec = [base + i * 0.1 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec


def _make_index(entries=None, dim=8):
    """Create an EmbeddingIndex with given entries."""
    return EmbeddingIndex(entries=entries or [], dimension=dim)


class TestCosinesimilarity:
    """Unit tests for cosine similarity."""

    def test_identical_vectors(self):
        vec = [1.0, 0.0, 0.0, 0.0]
        assert abs(_cosine_similarity(vec, vec) - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(a, b)) < 0.001

    def test_empty_vectors(self):
        assert _cosine_similarity([], []) == 0.0

    def test_mismatched_dimensions(self):
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


class TestGoldilockssCurve:
    """Unit tests for the Goldilocks curve."""

    def test_peak_at_half(self):
        """Peak curiosity at relevance=0.5."""
        assert abs(_goldilocks_curve(0.5) - 1.0) < 0.001

    def test_zero_at_extremes(self):
        """No curiosity at relevance=0.0 and 1.0."""
        assert abs(_goldilocks_curve(0.0)) < 0.001
        assert abs(_goldilocks_curve(1.0)) < 0.001

    def test_symmetric(self):
        """Curve is symmetric around 0.5."""
        assert abs(_goldilocks_curve(0.3) - _goldilocks_curve(0.7)) < 0.001

    def test_monotonic_to_peak(self):
        """Curve increases from 0 to 0.5."""
        assert _goldilocks_curve(0.1) < _goldilocks_curve(0.3)
        assert _goldilocks_curve(0.3) < _goldilocks_curve(0.5)

    def test_monotonic_from_peak(self):
        """Curve decreases from 0.5 to 1.0."""
        assert _goldilocks_curve(0.5) > _goldilocks_curve(0.7)
        assert _goldilocks_curve(0.7) > _goldilocks_curve(0.9)


class TestClassifyGap:
    """Unit tests for gap type classification."""

    def test_foreign(self):
        assert _classify_gap(0.0) == 'foreign'
        assert _classify_gap(0.10) == 'foreign'
        assert _classify_gap(0.14) == 'foreign'

    def test_partial(self):
        assert _classify_gap(0.15) == 'partial'
        assert _classify_gap(0.5) == 'partial'
        assert _classify_gap(0.85) == 'partial'

    def test_known(self):
        assert _classify_gap(0.86) == 'known'
        assert _classify_gap(1.0) == 'known'


class TestDetectGaps:
    """Core gap detection tests."""

    def test_foreign_content_no_curiosity(self):
        """Relevance < 0.15 → delta = 0.0, gap_type = foreign."""
        # Create an index entry very different from the fragment
        entry = EmbeddingEntry(
            source_type='conversation',
            source_id='mem-1',
            text_snippet='cats and dogs',
            embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        index = _make_index([entry])

        # Fragment embedding orthogonal to index
        fragment = _make_fragment()
        embeddings = {
            'frag-1': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        }

        results = detect_gaps([fragment], index, embeddings)
        assert len(results) == 1
        assert results[0].gap_type == 'foreign'
        assert results[0].curiosity_delta == 0.0

    def test_known_content_no_curiosity(self):
        """Relevance > 0.85 → delta = 0.0, gap_type = known."""
        vec = _make_embedding(dim=8)
        entry = EmbeddingEntry(
            source_type='conversation',
            source_id='mem-1',
            text_snippet='known topic',
            embedding=list(vec),  # same as fragment
        )
        index = _make_index([entry])

        fragment = _make_fragment()
        embeddings = {'frag-1': list(vec)}

        results = detect_gaps([fragment], index, embeddings)
        assert len(results) == 1
        assert results[0].gap_type == 'known'
        assert results[0].curiosity_delta == 0.0
        assert results[0].relevance > KNOWN_THRESHOLD

    def test_partial_match_generates_curiosity(self):
        """Relevance ~0.5 → max delta (peak of Goldilocks curve)."""
        # Create vectors with ~0.5 cosine similarity
        # cos(60°) = 0.5 — angle between a and b gives cos sim
        a = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        b = [0.5, 0.866, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        entry = EmbeddingEntry(
            source_type='conversation',
            source_id='mem-1',
            text_snippet='partial match topic',
            embedding=a,
        )
        index = _make_index([entry])

        fragment = _make_fragment()
        embeddings = {'frag-1': b}

        results = detect_gaps([fragment], index, embeddings)
        assert len(results) == 1
        assert results[0].gap_type == 'partial'
        assert results[0].curiosity_delta > 0.0
        assert results[0].curiosity_delta <= MAX_CURIOSITY_DELTA

    def test_goldilocks_curve_shape(self):
        """Delta at 0.3 < delta at 0.5 > delta at 0.7."""
        # We test the curve function directly since constructing exact
        # cosine similarity vectors for specific values is complex
        delta_03 = _goldilocks_curve(0.3) * MAX_CURIOSITY_DELTA
        delta_05 = _goldilocks_curve(0.5) * MAX_CURIOSITY_DELTA
        delta_07 = _goldilocks_curve(0.7) * MAX_CURIOSITY_DELTA

        assert delta_03 < delta_05
        assert delta_05 > delta_07
        assert abs(delta_03 - delta_07) < 0.001  # symmetric

    def test_epistemic_when_thread_matches(self):
        """Matching thread → suggested_type = 'epistemic'."""
        # Make a partial match with thread entries
        a = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        b = [0.5, 0.866, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        entry = EmbeddingEntry(
            source_type='thread',
            source_id='thread-1',
            text_snippet='active research question',
            embedding=a,
        )
        index = _make_index([entry])

        fragment = _make_fragment()
        embeddings = {'frag-1': b}

        results = detect_gaps([fragment], index, embeddings)
        assert results[0].gap_type == 'partial'
        assert results[0].suggested_curiosity_type == 'epistemic'
        assert len(results[0].matching_threads) > 0

    def test_diversive_when_no_thread(self):
        """No matching thread → suggested_type = 'diversive'."""
        a = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        b = [0.5, 0.866, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        entry = EmbeddingEntry(
            source_type='conversation',
            source_id='mem-1',
            text_snippet='general memory',
            embedding=a,
        )
        index = _make_index([entry])

        fragment = _make_fragment()
        embeddings = {'frag-1': b}

        results = detect_gaps([fragment], index, embeddings)
        assert results[0].gap_type == 'partial'
        assert results[0].suggested_curiosity_type == 'diversive'

    def test_visitor_speech_through_gap_detector(self):
        """Visitor TextFragment produces valid GapScore."""
        a = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        b = [0.5, 0.866, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        entry = EmbeddingEntry(
            source_type='conversation',
            source_id='mem-1',
            text_snippet='something familiar',
            embedding=a,
        )
        index = _make_index([entry])

        fragment = TextFragment(
            text='Have you heard about those vintage prism cards?',
            source_type='visitor_speech',
            source_id='visitor-123',
        )
        embeddings = {'visitor-123': b}

        results = detect_gaps([fragment], index, embeddings)
        assert len(results) == 1
        assert results[0].fragment.source_type == 'visitor_speech'
        assert isinstance(results[0].relevance, float)
        assert results[0].gap_type in ('foreign', 'partial', 'known')

    def test_embedding_index_performance(self):
        """1000 memories, gap detection completes in < 50ms."""
        dim = 8  # use small dim for test speed
        entries = []
        for i in range(1000):
            vec = _make_embedding(dim=dim, base=i * 0.001)
            entries.append(EmbeddingEntry(
                source_type='conversation',
                source_id=f'mem-{i}',
                text_snippet=f'memory {i}',
                embedding=vec,
            ))
        index = _make_index(entries, dim=dim)

        fragment = _make_fragment()
        embeddings = {'frag-1': _make_embedding(dim=dim, base=0.5)}

        start = time.time()
        results = detect_gaps([fragment], index, embeddings)
        elapsed_ms = (time.time() - start) * 1000

        assert len(results) == 1
        assert elapsed_ms < 500  # generous for CI; real target is <50ms

    def test_no_embedding_scores_foreign(self):
        """Fragment without embedding is scored as foreign."""
        entry = EmbeddingEntry(
            source_type='conversation',
            source_id='mem-1',
            text_snippet='something',
            embedding=_make_embedding(dim=8),
        )
        index = _make_index([entry])

        fragment = _make_fragment(source_id='no-embed')
        # No embedding for this fragment
        results = detect_gaps([fragment], index, {})
        assert results[0].gap_type == 'foreign'
        assert results[0].curiosity_delta == 0.0

    def test_empty_index_scores_foreign(self):
        """Empty index means everything is foreign."""
        index = _make_index([])
        fragment = _make_fragment()
        embeddings = {'frag-1': _make_embedding(dim=8)}

        results = detect_gaps([fragment], index, embeddings)
        assert results[0].gap_type == 'foreign'


class TestFormatGapAnnotation:
    """Tests for format_gap_annotation."""

    def test_foreign_returns_empty(self):
        gs = GapScore(fragment=_make_fragment(), gap_type='foreign')
        assert format_gap_annotation(gs) == ''

    def test_known_returns_empty(self):
        gs = GapScore(fragment=_make_fragment(), gap_type='known')
        assert format_gap_annotation(gs) == ''

    def test_partial_with_threads(self):
        gs = GapScore(
            fragment=_make_fragment(),
            gap_type='partial',
            relevance=0.5,
            matching_threads=['thread: active research'],
        )
        text = format_gap_annotation(gs)
        assert 'connects to something you\'re thinking about' in text

    def test_partial_with_memories(self):
        gs = GapScore(
            fragment=_make_fragment(),
            gap_type='partial',
            relevance=0.5,
            matching_memories=['conversation: vintage cards discussion'],
        )
        text = format_gap_annotation(gs)
        assert 'connects to something you know about' in text

    def test_partial_no_matches_high_relevance(self):
        gs = GapScore(
            fragment=_make_fragment(),
            gap_type='partial',
            relevance=0.5,
        )
        text = format_gap_annotation(gs)
        assert text  # should produce some annotation


class TestDeserializeEmbedding:
    """Tests for embedding deserialization."""

    def test_round_trip(self):
        import struct
        original = [0.1, 0.2, 0.3, 0.4]
        blob = struct.pack(f'{len(original)}f', *original)
        result = deserialize_embedding(blob, dimension=4)
        assert len(result) == 4
        for o, r in zip(original, result):
            assert abs(o - r) < 0.0001

    def test_empty_blob(self):
        assert deserialize_embedding(b'') == []
        assert deserialize_embedding(None) == []

    def test_wrong_dimension(self):
        import struct
        blob = struct.pack('4f', 0.1, 0.2, 0.3, 0.4)
        assert deserialize_embedding(blob, dimension=8) == []
