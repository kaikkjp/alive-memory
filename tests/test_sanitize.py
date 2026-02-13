"""Tests for pipeline/sanitize.py — input sanitization."""

from pipeline.sanitize import sanitize_input


class TestSanitizeInput:
    """sanitize_input strips ANSI escapes and control chars from visitor input."""

    def test_plain_text_passes_through(self):
        assert sanitize_input("hello") == "hello"

    def test_empty_string(self):
        assert sanitize_input("") == ""

    def test_none_returns_none(self):
        assert sanitize_input(None) is None

    def test_strips_ansi_color_codes(self):
        assert sanitize_input("\x1b[31mred text\x1b[0m") == "red text"

    def test_strips_csi_cursor_movement(self):
        # CSI H = cursor home, CSI 2J = clear screen
        assert sanitize_input("\x1b[H\x1b[2Jhello") == "hello"

    def test_strips_c1_control_byte(self):
        # 0x9b is the C1 CSI single-byte form
        assert sanitize_input("\x9b31mhello") == "hello"

    def test_strips_c1_range_bytes(self):
        # Characters 0x80-0x9f should be stripped
        text = "hello\x80\x85\x8f\x9fworld"
        result = sanitize_input(text)
        assert result == "helloworld"

    def test_strips_osc_sequences(self):
        # OSC: ESC ] ... BEL
        assert sanitize_input("\x1b]0;new title\x07hello") == "hello"

    def test_strips_null_bytes(self):
        assert sanitize_input("hel\x00lo") == "hello"

    def test_preserves_newlines(self):
        assert sanitize_input("line1\nline2") == "line1\nline2"

    def test_preserves_tabs(self):
        assert sanitize_input("col1\tcol2") == "col1\tcol2"

    def test_strips_whitespace(self):
        assert sanitize_input("  hello  ") == "hello"

    def test_unicode_text_preserved(self):
        assert sanitize_input("こんにちは") == "こんにちは"

    def test_mixed_unicode_and_ansi(self):
        assert sanitize_input("\x1b[1m雨の音\x1b[0m") == "雨の音"

    def test_csi_with_private_params(self):
        # ESC[?25l = hide cursor (private param '?')
        assert sanitize_input("\x1b[?25lhello\x1b[?25h") == "hello"
