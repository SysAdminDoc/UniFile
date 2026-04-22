"""Tests for UniFile data model classes."""
import pytest

from unifile.models import CategorizeItem, FileItem, RenameItem


class TestRenameItem:
    def test_defaults(self):
        item = RenameItem()
        assert item.selected is True
        assert item.status == "Pending"
        assert item.current_name == ""
        assert item.new_name == ""

    def test_assignment(self):
        item = RenameItem()
        item.current_name = "Folder [2024]"
        item.new_name = "Folder (2024)"
        item.status = "Done"
        assert item.current_name == "Folder [2024]"
        assert item.status == "Done"


class TestCategorizeItem:
    def test_defaults(self):
        item = CategorizeItem()
        assert item.selected is True
        assert item.confidence == 0
        assert item.method == ""

    def test_classification_fields(self):
        item = CategorizeItem()
        item.folder_name = "My Photos 2024"
        item.category = "Photos"
        item.confidence = 85
        item.method = "fuzzy"
        assert item.category == "Photos"
        assert item.confidence == 85


class TestFileItem:
    def test_defaults(self):
        item = FileItem()
        assert item.is_folder is False
        assert item.is_duplicate is False
        assert item.size == 0
        assert item.selected is True

    def test_file_properties(self):
        item = FileItem()
        item.name = "report.pdf"
        item.full_src = "/home/user/Downloads/report.pdf"
        item.category = "Documents"
        item.confidence = 80
        item.size = 1048576
        assert item.name == "report.pdf"
        assert item.size == 1048576

    def test_duplicate_tracking(self):
        item = FileItem()
        item.is_duplicate = True
        item.dup_group = 3
        item.dup_detail = "Same SHA-256 hash"
        assert item.dup_group == 3
