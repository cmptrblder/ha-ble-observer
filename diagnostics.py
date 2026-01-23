"""Diagnostics for BLE Observer."""

from __future__ import annotations

from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_MASK_IDENTIFIERS,
    CONF_INCLUDE_TIMESTAMPS,
    DEFAULT_MASK_IDENTIFIERS,
    DEFAULT_INCLUDE_TIMESTAMPS,
)
from .coordinator import BLEObserverCoordinator, _mask_mac


def _iso(dt):
    from homeassistant.util import dt as dt_util
    return dt_util.as_utc(dt).isoformat()


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> Dict[str, Any]:
    coordinator: BLEObserverCoordinator = hass.data[DOMAIN][entry.entry_id]

    mask = entry.options.get(CONF_MASK_IDENTIFIERS, DEFAULT_MASK_IDENTIFIERS)
    include_ts = entry.options.get(CONF_INCLUDE_TIMESTAMPS, DEFAULT_INCLUDE_TIMESTAMPS)

    devices_out = []
    for d in coordinator.devices.values():
        device: Dict[str, Any] = {
            "stable_id": d.stable_id if not mask else (d.stable_id.replace(d.mac, _mask_mac(d.mac)) if d.mac else d.stable_id),
            "mac": (d.mac if not mask else (_mask_mac(d.mac) if d.mac else None)),
            "vendor": d.vendor,
            "manufacturer_id": d.manufacturer_id,
            "service_uuids": sorted(list(d.service_uuids)),
            "payload_signature": d.payload_sig,
            "fingerprint_id": d.fingerprint_id,
            "confidence": d.confidence,
            "device_family": d.device_family,
            "capabilities": sorted(list(d.capabilities)),
            "rssi_last": d.rssi_last,
            "rssi_avg": d.rssi_avg,
            "rssi_max": d.rssi_max,
            "mac_behavior": d.mac_behavior,
            "primary_source": d.primary_source,
        }

        if include_ts:
            device["first_seen"] = _iso(d.first_seen)
            device["last_seen"] = _iso(d.last_seen)
            device["seen_count"] = d.seen_count

        devices_out.append(device)

    return {
        "summary": coordinator.summary(),
        "options": dict(entry.options),
        "device_count": len(devices_out),
        "devices": devices_out,
    }
