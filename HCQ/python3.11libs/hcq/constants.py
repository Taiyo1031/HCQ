"""Shared constants and default values for HCQ."""

from __future__ import annotations

VERSION = "1.2.0"
MIN_HOUDINI_VERSION = (21, 0)
PRODUCT_NAME = "HCQ"
REPOSITORY_URL = "https://github.com/Taiyo1031/HCQ"
USAGE_URL = f"{REPOSITORY_URL}#main-workflows"
LATEST_RELEASE_URL = f"{REPOSITORY_URL}/releases/latest"
LATEST_RELEASE_API_URL = (
    "https://api.github.com/repos/Taiyo1031/HCQ/releases/latest"
)
PRODUCT_LONG_NAME = "HCQ — Houdini Cook Queue"

SCHEMA_VERSION = 1
SCHEMA_QUEUE_TEMPLATE = "hcq.queue-template"
SCHEMA_RUN_LIST = "hcq.run-list"
SCHEMA_RUN_STATUS = "hcq.run-status"
SCHEMA_RUN_RESULT = "hcq.run-result"

ALLOWED_ACTIONS = {
    "auto_detect",
    "filecache_save_to_disk",
    "rop_render",
    "top_cook",
    "force_cook",
    "press_button",
}

CPU_MODES = {"current", "all", "threads", "reserve", "single", "inherit"}
FRAME_RANGE_MODES = {"node", "playback", "custom"}
ERROR_BEHAVIORS = {"stop_queue", "skip_continue", "wait_for_user"}
VERIFICATION_MODES = {"basic", "none"}
EXISTING_OUTPUT_BEHAVIORS = {"ask_each", "overwrite", "stop", "skip"}
SAVE_BEHAVIORS = {"always", "ask", "never"}

QUEUE_STATES = {
    "idle",
    "preparing",
    "running",
    "pause_requested",
    "paused",
    "cancel_requested",
    "cancelled",
    "completed",
    "failed",
    "interrupted",
}

JOB_STATES = {
    "waiting",
    "validating",
    "preparing",
    "running",
    "completed",
    "completed_with_warning",
    "failed",
    "cancelled",
    "skipped",
    "unknown",
}

DEFAULT_SETTINGS = {
    "monitor_enabled": True,
    "monitor_poll_interval_ms": 750,
    "minimum_cook_duration_seconds": 5.0,
    "suppress_monitor_during_playback": True,
    "merge_rapid_notifications": True,
    "windows_notifications_enabled": False,
    "save_before_running": "always",
    "create_backup_before_saving": False,
    "default_cpu": {"mode": "current"},
    "default_on_error": "stop_queue",
    "default_retry_count": 0,
    "default_verification": "basic",
    "existing_output_behavior": "ask_each",
    "history_retention_days": 90,
    "notify_each_job": True,
    "notify_queue_complete": True,
    "last_opened_tab": 0,
    "window_geometry": None,
}

OUTPUT_PARAMETER_NAMES = (
    "file",
    "sopoutput",
    "vm_picture",
    "picture",
    "lopoutput",
    "filename",
    "output",
    "outputfile",
    "usdfile",
)
