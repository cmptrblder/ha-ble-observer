"""Config flow for BLE Observer."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_ACTIVE_WINDOW_MIN,
    CONF_RETENTION_DAYS,
    CONF_MASK_IDENTIFIERS,
    CONF_INCLUDE_TIMESTAMPS,
    CONF_PROMOTED,
    DEFAULT_ACTIVE_WINDOW_MIN,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_MASK_IDENTIFIERS,
    DEFAULT_INCLUDE_TIMESTAMPS,
)


class BLEObserverConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BLE Observer."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

        return self.async_create_entry(title="BLE Observer", data={})


class BLEObserverOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is None:
            opts = self.entry.options
            schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_ACTIVE_WINDOW_MIN,
                        default=opts.get(CONF_ACTIVE_WINDOW_MIN, DEFAULT_ACTIVE_WINDOW_MIN),
                    ): vol.All(int, vol.Range(min=1, max=120)),
                    vol.Optional(
                        CONF_RETENTION_DAYS,
                        default=opts.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS),
                    ): vol.All(int, vol.Range(min=1, max=365)),
                    vol.Optional(
                        CONF_MASK_IDENTIFIERS,
                        default=opts.get(CONF_MASK_IDENTIFIERS, DEFAULT_MASK_IDENTIFIERS),
                    ): bool,
                    vol.Optional(
                        CONF_INCLUDE_TIMESTAMPS,
                        default=opts.get(CONF_INCLUDE_TIMESTAMPS, DEFAULT_INCLUDE_TIMESTAMPS),
                    ): bool,
                    vol.Optional(
                        CONF_PROMOTED,
                        default=opts.get(CONF_PROMOTED, []),
                    ): list,
                }
            )
            return self.async_show_form(step_id="init", data_schema=schema)

        return self.async_create_entry(title="", data=user_input)


@callback
def async_get_options_flow(entry: config_entries.ConfigEntry):
    return BLEObserverOptionsFlow(entry)
