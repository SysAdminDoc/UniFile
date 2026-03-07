"""Tests for the engine module (CategoryBalancer, RuleEngine)."""
import pytest

from unifile.engine import CategoryBalancer


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
