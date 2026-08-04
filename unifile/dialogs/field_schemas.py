"""Dialogs for managing per-library field schemas and editing entry values."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header
from unifile.field_schemas import FieldTypeEnum, schema_summary
from unifile.tagging.library import TagLibrary

_FIELD_TYPE_CHOICES = (
    ("Text Line", FieldTypeEnum.TEXT_LINE),
    ("Text Box", FieldTypeEnum.TEXT_BOX),
    ("Date", FieldTypeEnum.DATETIME),
    ("Currency", FieldTypeEnum.CURRENCY),
    ("Status / Enum", FieldTypeEnum.ENUM),
    ("Checkbox", FieldTypeEnum.BOOLEAN),
)


class FieldSchemaDialog(QDialog):
    """List built-in fields and create/remove custom definitions."""

    def __init__(self, library: TagLibrary, parent=None):
        super().__init__(parent)
        self._library = library
        self.setWindowTitle("Field Schemas")
        self.setMinimumSize(920, 620)
        self.setStyleSheet(get_active_stylesheet())
        theme = get_active_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(build_dialog_header(
            theme,
            "Library",
            "Field Schemas",
            "Define fields that belong only to this library. Built-in fields remain available; "
            "custom rules validate values before they are saved.",
        ))

        self.tbl_schemas = QTableWidget(0, 4)
        self.tbl_schemas.setHorizontalHeaderLabels(["Name", "Type", "Rules", "Key"])
        self.tbl_schemas.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_schemas.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_schemas.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_schemas.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_schemas.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_schemas.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl_schemas.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_schemas.setAccessibleName("Library field schemas")
        self.tbl_schemas.setAccessibleDescription(
            "Built-in and custom fields configured for this tag library")
        self.tbl_schemas.itemSelectionChanged.connect(self._update_remove_state)
        layout.addWidget(self.tbl_schemas, 1)

        add_box = QWidget()
        add_layout = QVBoxLayout(add_box)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.setSpacing(6)
        add_title = QLabel("Add custom field")
        add_title.setStyleSheet(
            f"color: {theme['fg_bright']}; font-size: 13px; font-weight: 700;")
        add_layout.addWidget(add_title)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.addWidget(QLabel("Name"), 0, 0)
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("e.g. Budget")
        self.txt_name.setAccessibleName("Custom field name")
        self.txt_name.setAccessibleDescription("Display name for the new custom field")
        form.addWidget(self.txt_name, 0, 1)
        form.addWidget(QLabel("Type"), 0, 2)
        self.cmb_type = QComboBox()
        self.cmb_type.setAccessibleName("Custom field type")
        self.cmb_type.setAccessibleDescription("Validation and editor type for the new custom field")
        for label, field_type in _FIELD_TYPE_CHOICES:
            self.cmb_type.addItem(label, field_type)
        self.cmb_type.currentIndexChanged.connect(self._update_rule_controls)
        form.addWidget(self.cmb_type, 0, 3)

        self.lbl_options = QLabel("Status options")
        form.addWidget(self.lbl_options, 1, 0)
        self.txt_options = QLineEdit()
        self.txt_options.setPlaceholderText("Backlog, Active, Done")
        self.txt_options.setAccessibleName("Status options")
        self.txt_options.setAccessibleDescription("Comma-separated choices for a status field")
        form.addWidget(self.txt_options, 1, 1, 1, 3)

        self.lbl_min = QLabel("Currency minimum")
        form.addWidget(self.lbl_min, 2, 0)
        self.txt_min = QLineEdit()
        self.txt_min.setPlaceholderText("Optional")
        self.txt_min.setAccessibleName("Currency minimum")
        form.addWidget(self.txt_min, 2, 1)
        self.lbl_max = QLabel("Currency maximum")
        form.addWidget(self.lbl_max, 2, 2)
        self.txt_max = QLineEdit()
        self.txt_max.setPlaceholderText("Optional")
        self.txt_max.setAccessibleName("Currency maximum")
        form.addWidget(self.txt_max, 2, 3)
        add_layout.addLayout(form)

        controls = QGridLayout()
        self.btn_add = QPushButton("Add Field")
        self.btn_add.setProperty("class", "success")
        self.btn_add.setAccessibleName("Add custom field schema")
        self.btn_add.setAccessibleDescription("Save a new field definition for this library")
        self.btn_add.clicked.connect(self._add_schema)
        controls.addWidget(self.btn_add, 0, 0)
        self.btn_remove = QPushButton("Remove Custom Field")
        self.btn_remove.setProperty("class", "danger")
        self.btn_remove.setAccessibleName("Remove selected custom field")
        self.btn_remove.setAccessibleDescription(
            "Delete the selected custom field and its saved entry values")
        self.btn_remove.clicked.connect(self._remove_schema)
        controls.addWidget(self.btn_remove, 0, 1)
        controls.setColumnStretch(2, 1)
        add_layout.addLayout(controls)
        layout.addWidget(add_box)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        layout.addWidget(close_box)
        self._refresh()
        self._update_rule_controls()

    def _refresh(self):
        schemas = self._library.get_field_schemas() if self._library.is_open else []
        self.tbl_schemas.setRowCount(len(schemas))
        for row, schema in enumerate(schemas):
            name = QTableWidgetItem(schema["name"])
            name.setData(Qt.ItemDataRole.UserRole, schema["key"])
            self.tbl_schemas.setItem(row, 0, name)
            self.tbl_schemas.setItem(row, 1, QTableWidgetItem(schema["type"]))
            self.tbl_schemas.setItem(row, 2, QTableWidgetItem(
                schema_summary(schema["type"], schema.get("schema"))))
            key_item = QTableWidgetItem(schema["key"])
            key_item.setToolTip("Built-in field" if schema["is_default"] else "Custom field")
            self.tbl_schemas.setItem(row, 3, key_item)
        self._update_remove_state()
        self.lbl_status.setText(
            f"{len(schemas)} field schema(s). Custom fields are stored in this library only."
            if self._library.is_open else "Open a library before managing field schemas."
        )

    def _selected_schema(self) -> dict[str, Any] | None:
        row = self.tbl_schemas.currentRow()
        if row < 0:
            return None
        item = self.tbl_schemas.item(row, 0)
        if not item:
            return None
        return self._library.get_field_schema(item.data(Qt.ItemDataRole.UserRole))

    def _update_remove_state(self):
        schema = self._selected_schema()
        self.btn_remove.setEnabled(bool(schema and not schema.get("is_default")))

    def _update_rule_controls(self):
        field_type = self.cmb_type.currentData()
        is_enum = field_type is FieldTypeEnum.ENUM
        is_currency = field_type is FieldTypeEnum.CURRENCY
        for widget in (self.lbl_options, self.txt_options):
            widget.setEnabled(is_enum)
        for widget in (self.lbl_min, self.txt_min, self.lbl_max, self.txt_max):
            widget.setEnabled(is_currency)

    def _add_schema(self):
        if not self._library.is_open:
            self.lbl_status.setText("Open a library before adding a field.")
            return
        field_type = self.cmb_type.currentData()
        schema: dict[str, Any] = {}
        if field_type is FieldTypeEnum.ENUM:
            schema["options"] = self.txt_options.text()
        elif field_type is FieldTypeEnum.CURRENCY:
            schema["min"] = self.txt_min.text()
            schema["max"] = self.txt_max.text()
        result = self._library.add_field_schema(self.txt_name.text(), field_type, schema)
        if not result:
            self.lbl_status.setText(self._library.last_field_error or "Field could not be added.")
            return
        self._refresh()
        self.txt_name.clear()
        self.txt_options.clear()
        self.txt_min.clear()
        self.txt_max.clear()
        self.lbl_status.setText(f"Added custom field: {result['name']}")

    def _remove_schema(self):
        schema = self._selected_schema()
        if not schema:
            return
        if not self._library.delete_field_schema(schema["key"]):
            self.lbl_status.setText(self._library.last_field_error or "Field could not be removed.")
            return
        self._refresh()
        self.lbl_status.setText(f"Removed custom field: {schema['name']}")


class EntryFieldsDialog(QDialog):
    """Edit all configured field values for one entry."""

    def __init__(self, library: TagLibrary, entry_id: int, parent=None):
        super().__init__(parent)
        self._library = library
        self._entry_id = entry_id
        self._widgets: list[tuple[dict[str, Any], QWidget]] = []
        self.setWindowTitle("Edit Entry Fields")
        self.setMinimumSize(700, 680)
        self.setStyleSheet(get_active_stylesheet())
        theme = get_active_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        entry = self._library.get_entry(entry_id) if self._library.is_open else None
        entry_name = entry.filename if entry else "selected entry"
        layout.addWidget(build_dialog_header(
            theme,
            "Library",
            "Edit Entry Fields",
            f"Set validated metadata for {entry_name}. Blank values clear the field.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAccessibleName("Entry field editor")
        scroll.setAccessibleDescription("Scrollable form containing all configured entry fields")
        form_widget = QWidget()
        self.form = QFormLayout(form_widget)
        self.form.setContentsMargins(12, 12, 12, 12)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(10)
        scroll.setWidget(form_widget)
        layout.addWidget(scroll, 1)

        fields = self._library.get_entry_fields(entry_id) if entry else {}
        schemas = self._library.get_field_schemas() if self._library.is_open else []
        for schema in schemas:
            label = QLabel(schema["name"])
            label.setToolTip(f"{schema['type']} · {schema['key']}")
            widget = self._build_field_widget(schema, fields.get(schema["key"], ""))
            self._widgets.append((schema, widget))
            self.form.addRow(label, widget)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _set_accessibility(widget: QWidget, name: str, description: str):
        widget.setAccessibleName(name)
        widget.setAccessibleDescription(description)

    def _build_field_widget(self, schema: dict[str, Any], current: str) -> QWidget:
        field_type = schema["type"]
        if field_type == FieldTypeEnum.TEXT_BOX.value:
            widget: QWidget = QPlainTextEdit()
            widget.setMinimumHeight(62)
            widget.setPlainText(current)
        elif field_type == FieldTypeEnum.ENUM.value:
            combo = QComboBox()
            combo.addItem("Not set", "")
            options = list(schema.get("options", []))
            if current and not any(current.casefold() == option.casefold() for option in options):
                options.append(current)
            for option in options:
                combo.addItem(option, option)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            widget = combo
        elif field_type == FieldTypeEnum.BOOLEAN.value:
            combo = QComboBox()
            combo.addItem("Not set", "")
            combo.addItem("True", "true")
            combo.addItem("False", "false")
            index = combo.findData(current.casefold())
            combo.setCurrentIndex(index if index >= 0 else 0)
            widget = combo
        else:
            line = QLineEdit()
            line.setText(current)
            if field_type == FieldTypeEnum.DATETIME.value:
                line.setPlaceholderText("YYYY-MM-DD")
            elif field_type == FieldTypeEnum.CURRENCY.value:
                line.setPlaceholderText("0.00")
            widget = line
        self._set_accessibility(
            widget,
            f"{schema['name']} field",
            f"Value for the {schema['name']} {schema['type']} field",
        )
        return widget

    @staticmethod
    def _raw_value(widget: QWidget) -> Any:
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QLineEdit):
            return widget.text()
        return ""

    def _save(self):
        pending: list[tuple[str, str | None]] = []
        for schema, widget in self._widgets:
            raw = self._raw_value(widget)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                pending.append((schema["key"], None))
                continue
            normalized, error = self._library.validate_field_value(schema["key"], raw)
            if error:
                self.lbl_status.setText(f"{schema['name']}: {error}")
                QMessageBox.warning(self, "Invalid field value", f"{schema['name']}: {error}")
                widget.setFocus()
                return
            pending.append((schema["key"], normalized))

        for key, value in pending:
            success = self._library.clear_entry_field(self._entry_id, key) if value is None else \
                self._library.set_entry_field(self._entry_id, key, value)
            if not success:
                self.lbl_status.setText(
                    self._library.last_field_error or f"Could not save {key}.")
                return
        self.accept()
