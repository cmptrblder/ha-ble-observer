"""Binary sensors for BLE Observer (promoted presence)."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_UPDATED
from .coordinator import BLEObserverCoordinator, DeviceRecord


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: BLEObserverCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = []
    for rule, _ in coordinator.iter_promoted():
        dev_name = rule.get("name") or rule.get("mac") or rule.get("fingerprint_id") or "promoted"
        entities.append(BLEPromotedPresenceBinary(coordinator, entry, rule, f"{dev_name} Present"))

    async_add_entities(entities)


class _DispatcherMixin:
    async def async_added_to_hass(self) -> None:
        self.async_write_ha_state()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATED,
                self.async_write_ha_state,
            )
        )


class BLEPromotedPresenceBinary(_DispatcherMixin, BinarySensorEntity):
    _attr_should_poll = False

    def __init__(self, coordinator: BLEObserverCoordinator, entry: ConfigEntry, rule: dict, name: str) -> None:
        self.coordinator = coordinator
        self.entry = entry
        self.rule = rule
        self._attr_name = name

        raw = rule.get("mac") or rule.get("fingerprint_id") or rule.get("name") or "promoted"
        rid = hashlib.sha1(str(raw).encode("utf-8")).hexdigest()[:12]
        self._attr_unique_id = f"{entry.entry_id}_promoted_presence_{rid}".lower()

    def _match(self) -> Optional[DeviceRecord]:
        mac = self.rule.get("mac")
        fp = self.rule.get("fingerprint_id")
        if mac:
            d = self.coordinator.devices.get(f"mac:{str(mac).upper()}")
            if d:
                return d
            for dev in self.coordinator.devices.values():
                if dev.mac and dev.mac.upper() == str(mac).upper():
                    return dev
        if fp:
            for dev in self.coordinator.devices.values():
                if dev.fingerprint_id == fp:
                    return dev
        return None

    @property
    def is_on(self) -> bool:
        d = self._match()
        if not d:
            return False
        return d.last_seen >= (dt_util.utcnow() - self.coordinator.active_window)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        d = self._match()
        if not d:
            return {"matched": False}
        return {
            "matched": True,
            "stable_id": d.stable_id,
            "fingerprint_id": d.fingerprint_id,
            "vendor": d.vendor,
            "mac": d.mac,
            "confidence": d.confidence,
            "device_family": d.device_family,
            "capabilities": sorted(list(d.capabilities)),
            "primary_source": d.primary_source,
            "last_seen": d.last_seen.isoformat(),
            "rssi_last": d.rssi_last,
        }
