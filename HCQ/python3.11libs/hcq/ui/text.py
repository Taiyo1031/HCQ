"""Centralized English UI text.

Keeping user-facing strings here makes a future localization pass mechanical.
"""

APP_TITLE = "HCQ — Houdini Cook Queue"
APP_SHORT_TITLE = "HCQ"

TAB_MONITOR = "Monitor"
TAB_QUEUES = "Queues"
TAB_RUN = "Run"
TAB_HISTORY = "History"
TAB_SETTINGS = "Settings"

MONITOR_ON = "Monitor: On"
MONITOR_OFF = "Monitor: Off"
QUEUE_IDLE = "Queue: Idle"
HOUDINI_REQUIREMENT = "Houdini 21.0+ / Windows"
NO_DATA = "No items to display."
NO_SELECTION = "Nothing is selected."
NOT_AVAILABLE = "Not available"
READY = "Ready"
UNKNOWN = "Unknown"

ADD_SELECTED_NODES = "Add Selected Nodes"
ADD_BY_PATH = "Add by Path"
ADD_QUEUE = "Add Queue"
ADD_TO_RUN_LIST = "Add to Run List"
REMOVE = "Remove"
ENABLE = "Enable"
DISABLE = "Disable"
GO_TO_NODE = "Go to Node"
LOCATE_REPLACEMENT = "Locate Replacement"
EDIT_PATH = "Edit Path"
REFRESH = "Refresh"
USAGE = "Usage"
UPDATE = "Update"
USAGE_TOOLTIP = "Open the HCQ usage guide on GitHub"
UPDATE_TOOLTIP = "Check GitHub Releases for an HCQ update"
CHECKING_FOR_UPDATES = "Checking…"

NEW_QUEUE = "New Queue"
EDIT = "Edit"
DUPLICATE = "Duplicate"
DELETE = "Delete"
IMPORT_JSON = "Import JSON"
EXPORT_JSON = "Export JSON"
EXPORT_RUN_LIST = "Export Run List JSON"
SEARCH = "Search"
GROUP = "Group"
ALL_GROUPS = "All Groups"
FAVORITES = "Favorites"

MOVE_UP = "Move Up"
MOVE_DOWN = "Move Down"
SAVE = "Save"
SAVE_AS = "Save As"
DISCARD = "Discard Changes"
IMPORT_JOBS = "Import Jobs"
JOB_SETTINGS = "Job Settings"

CPU_JOB_ITEMS = (
    ("Use Queue Setting", "inherit"),
    ("Use Current Houdini Setting", "current"),
    ("Use All Logical Threads", "all"),
    ("Set Maximum Logical Threads", "threads"),
    ("Leave Logical Threads Free", "reserve"),
    ("Single Logical Thread", "single"),
)
CPU_QUEUE_ITEMS = tuple(item for item in CPU_JOB_ITEMS if item[1] != "inherit")
CPU_LIMIT_NOTE = (
    "Thread limits are upper bounds. CPU usage can vary, and some nodes may "
    "not fully honor the limit."
)

PREFLIGHT_CHECK = "Preflight Check"
RUN_QUEUE = "Run Queue"
DURING_RUN = "During Run:"
PAUSE_AFTER_CURRENT = "Pause After Current Job"
RESUME = "Resume"
CANCEL_CURRENT = "Cancel Current Cook"
CLEAR_RUN_LIST = "Clear Run List"
TEMPORARY_OVERRIDES = "Edit Temporary Overrides"

RUN_AGAIN = "Run Again"
RUN_FAILED = "Run Failed Jobs"
RUN_FROM_FAILED = "Run from Failed Job"
RESTORE_RUN_LIST = "Restore to Run List"
EXPORT_RESULT = "Export Result JSON"

APPLY = "Apply"
CANCEL = "Cancel"
CLOSE = "Close"
BROWSE = "Browse…"
RETRY = "Retry"
SKIP = "Skip"
STOP = "Stop"

QUEUE_EDITOR_TITLE = "Queue Editor"
IMPORT_PREVIEW_TITLE = "Import Preview"
PATH_REMAP_TITLE = "Path Remap"
RECOVERY_TITLE = "Interrupted Session Recovery"
ERROR_DECISION_TITLE = "Job Failed"
RUN_CONFIRM_TITLE = "Run Queue"
PREFLIGHT_TITLE = "Preflight Check"

INTERRUPTED_FOUND = "An interrupted HCQ session was found."
FOREGROUND_WARNING = (
    "Houdini may be unavailable while foreground jobs are running."
)
