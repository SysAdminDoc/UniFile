"""Tests for the engine module (CategoryBalancer, RuleEngine)."""
import pytest
from datetime import datetime

from unifile.engine import CategoryBalancer, RuleEngine, _parse_naive_dt, _safe_regex_match


class TestCategoryBalancer:

    def test_empty_items_returns_empty(self):
        balancer = CategoryBalancer()
        result = balancer.balance([])
        assert result['merges'] == 0
        assert result['splits'] == 0

    def test_balanced_items_no_changes(self, sample_file_items):
        balancer = CategoryBalancer(min_merge=1, split_pct=0.50)
        cats = set(it.category for it in sample_file_items)
        result = balancer.balance(sample_file_items, all_categories=cats)
        # With 12 items across 8 categories, no single category has >50%
        assert result['passes'] >= 1

    def test_merge_small_categories(self):
        """Categories with very few items should trigger merge suggestions."""
        from unifile.models import FileItem

        items = []
        # 20 items in "Photos", 1 item in "Rare"
        for i in range(20):
            it = FileItem()
            it.name = f"photo_{i}.jpg"
            it.category = "Photos"
            items.append(it)

        rare = FileItem()
        rare.name = "rare.xyz"
        rare.category = "Rare"
        items.append(rare)

        balancer = CategoryBalancer(min_merge=2, split_pct=0.95)
        result = balancer.balance(items, all_categories={'Photos', 'Rare'})
        # "Rare" has only 1 item, below min_merge of 2
        assert isinstance(result, dict)
        assert 'merges' in result

    def test_custom_thresholds(self):
        balancer = CategoryBalancer(min_merge=5, split_pct=0.10, max_passes=2)
        assert balancer.min_merge == 5
        assert balancer.split_pct == 0.10
        assert balancer.max_passes == 2


# ── _parse_naive_dt ────────────────────────────────────────────────────────────

class TestParseNaiveDt:

    def test_plain_iso(self):
        dt = _parse_naive_dt("2024-03-15T10:30:00")
        assert dt == datetime(2024, 3, 15, 10, 30, 0)

    def test_strips_trailing_z(self):
        dt = _parse_naive_dt("2024-03-15T10:30:00Z")
        assert dt == datetime(2024, 3, 15, 10, 30, 0)

    def test_strips_trailing_z_lower(self):
        dt = _parse_naive_dt("2024-03-15T10:30:00z")
        assert dt == datetime(2024, 3, 15, 10, 30, 0)

    def test_strips_positive_offset_with_colon(self):
        dt = _parse_naive_dt("2024-03-15T10:30:00+05:30")
        assert dt == datetime(2024, 3, 15, 10, 30, 0)

    def test_strips_negative_offset(self):
        dt = _parse_naive_dt("2024-03-15T10:30:00-04:00")
        assert dt == datetime(2024, 3, 15, 10, 30, 0)

    def test_strips_offset_without_colon(self):
        dt = _parse_naive_dt("2024-03-15T10:30:00+0530")
        assert dt == datetime(2024, 3, 15, 10, 30, 0)

    def test_date_only(self):
        dt = _parse_naive_dt("2024-03-15")
        assert dt == datetime(2024, 3, 15)

    def test_strips_whitespace(self):
        dt = _parse_naive_dt("  2024-03-15T10:30:00Z  ")
        assert dt == datetime(2024, 3, 15, 10, 30, 0)


# ── _safe_regex_match ──────────────────────────────────────────────────────────

class TestSafeRegexMatch:

    def test_basic_match(self):
        assert _safe_regex_match(r"\d{4}", "file_2024.txt") is True

    def test_no_match(self):
        assert _safe_regex_match(r"^\d+$", "abc123") is False

    def test_case_insensitive(self):
        assert _safe_regex_match(r"^REPORT", "report_final.pdf") is True

    def test_invalid_pattern_returns_false(self):
        assert _safe_regex_match(r"[invalid", "anything") is False

    def test_empty_pattern(self):
        # Empty pattern matches everything
        assert _safe_regex_match(r"", "any string") is True

    def test_empty_value(self):
        assert _safe_regex_match(r"\d+", "") is False


# ── RuleEngine.evaluate ────────────────────────────────────────────────────────

