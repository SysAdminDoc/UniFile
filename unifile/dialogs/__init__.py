"""UniFile dialogs subpackage — re-exports all dialog classes for backward compatibility."""

from unifile.dialogs.settings import (
    OllamaSettingsDialog, PhotoSettingsDialog, FaceManagerDialog, ModelManagerDialog
)
from unifile.dialogs.editors import (
    CustomCategoriesDialog, DestTreeDialog, PCCategoryEditorDialog,
    TemplateBuilderWidget, _FileBrowserDialog, RuleEditorDialog
)
from unifile.dialogs.cleanup import (
    _CleanupScanWorker, CleanupToolsDialog, CleanupPanel
)
from unifile.dialogs.duplicates import (
    _DupScanWorker, DuplicateFinderDialog, DuplicatePanel, DuplicateCompareDialog
)
from unifile.dialogs.tools import (
    BeforeAfterDialog, EventGroupDialog, ScheduleDialog,
    UndoTimelineDialog, UndoBatchDialog, PluginManagerDialog,
    RelationshipGraphWidget, WatchHistoryDialog
)
from unifile.dialogs.theme import (
    ThemePickerDialog, ProtectedPathsDialog
)

__all__ = [
    'OllamaSettingsDialog', 'PhotoSettingsDialog', 'FaceManagerDialog', 'ModelManagerDialog',
    'CustomCategoriesDialog', 'DestTreeDialog', 'PCCategoryEditorDialog',
    'TemplateBuilderWidget', '_FileBrowserDialog', 'RuleEditorDialog',
    '_CleanupScanWorker', 'CleanupToolsDialog', 'CleanupPanel',
    '_DupScanWorker', 'DuplicateFinderDialog', 'DuplicatePanel', 'DuplicateCompareDialog',
    'BeforeAfterDialog', 'EventGroupDialog', 'ScheduleDialog',
    'UndoTimelineDialog', 'UndoBatchDialog', 'PluginManagerDialog',
    'RelationshipGraphWidget', 'WatchHistoryDialog',
    'ThemePickerDialog', 'ProtectedPathsDialog',
]
