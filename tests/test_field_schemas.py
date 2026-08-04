"""Per-library custom field schema and typed value coverage."""

from __future__ import annotations

import sys

import pytest

from unifile.tagging.library import TagLibrary
from unifile.tagging.models import BooleanField, DatetimeField, TextField


def _open_library(root):
    root.mkdir()
    library = TagLibrary(str(root))
    assert library.open()
    return library


def test_custom_field_definitions_are_scoped_to_each_library(tmp_path):
    first = _open_library(tmp_path / "first")
    second = _open_library(tmp_path / "second")
    try:
        first_schema = first.add_field_schema(
            "Status", "enum", {"options": ["Backlog", "Done"]})
        second_schema = second.add_field_schema(
            "Status", "enum", {"options": ["Draft", "Published"]})
        assert first_schema and second_schema
        assert first_schema["key"] == second_schema["key"] == "status"
        assert first.get_field_schema("status")["options"] == ["Backlog", "Done"]
        assert second.get_field_schema("status")["options"] == ["Draft", "Published"]
    finally:
        first.close()
        second.close()


def test_validation_canonicalizes_currency_date_enum_and_boolean(tmp_path):
    library = _open_library(tmp_path / "library")
    try:
        assert library.add_field_schema(
            "Budget", "currency", {"min": "0", "max": "1000"})
        assert library.add_field_schema(
            "Status", "status", {"options": "Backlog, Active, Done"})
        assert library.add_field_schema("Deadline", "date")
        assert library.add_field_schema("Reviewed", "boolean")

        assert library.validate_field_value("budget", "$1,234")[1]
        assert library.validate_field_value("budget", "$12.5") == ("12.50", None)
        assert library.validate_field_value("status", "done") == ("Done", None)
        assert library.validate_field_value("deadline", "2026-08-03T12:30:00Z") == (
            "2026-08-03", None)
        assert library.validate_field_value("reviewed", "yes") == ("true", None)
        assert library.validate_field_value("reviewed", "maybe")[1]
    finally:
        library.close()


def test_typed_entry_fields_round_trip_search_and_clear(tmp_path):
    library = _open_library(tmp_path / "library")
    file_path = tmp_path / "library" / "invoice.txt"
    file_path.write_text("invoice", encoding="utf-8")
    try:
        assert library.add_field_schema("Budget", "currency")
        assert library.add_field_schema("Status", "enum", {"options": ["Open", "Paid"]})
        assert library.add_field_schema("Due", "date")
        assert library.add_field_schema("Reviewed", "boolean")
        entry = library.add_entry(str(file_path))
        assert entry is not None

        assert library.set_entry_field(entry.id, "budget", "€1,234.5")
        assert library.set_entry_field(entry.id, "status", "paid")
        assert library.set_entry_field(entry.id, "due", "2026-09-01")
        assert library.set_entry_field(entry.id, "reviewed", True)
        assert library.get_entry_fields(entry.id) == {
            "budget": "1234.50",
            "status": "Paid",
            "due": "2026-09-01",
            "reviewed": "true",
        }
        assert library.search_entries("field:status=paid")[0].id == entry.id
        assert library.search_entries("field:reviewed=true")[0].id == entry.id

        assert library.set_entry_field(entry.id, "status", "unknown") is False
        assert library.get_entry_fields(entry.id)["status"] == "Paid"
        assert library.clear_entry_field(entry.id, "reviewed")
        assert "reviewed" not in library.get_entry_fields(entry.id)
        assert not library._session.query(BooleanField).filter_by(entry_id=entry.id).count()
        assert library._session.query(TextField).filter_by(
            entry_id=entry.id, type_key="budget").count() == 1
        assert library._session.query(DatetimeField).filter_by(
            entry_id=entry.id, type_key="due").count() == 1
    finally:
        library.close()


@pytest.mark.skipif(
    pytest.importorskip("PyQt6", reason="PyQt6 not installed") is None,
    reason="PyQt6 not installed",
)
def test_field_dialogs_construct_for_an_open_library(tmp_path):
    from PyQt6.QtWidgets import QApplication

    from unifile.dialogs.field_schemas import EntryFieldsDialog, FieldSchemaDialog

    app = QApplication.instance() or QApplication([sys.argv[0], "-platform", "offscreen"])
    library = _open_library(tmp_path / "library")
    file_path = tmp_path / "library" / "note.txt"
    file_path.write_text("note", encoding="utf-8")
    try:
        library.add_field_schema("Status", "enum", {"options": ["Open", "Done"]})
        entry = library.add_entry(str(file_path))
        schema_dialog = FieldSchemaDialog(library)
        fields_dialog = EntryFieldsDialog(library, entry.id)
        assert schema_dialog.btn_add.isEnabled()
        assert fields_dialog.windowTitle() == "Edit Entry Fields"
        fields_dialog.close()
        schema_dialog.close()
        app.processEvents()
    finally:
        library.close()
