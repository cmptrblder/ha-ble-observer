"""Sensors for BLE Observer."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATED
from .coordinator import BLEObserverCoordinator, DeviceRecord


SUMMARY_SENSORS = [
    ("active_last_window", "Active BLE devices (window)"),
    ("total_seen", "Total BLE devices seen (retained)"),
    ("unknown_active", "Unknown BLE devices active"),
    ("rotating_active", "Rotating-id BLE devices active"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: BLEObserverCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    for key, name in SUMMARY_SENSORS:
        entities.append(BLESummarySensor(coordinator, entry, key, name))

    for rule, _ in coordinator.iter_promoted():
        dev_name = rule.get("name") or rule.get("mac") or rule.get("fingerprint_id") or "promoted"
        entities.append(BLEPromotedRSSISensor(coordinator, entry, rule, f"{dev_name} RSSI"))
        entities.append(BLEPromotedLastSeenSensor(coordinator, entry, rule, f"{dev_name} Last seen"))

    async_add_entities(entities)


class _DispatcherMixin:
    async def async_added_to_hass(self) -> None:
        # Initial write so entities are not unavailable before first BLE update.
        self.async_write_ha_state()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATED,
                self.async_write_ha_state,
            )
        )


class BLESummarySensor(_DispatcherMixin, SensorEntity):
    _attr_should_poll = False

    def __init__(self, coordinator: BLEObserverCoordinator, entry: ConfigEntry, key: str, name: str) -> None:
        self.coordinator = coordinator
        self.entry = entry
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_summary_{key}"

    @property
    def native_value(self):
        return self.coordinator.summary().get(self.key, 0)

    @property
    def extra_state_attributes(self):
        s = self.coordinator.summary()
        if self.key == "active_last_window":
            return {
                "vendor_counts": s.get("vendor_counts", {}),
                "top_rssi": s.get("top_rssi", []),
                "active_window_minutes": s.get("active_window_minutes"),
            }
        return None


class _PromotedBase(_DispatcherMixin, SensorEntity):
    _attr_should_poll = False

    def __init__(self, coordinator: BLEObserverCoordinator, entry: ConfigEntry, rule: dict, name: str) -> None:
        self.coordinator = coordinator
        self.entry = entry
        self.rule = rule
        self._attr_name = name

        raw = rule.get("mac") or rule.get("fingerprint_id") or rule.get("name") or "promoted"
        rid = hashlib.sha1(str(raw).encode("utf-8")).hexdigest()[:12]
        self._attr_unique_id = f"{entry.entry_id}_promoted_{rid}_{self.__class__.__name__}".lower()

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
        }


class BLEPromotedRSSISensor(_PromotedBase):
    @property
    def native_value(self):
        d = self._match()
        return None if not d else d.rssi_last


class BLEPromotedLastSeenSensor(_PromotedBase):
    @property
    def native_value(self):
        d = self._match()
        return None if not d else d.last_seen.isoformat()
