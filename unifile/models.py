"""UniFile — Data model classes for scan items."""
import os

# ── Data structures ────────────────────────────────────────────────────────────
class RenameItem:
    def __init__(self):
        self.selected = True
        self.current_name = ""
        self.new_name = ""
        self.aep_file = ""
        self.file_size = ""
        self.full_current_path = ""
        self.full_new_path = ""
        self.status = "Pending"
        self.tbl_row = -1   # actual QTableWidget row index

class CategorizeItem:
    def __init__(self):
        self.selected = True
        self.folder_name = ""
        self.cleaned_name = ""
        self.category = ""
        self.confidence = 0
        self.full_source_path = ""
        self.full_dest_path = ""
        self.status = "Pending"
        self.method = ""        # classification method: extension, keyword, fuzzy, metadata, context
        self.detail = ""        # human-readable detail of how it was classified
        self.topic = ""         # original topic if context engine overrode it
        self.tbl_row = -1      # actual QTableWidget row index



# ── FileItem data class ────────────────────────────────────────────────────────
class FileItem:
    """Represents a single file or folder to be organized."""
    def __init__(self):
        self.name         = ""       # original filename/foldername
        self.display_name = ""       # name to use at destination (may differ if renamed)
        self.full_src     = ""       # absolute source path
        self.full_dst     = ""       # computed destination path
        self.category     = ""
        self.confidence   = 0
        self.method       = ""
        self.detail       = ""
        self.size         = 0        # bytes (0 for folders)
        self.is_folder    = False
        self.is_duplicate = False
        self.dup_group    = 0        # duplicate group ID (0 = not a dup)
        self.dup_detail   = ""       # human-readable dup info
        self.dup_is_original = False # True = keep this one, False = dup copy
        self.status       = "Pending"
        self.selected     = True
        self.tbl_row      = -1
        self.metadata     = {}       # extracted metadata dict
        self.vision_description = "" # AI vision description of image content
        self.vision_ocr   = ""       # text detected in image by vision model


