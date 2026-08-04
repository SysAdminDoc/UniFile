"""UniFile dialogs subpackage — re-exports all dialog classes for backward compatibility."""

from unifile.dialogs.advanced_settings import (
    AIProviderSettingsDialog,
    DiskSpaceSettingsDialog,
    EmbeddingSettingsDialog,
    LearningStatsDialog,
    SemanticSearchDialog,
    SemanticSearchSettingsDialog,
    WhisperSettingsDialog,
)
from unifile.dialogs.cleanup import CleanupPanel, CleanupToolsDialog, _CleanupScanWorker
from unifile.dialogs.cloud_remotes import CloudRemotesDialog
from unifile.dialogs.collections import CollectionBoardDialog
from unifile.dialogs.duplicates import (
    DuplicateCompareDialog,
    DuplicateFinderDialog,
    DuplicatePanel,
    _DupScanWorker,
)
from unifile.dialogs.editors import (
    CustomCategoriesDialog,
    DestTreeDialog,
    PCCategoryEditorDialog,
    RuleEditorDialog,
    TemplateBuilderWidget,
    _FileBrowserDialog,
)
from unifile.dialogs.field_schemas import EntryFieldsDialog, FieldSchemaDialog
from unifile.dialogs.file_health import FileHealthDialog
from unifile.dialogs.library_roots import LibraryRootsDialog
from unifile.dialogs.metadata_editor import BatchMetadataEditorDialog
from unifile.dialogs.natural_rules import NaturalLanguageRulesDialog
from unifile.dialogs.project_audit import ProjectAuditDialog
from unifile.dialogs.provider_health import ProviderHealthDialog
from unifile.dialogs.settings import (
    ConfidenceTiersDialog,
    FaceManagerDialog,
    ModelManagerDialog,
    OllamaSettingsDialog,
    PhotoSettingsDialog,
)
from unifile.dialogs.settings_hub import SettingsHubDialog
from unifile.dialogs.theme import ProtectedPathsDialog, ThemePickerDialog
from unifile.dialogs.tools import (
    BeforeAfterDialog,
    CsvRulesDialog,
    EventGroupDialog,
    PluginManagerDialog,
    RelationshipGraphWidget,
    ScheduleDialog,
    UndoBatchDialog,
    UndoTimelineDialog,
    WatchHistoryDialog,
)
from unifile.dialogs.voice_control import VoiceControlDialog

__all__ = [
    'OllamaSettingsDialog', 'ConfidenceTiersDialog', 'PhotoSettingsDialog', 'FaceManagerDialog', 'ModelManagerDialog',
    'CustomCategoriesDialog', 'DestTreeDialog', 'PCCategoryEditorDialog',
    'TemplateBuilderWidget', '_FileBrowserDialog', 'RuleEditorDialog',
    '_CleanupScanWorker', 'CleanupToolsDialog', 'CleanupPanel',
    '_DupScanWorker', 'DuplicateFinderDialog', 'DuplicatePanel', 'DuplicateCompareDialog',
    'BeforeAfterDialog', 'EventGroupDialog', 'ScheduleDialog',
    'UndoTimelineDialog', 'UndoBatchDialog', 'PluginManagerDialog',
    'RelationshipGraphWidget', 'WatchHistoryDialog', 'CsvRulesDialog',
    'ThemePickerDialog', 'ProtectedPathsDialog',
    'AIProviderSettingsDialog', 'WhisperSettingsDialog', 'DiskSpaceSettingsDialog',
    'SemanticSearchSettingsDialog', 'SemanticSearchDialog',
    'EmbeddingSettingsDialog', 'LearningStatsDialog',
    'SettingsHubDialog',
    'CloudRemotesDialog',
    'BatchMetadataEditorDialog',
    'NaturalLanguageRulesDialog',
    'ProjectAuditDialog',
    'ProviderHealthDialog',
    'LibraryRootsDialog',
    'CollectionBoardDialog',
    'FileHealthDialog',
    'FieldSchemaDialog',
    'EntryFieldsDialog',
    'VoiceControlDialog',
]
