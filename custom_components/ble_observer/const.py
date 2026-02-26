"""Constants for BLE Observer."""

DOMAIN = "ble_observer"

PLATFORMS = ["sensor", "binary_sensor"]

SIGNAL_UPDATED = f"{DOMAIN}_updated"

CONF_ACTIVE_WINDOW_MIN = "active_window_minutes"
CONF_RETENTION_DAYS = "retention_days"
CONF_MASK_IDENTIFIERS = "mask_identifiers"
CONF_INCLUDE_TIMESTAMPS = "include_timestamps"
CONF_PROMOTED = "promoted"

DEFAULT_ACTIVE_WINDOW_MIN = 5
DEFAULT_RETENTION_DAYS = 14
DEFAULT_MASK_IDENTIFIERS = True
DEFAULT_INCLUDE_TIMESTAMPS = False
