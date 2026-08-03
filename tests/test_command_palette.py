"""Command palette search behavior that does not depend on mouse input."""

from PyQt6.QtWidgets import QApplication

from unifile.dialogs.command_palette import CommandPalette, _Command


def test_command_palette_limits_file_results_to_five():
    app = QApplication.instance() or QApplication([])
    commands = [
        _Command("File", f"invoice-{index}.pdf", "Documents", lambda: None)
        for index in range(8)
    ]
    palette = CommandPalette(commands=commands)
    palette._filter("invoice")

    file_items = []
    for index in range(palette.lst.count()):
        item = palette.lst.item(index)
        command = item.data(256) if item else None  # Qt.UserRole
        if command and command.section == "File":
            file_items.append(command)
    assert len(file_items) == 5
    palette.close()
    palette.deleteLater()
    app.processEvents()
