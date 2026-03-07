"""Tests for .unifile_ignore pattern matching."""
import pytest

from unifile.ignore import IgnoreFilter


class TestIgnoreFilter:

    def test_empty_filter_ignores_nothing(self):
        filt = IgnoreFilter()
        assert not filt.has_rules
        assert not filt.is_ignored("anything.txt", False)
        assert not filt.is_ignored("somedir", True)

    def test_load_from_directory(self, tmp_dir, ignore_file):
        filt = IgnoreFilter.from_directory(str(tmp_dir))
        assert filt.has_rules
        assert len(filt.patterns) > 0

    def test_extension_pattern(self):
        filt = IgnoreFilter()
        filt._add_pattern("*.tmp")
        assert filt.is_ignored("file.tmp", False)
        assert not filt.is_ignored("file.txt", False)

    def test_directory_pattern(self):
        filt = IgnoreFilter()
        filt._add_pattern("build/")
        assert filt.is_ignored("build", True)
        # "build/" pattern matches name "build" regardless — not a file named "build.txt"
        assert not filt.is_ignored("build.txt", False)

    def test_negation_pattern(self):
        filt = IgnoreFilter()
        filt._add_pattern("*.log")
        filt._add_pattern("!important.log")
        assert filt.is_ignored("debug.log", False)
        assert not filt.is_ignored("important.log", False)

    def test_comment_and_blank_lines(self):
        filt = IgnoreFilter()
        filt._add_pattern("# this is a comment")
        filt._add_pattern("")
        filt._add_pattern("  ")
        assert not filt.has_rules

    def test_double_star_pattern(self):
        filt = IgnoreFilter()
        filt._add_pattern("**/node_modules")
        assert filt.is_ignored("node_modules", True)

    def test_combined_patterns(self, tmp_dir, ignore_file):
        filt = IgnoreFilter.from_directory(str(tmp_dir))
        # build/ is ignored
        assert filt.is_ignored("build", True)
        # *.o is ignored
        assert filt.is_ignored("output.o", False)
        # node_modules/ is ignored
        assert filt.is_ignored("node_modules", True)
        # Regular files not ignored
        assert not filt.is_ignored("photo.jpg", False)
        assert not filt.is_ignored("report.pdf", False)
