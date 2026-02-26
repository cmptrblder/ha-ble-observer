"""Coordinator / core logic for BLE Observer."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    SIGNAL_UPDATED,
    CONF_ACTIVE_WINDOW_MIN,
    CONF_RETENTION_DAYS,
    CONF_PROMOTED,
    DEFAULT_ACTIVE_WINDOW_MIN,
    DEFAULT_RETENTION_DAYS,
)

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION = 1
_STORE_KEY = f"{DOMAIN}.registry"


def _now() -> datetime:
    return dt_util.utcnow()


def _iso(dt: datetime) -> str:
    return dt_util.as_utc(dt).isoformat()


def _safe_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _normalize_uuid(u: str) -> str:
    return str(u).strip().lower()


def _mask_mac(mac: str) -> str:
    m = mac.upper()
    parts = m.split(":")
    if len(parts) != 6:
        return "??:??:??:??:??:??"
    return ":".join(parts[:3] + ["XX", "XX", "XX"])


def _payload_signature(packet: Optional[str]) -> Optional[str]:
    if not packet:
        return None
    s = re.sub(r"[^0-9a-fA-F]", "", str(packet))
    if not s:
        return None
    return f"len{len(s)//2}:{s[:16].lower()}"


def _fingerprint(manufacturer: Optional[str], mfg_id: Optional[str], uuids: Set[str], sig: Optional[str], time_bucket: str) -> str:
    base = "|".join(
        [
            f"m={manufacturer or ''}",
            f"mid={mfg_id or ''}",
            "u=" + ",".join(sorted(uuids)),
            f"s={sig or ''}",
            f"tb={time_bucket}",
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def classify_device_family(entity_id: str, attrs: dict) -> str:
    eid = entity_id.lower()
    if "ibs_th" in eid:
        return "inkbird_ibs_th"
    if attrs.get("major") is not None and attrs.get("minor") is not None:
        return "ibeacon"
    mfg = attrs.get("manufacturer") or attrs.get("vendor") or attrs.get("company")
    if mfg in ("Apple", "Apple, Inc."):
        return "apple_ble"
    return "unknown"


def derive_canonical_id(entity_id: str, attrs: dict, rec_first_seen: datetime) -> str:
    unique_id = attrs.get("unique_id")
    if unique_id:
        m = re.search(r"ibs_th_([0-9a-fA-F]{4})", str(unique_id).lower())
        if m:
            return f"inkbird:{m.group(1)}"

    if "ibs_th" in entity_id.lower():
        m = re.search(r"ibs_th_([0-9a-fA-F]{4})", entity_id.lower())
        if m:
            return f"inkbird:{m.group(1)}"

    uuid = attrs.get("uuid")
    major = attrs.get("major")
    minor = attrs.get("minor")
    if uuid and major is not None and minor is not None:
        return f"ibeacon:{str(uuid).lower()}:{major}:{minor}"

    mac = attrs.get("mac") or attrs.get("address") or attrs.get("ble_mac")
    if mac:
        return f"mac:{str(mac).upper()}"

    manufacturer = attrs.get("manufacturer") or attrs.get("vendor") or attrs.get("company")
    mfg_id = attrs.get("manufacturer_id") or attrs.get("company_id") or attrs.get("mfg_id")
    uuids_raw = attrs.get("service_uuids") or attrs.get("uuids") or attrs.get("uuid")
    service_uuids: Set[str] = set()
    if isinstance(uuids_raw, (list, tuple, set)):
        service_uuids = {_normalize_uuid(u) for u in uuids_raw if u}
    elif isinstance(uuids_raw, str) and uuids_raw:
        service_uuids = {_normalize_uuid(uuids_raw)}
    sig = _payload_signature(attrs.get("packet") or attrs.get("raw") or attrs.get("payload"))
    time_bucket = rec_first_seen.date().isoformat()
    fp = _fingerprint(str(manufacturer) if manufacturer else None, str(mfg_id) if mfg_id else None, service_uuids, sig, time_bucket)
    return f"fp:{fp}"


def update_confidence(rec: "DeviceRecord") -> None:
    now = _now()
    if rec.device_family == "inkbird_ibs_th":
        base = 0.85
    elif rec.device_family == "ibeacon":
        base = 0.75
    elif rec.mac_behavior == "static":
        base = 0.65
    else:
        base = 0.35

    age_days = max(1, (now - rec.first_seen).days + 1)
    longevity_bonus = min(0.15, age_days * 0.02)

    inactive_days = (now - rec.last_seen).days
    decay = max(0.5, 1 - inactive_days * 0.1) if inactive_days > 2 else 1.0

    rec.confidence = round(min(0.95, max(0.1, (base + longevity_bonus) * decay)), 2)


@dataclass
class DeviceRecord:
    stable_id: str
    mac: Optional[str] = None
    vendor: Optional[str] = None
    manufacturer_id: Optional[str] = None
    service_uuids: Set[str] = field(default_factory=set)

    payload_sig: Optional[str] = None
    fingerprint_id: Optional[str] = None
    confidence: float = 0.0

    device_family: str = "unknown"
    capabilities: Set[str] = field(default_factory=set)

    first_seen: datetime = field(default_factory=_now)
    last_seen: datetime = field(default_factory=_now)
    seen_count: int = 0

    rssi_last: Optional[int] = None
    rssi_max: Optional[int] = None
    rssi_sum: int = 0
    rssi_n: int = 0

    mac_behavior: str = "unknown"

    sources: Dict[str, int] = field(default_factory=dict)
    primary_source: Optional[str] = None

    def update_rssi(self, rssi: Optional[int]) -> None:
        if rssi is None:
            return
        self.rssi_last = rssi
        self.rssi_max = rssi if self.rssi_max is None else max(self.rssi_max, rssi)
        self.rssi_sum += rssi
        self.rssi_n += 1

    @property
    def rssi_avg(self) -> Optional[float]:
        return (self.rssi_sum / self.rssi_n) if self.rssi_n > 0 else None


class BLEObserverCoordinator:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

        self._store = Store(hass, _STORE_VERSION, _STORE_KEY)
        self.devices: Dict[str, DeviceRecord] = {}

        self._tracked_entity_ids: Set[str] = set()
        self._unsub_state = None
        self._rediscover_cancel = None

        self._save_debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=30,
            immediate=False,
            function=self._save,
        )

    @property
    def active_window(self) -> timedelta:
        mins = self.entry.options.get(CONF_ACTIVE_WINDOW_MIN, DEFAULT_ACTIVE_WINDOW_MIN)
        return timedelta(minutes=int(mins))

    @property
    def retention_window(self) -> timedelta:
        days = self.entry.options.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)
        return timedelta(days=int(days))

    @property
    def promoted(self) -> List[Dict[str, Any]]:
        return list(self.entry.options.get(CONF_PROMOTED, []))

    async def async_setup(self) -> None:
        await self._load()

        # Discover and subscribe (handles initial subscribe)
        await self._discover_ble_monitor_entities()

        # Periodic rediscovery to pick up new entities
        self._rediscover_cancel = async_track_time_interval(
            self.hass,
            self._rediscover_entities,
            timedelta(minutes=5),
        )

        self._purge_old()
        self._save_debouncer.async_schedule_call()

        # Kick an initial update so entities aren't unavailable
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    async def async_shutdown(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._rediscover_cancel:
            self._rediscover_cancel()
            self._rediscover_cancel = None
        await self._save()

    async def _load(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        try:
            for stable_id, rec in data.get("devices", {}).items():
                dr = DeviceRecord(
                    stable_id=stable_id,
                    mac=rec.get("mac"),
                    vendor=rec.get("vendor"),
                    manufacturer_id=rec.get("manufacturer_id"),
                    service_uuids=set(rec.get("service_uuids", [])),
                    payload_sig=rec.get("payload_sig"),
                    fingerprint_id=rec.get("fingerprint_id"),
                    confidence=float(rec.get("confidence", 0.0)),
                    device_family=rec.get("device_family", "unknown"),
                    capabilities=set(rec.get("capabilities", [])),
                    first_seen=dt_util.parse_datetime(rec.get("first_seen")) or _now(),
                    last_seen=dt_util.parse_datetime(rec.get("last_seen")) or _now(),
                    seen_count=int(rec.get("seen_count", 0)),
                    rssi_last=rec.get("rssi_last"),
                    rssi_max=rec.get("rssi_max"),
                    rssi_sum=int(rec.get("rssi_sum", 0)),
                    rssi_n=int(rec.get("rssi_n", 0)),
                    mac_behavior=rec.get("mac_behavior", "unknown"),
                    sources=dict(rec.get("sources", {})),
                    primary_source=rec.get("primary_source"),
                )
                self.devices[stable_id] = dr
        except Exception as exc:
            _LOGGER.warning("Failed to load stored BLE Observer data: %s", exc)
            self.devices = {}

    async def _save(self) -> None:
        out: Dict[str, Any] = {"devices": {}}
        for sid, d in self.devices.items():
            out["devices"][sid] = {
                "mac": d.mac,
                "vendor": d.vendor,
                "manufacturer_id": d.manufacturer_id,
                "service_uuids": sorted(list(d.service_uuids)),
                "payload_sig": d.payload_sig,
                "fingerprint_id": d.fingerprint_id,
                "confidence": d.confidence,
                "device_family": d.device_family,
                "capabilities": sorted(list(d.capabilities)),
                "first_seen": _iso(d.first_seen),
                "last_seen": _iso(d.last_seen),
                "seen_count": d.seen_count,
                "rssi_last": d.rssi_last,
                "rssi_max": d.rssi_max,
                "rssi_sum": d.rssi_sum,
                "rssi_n": d.rssi_n,
                "mac_behavior": d.mac_behavior,
                "sources": d.sources,
                "primary_source": d.primary_source,
            }
        await self._store.async_save(out)

    async def _discover_ble_monitor_entities(self) -> None:
        ent_reg = er.async_get(self.hass)
        ble_entry_ids = {e.entry_id for e in self.hass.config_entries.async_entries("ble_monitor")}

        entity_ids = {
            entity_id
            for entity_id, ent in ent_reg.entities.items()
            if ent.config_entry_id in ble_entry_ids
        }

        # Resubscribe only if set changed
        if entity_ids != self._tracked_entity_ids:
            self._tracked_entity_ids = entity_ids
            self._subscribe()

    async def _rediscover_entities(self, _now_dt: datetime) -> None:
        await self._discover_ble_monitor_entities()

    def _subscribe(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

        if not self._tracked_entity_ids:
            _LOGGER.debug("BLE Observer: no ble_monitor entities to subscribe to")
            return

        _LOGGER.debug("BLE Observer subscribing to %d ble_monitor entities", len(self._tracked_entity_ids))

        self._unsub_state = async_track_state_change_event(
            self.hass,
            list(self._tracked_entity_ids),
            self._handle_state_change,
        )

    @callback
    def _handle_state_change(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        attrs = dict(new_state.attributes or {})
        if attrs.get("restored"):
            return

        entity_id = new_state.entity_id

        mac = attrs.get("mac") or attrs.get("address") or attrs.get("ble_mac")
        mac = str(mac).upper() if mac else None

        vendor = attrs.get("manufacturer") or attrs.get("vendor") or attrs.get("company")
        vendor = str(vendor) if vendor is not None else None

        mfg_id = attrs.get("manufacturer_id") or attrs.get("company_id") or attrs.get("mfg_id")
        mfg_id = str(mfg_id) if mfg_id is not None else None

        uuids_raw = attrs.get("service_uuids") or attrs.get("uuids") or attrs.get("uuid")
        service_uuids: Set[str] = set()
        if isinstance(uuids_raw, (list, tuple, set)):
            service_uuids = {_normalize_uuid(u) for u in uuids_raw if u}
        elif isinstance(uuids_raw, str) and uuids_raw:
            service_uuids = {_normalize_uuid(uuids_raw)}

        packet = attrs.get("packet") or attrs.get("raw") or attrs.get("payload")
        sig = _payload_signature(packet) if packet else None

        rssi = _safe_int(attrs.get("rssi") or attrs.get("RSSI") or attrs.get("signal_strength"))
        source = attrs.get("source") or attrs.get("scanner") or attrs.get("adapter")

        rec_first_seen = _now()
        device_family = classify_device_family(entity_id, attrs)
        stable_id = derive_canonical_id(entity_id, attrs, rec_first_seen)

        rec = self.devices.get(stable_id)
        if rec is None:
            rec = DeviceRecord(stable_id=stable_id)
            rec.first_seen = rec_first_seen
            self.devices[stable_id] = rec

        rec.last_seen = _now()
        rec.seen_count += 1
        rec.device_family = device_family

        if mac:
            rec.mac = mac
        if vendor:
            rec.vendor = vendor
        if mfg_id:
            rec.manufacturer_id = mfg_id
        if service_uuids:
            rec.service_uuids |= service_uuids
        if sig:
            rec.payload_sig = sig

        eid_l = entity_id.lower()
        if "temperature" in eid_l or attrs.get("device_class") == "temperature":
            rec.capabilities.add("temperature")
        if "humidity" in eid_l or attrs.get("device_class") == "humidity":
            rec.capabilities.add("humidity")
        if "battery" in eid_l or attrs.get("device_class") == "battery":
            rec.capabilities.add("battery")
        if "measured_power" in eid_l:
            rec.capabilities.add("measured_power")

        time_bucket = rec.first_seen.date().isoformat()
        rec.fingerprint_id = _fingerprint(rec.vendor, rec.manufacturer_id, rec.service_uuids, rec.payload_sig, time_bucket)

        if rec.device_family == "inkbird_ibs_th" and rec.mac:
            rec.mac_behavior = "static"
        elif rec.device_family == "ibeacon":
            rec.mac_behavior = "rotating"
        else:
            rec.mac_behavior = "unknown" if rec.mac else "rotating"

        if source:
            rec.sources[source] = rec.sources.get(source, 0) + 1
            rec.primary_source = max(rec.sources, key=rec.sources.get)

        rec.update_rssi(rssi)
        update_confidence(rec)

        if rec.seen_count % 100 == 0:
            self._purge_old()
        self._save_debouncer.async_schedule_call()

        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    def _purge_old(self) -> None:
        cutoff = _now() - self.retention_window
        to_del = [sid for sid, d in self.devices.items() if d.last_seen < cutoff]
        for sid in to_del:
            self.devices.pop(sid, None)

    def summary(self) -> Dict[str, Any]:
        now = _now()
        active_cutoff = now - self.active_window

        total = len(self.devices)
        active = 0
        unknown = 0
        rotating = 0
        vendor_counts: Dict[str, int] = {}
        top_rssi: List[Tuple[int, str]] = []

        for sid, d in self.devices.items():
            if d.last_seen < active_cutoff:
                continue
            active += 1
            if not d.vendor:
                unknown += 1
            if d.mac_behavior == "rotating":
                rotating += 1
            if d.vendor:
                vendor_counts[d.vendor] = vendor_counts.get(d.vendor, 0) + 1
            if d.rssi_last is not None:
                top_rssi.append((d.rssi_last, sid))

        top_rssi.sort(reverse=True)
        top_list = []
        for rssi, sid in top_rssi[:10]:
            d = self.devices[sid]
            top_list.append(
                {
                    "stable_id": sid,
                    "fingerprint_id": d.fingerprint_id,
                    "vendor": d.vendor,
                    "rssi": rssi,
                    "primary_source": d.primary_source,
                    "last_seen": _iso(d.last_seen),
                }
            )

        return {
            "total_seen": total,
            "active_last_window": active,
            "unknown_active": unknown,
            "rotating_active": rotating,
            "vendor_counts": vendor_counts,
            "top_rssi": top_list,
            "active_window_minutes": int(self.active_window.total_seconds() / 60),
        }

    def iter_promoted(self) -> List[Tuple[Dict[str, Any], Optional[DeviceRecord]]]:
        results: List[Tuple[Dict[str, Any], Optional[DeviceRecord]]] = []
        for rule in self.promoted:
            mac = rule.get("mac")
            fp = rule.get("fingerprint_id")
            match = None
            if mac:
                sid = f"mac:{str(mac).upper()}"
                match = self.devices.get(sid)
                if match is None:
                    for d in self.devices.values():
                        if d.mac and d.mac.upper() == str(mac).upper():
                            match = d
                            break
            elif fp:
                for d in self.devices.values():
                    if d.fingerprint_id == fp:
                        match = d
                        break
            results.append((rule, match))
        return results


__all__ = ["BLEObserverCoordinator", "DeviceRecord", "_mask_mac"]