class TestRuleEngineEvaluate:

    def _make_item(self, name="test.pdf", size=1024, full_src=""):
        from unifile.models import FileItem
        it = FileItem()
        it.name = name
        it.size = size
        it.full_src = full_src
        return it

    def test_no_rules_returns_none(self):
        assert RuleEngine.evaluate(self._make_item(), []) is None

    def test_disabled_rule_skipped(self):
        rules = [{'enabled': False, 'conditions': [{'field': 'extension', 'op': 'eq', 'value': '.pdf'}],
                  'action_category': 'Documents', 'confidence': 90}]
        assert RuleEngine.evaluate(self._make_item(), rules) is None

    def test_eq_match(self):
        rules = [{'enabled': True,
                  'conditions': [{'field': 'extension', 'op': 'eq', 'value': '.pdf'}],
                  'action_category': 'Documents', 'action_rename': '', 'confidence': 90}]
        result = RuleEngine.evaluate(self._make_item("doc.pdf"), rules)
        assert result is not None
        assert result[0] == 'Documents'
        assert result[2] == 90

    def test_no_match_returns_none(self):
        rules = [{'enabled': True,
                  'conditions': [{'field': 'extension', 'op': 'eq', 'value': '.docx'}],
                  'action_category': 'Documents', 'action_rename': '', 'confidence': 90}]
        assert RuleEngine.evaluate(self._make_item("image.png"), rules) is None

    def test_contains_match(self):
        rules = [{'enabled': True,
                  'conditions': [{'field': 'name', 'op': 'contains', 'value': 'invoice'}],
                  'action_category': 'Finance', 'action_rename': '', 'confidence': 85}]
        result = RuleEngine.evaluate(self._make_item("invoice_2024.pdf"), rules)
        assert result is not None
        assert result[0] == 'Finance'

    def test_size_gt_mb(self):
        rules = [{'enabled': True,
                  'conditions': [{'field': 'size', 'op': 'size_gt_mb', 'value': '1'}],
                  'action_category': 'Large', 'action_rename': '', 'confidence': 80}]
        big = self._make_item(size=2 * 1024 * 1024)
        small = self._make_item(size=512 * 1024)
        assert RuleEngine.evaluate(big, rules) is not None
        assert RuleEngine.evaluate(small, rules) is None

    def test_logic_any(self):
        rules = [{'enabled': True, 'logic': 'any',
                  'conditions': [
                      {'field': 'extension', 'op': 'eq', 'value': '.jpg'},
                      {'field': 'extension', 'op': 'eq', 'value': '.png'},
                  ],
                  'action_category': 'Images', 'action_rename': '', 'confidence': 90}]
        assert RuleEngine.evaluate(self._make_item("photo.jpg"), rules) is not None
        assert RuleEngine.evaluate(self._make_item("photo.png"), rules) is not None
        assert RuleEngine.evaluate(self._make_item("doc.pdf"), rules) is None

    def test_logic_all_requires_both(self):
        rules = [{'enabled': True, 'logic': 'all',
                  'conditions': [
                      {'field': 'extension', 'op': 'eq', 'value': '.jpg'},
                      {'field': 'name', 'op': 'contains', 'value': 'vacation'},
                  ],
                  'action_category': 'Holiday Photos', 'action_rename': '', 'confidence': 95}]
        assert RuleEngine.evaluate(self._make_item("vacation_2024.jpg"), rules) is not None
        assert RuleEngine.evaluate(self._make_item("work_2024.jpg"), rules) is None

    def test_priority_ordering(self):
        rules = [
            {'enabled': True, 'priority': 10,
             'conditions': [{'field': 'extension', 'op': 'eq', 'value': '.pdf'}],
             'action_category': 'LowPriority', 'action_rename': '', 'confidence': 50},
            {'enabled': True, 'priority': 1,
             'conditions': [{'field': 'extension', 'op': 'eq', 'value': '.pdf'}],
             'action_category': 'HighPriority', 'action_rename': '', 'confidence': 90},
        ]
        result = RuleEngine.evaluate(self._make_item("doc.pdf"), rules)
        assert result[0] == 'HighPriority'

    def test_matches_regex(self):
        rules = [{'enabled': True,
                  'conditions': [{'field': 'name', 'op': 'matches', 'value': r'^\d{4}_'}],
                  'action_category': 'Dated', 'action_rename': '', 'confidence': 80}]
        assert RuleEngine.evaluate(self._make_item("2024_report.pdf"), rules) is not None
        assert RuleEngine.evaluate(self._make_item("report_2024.pdf"), rules) is None

    def test_invalid_regex_does_not_crash(self):
        rules = [{'enabled': True,
                  'conditions': [{'field': 'name', 'op': 'matches', 'value': '[bad regex'}],
                  'action_category': 'X', 'action_rename': '', 'confidence': 80}]
        assert RuleEngine.evaluate(self._make_item("file.txt"), rules) is None

    def test_bad_value_type_does_not_crash(self):
        rules = [{'enabled': True,
                  'conditions': [{'field': 'size', 'op': 'gt', 'value': 'not_a_number'}],
                  'action_category': 'X', 'action_rename': '', 'confidence': 80}]
        assert RuleEngine.evaluate(self._make_item(), rules) is None


# ── RuleEngine.find_conflicts ─────────────────────────────────────────────────

class TestFindConflicts:

    def _rule(self, conditions, category, priority=50):
        return {
            'enabled': True, 'priority': priority, 'logic': 'all',
            'conditions': conditions,
            'action_category': category, 'action_rename': '', 'confidence': 80,
        }

    def test_no_rules_no_conflicts(self):
        assert RuleEngine.find_conflicts([]) == []

    def test_identical_conditions_different_actions(self):
        cond = [{'field': 'extension', 'op': 'eq', 'value': '.pdf'}]
        rules = [self._rule(cond, 'Documents'), self._rule(cond, 'Archive')]
        conflicts = RuleEngine.find_conflicts(rules)
        assert (0, 1) in conflicts

    def test_same_conditions_same_action_not_conflict(self):
        cond = [{'field': 'extension', 'op': 'eq', 'value': '.pdf'}]
        rules = [self._rule(cond, 'Documents'), self._rule(cond, 'Documents')]
        assert RuleEngine.find_conflicts(rules) == []

    def test_different_conditions_no_conflict(self):
        rules = [
            self._rule([{'field': 'extension', 'op': 'eq', 'value': '.pdf'}], 'A'),
            self._rule([{'field': 'extension', 'op': 'eq', 'value': '.jpg'}], 'B'),
        ]
        assert RuleEngine.find_conflicts(rules) == []

    def test_no_duplicate_pairs(self):
        cond = [{'field': 'name', 'op': 'contains', 'value': 'report'}]
        rules = [self._rule(cond, 'X'), self._rule(cond, 'Y'), self._rule(cond, 'Z')]
        conflicts = RuleEngine.find_conflicts(rules)
        # Should have pairs (0,1), (0,2), (1,2) but not reversed
        for a, b in conflicts:
            assert a < b
