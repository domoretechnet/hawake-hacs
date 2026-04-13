"""Sensor platform for Allarise Alarm integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

_MINUTES_UNTIL_REFRESH = timedelta(minutes=1)

from .const import DASHBOARD_SENSORS, DOMAIN, PER_ALARM_SENSORS
from .coordinator import AllariseCoordinator, CommandEntityFactory

_FIRE_TIME_DASHBOARD_KEYS = frozenset({
    "active_alarm_fire_time",
    "active_alarm_snooze_fire_time",
    "quick_alarm_fire_time",
})
_FIRE_TIME_PER_ALARM_KEYS = frozenset({
    "fire_time",
    "snooze_fire_time",
})


def _minutes_until(iso_string: str) -> int | None:
    """Return whole minutes from now until an ISO timestamp, or None if unparseable."""
    parsed = dt_util.parse_datetime(iso_string)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = dt_util.as_utc(parsed)
    return round((parsed - dt_util.utcnow()).total_seconds() / 60)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[AllariseCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Allarise sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    # All dashboard sensors (including quick alarm) go on the dashboard device
    for key, name_suffix, icon, _ in DASHBOARD_SENSORS:
        entities.append(
            AllariseDashboardSensor(coordinator, key, name_suffix, icon)
        )

    async_add_entities(entities)

    # Register factory for dynamic per-alarm sensor creation
    def _sensor_factory(coord: AllariseCoordinator, alarm_index: int) -> list:
        return [
            AllarisePerAlarmSensor(coord, alarm_index, key, name_suffix, icon)
            for key, name_suffix, icon, _ in PER_ALARM_SENSORS
        ]

    coordinator.register_alarm_entity_factory(_sensor_factory, async_add_entities)

    # Register factory for dynamic command sensor creation
    def _command_sensor_factory(coord: AllariseCoordinator, command_name: str) -> list:
        return [AllariseCommandSensor(coord, command_name)]

    coordinator.register_command_entity_factory(_command_sensor_factory, async_add_entities)


class AllariseDashboardSensor(CoordinatorEntity[AllariseCoordinator], SensorEntity):
    """A dashboard sensor for Allarise."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AllariseCoordinator,
        key: str,
        name_suffix: str,
        icon: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name_suffix
        self._attr_icon = icon
        self._attr_unique_id = f"allarise_{coordinator.device_name}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"allarise_{self.coordinator.device_name}_dashboard")},
            name=f"Allarise {self.coordinator.device_name} - Dashboard",
            manufacturer="Allarise",
            model="iOS Alarm Clock",
        )

    @property
    def available(self) -> bool:
        """Return True if the app is online."""
        return self.coordinator.app_online

    @property
    def native_value(self) -> str:
        """Return the sensor value."""
        return self.coordinator.get_dashboard_state(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, int] | None:
        """Expose minutes_until for fire-time sensors."""
        if self._key not in _FIRE_TIME_DASHBOARD_KEYS:
            return None
        minutes = _minutes_until(self.coordinator.get_dashboard_state(self._key))
        if minutes is None:
            return None
        return {"minutes_until": minutes}

    async def async_added_to_hass(self) -> None:
        """Register a 1-minute tick for fire-time sensors so minutes_until stays fresh."""
        await super().async_added_to_hass()
        if self._key in _FIRE_TIME_DASHBOARD_KEYS:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass,
                    lambda _now: self.async_write_ha_state(),
                    _MINUTES_UNTIL_REFRESH,
                )
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class AllarisePerAlarmSensor(CoordinatorEntity[AllariseCoordinator], SensorEntity):
    """A per-alarm sensor — each alarm index gets its own HA device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AllariseCoordinator,
        alarm_index: int,
        key: str,
        name_suffix: str,
        icon: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._alarm_index = alarm_index
        self._key = key
        self._attr_name = name_suffix
        self._attr_icon = icon
        self._attr_unique_id = (
            f"allarise_{coordinator.device_name}_alarm_{alarm_index}_{key}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info — each alarm index is its own device."""
        alarm_name = self.coordinator.get_per_alarm_state(self._alarm_index, "name")
        if alarm_name in ("Unknown", ""):
            display_name = f"Allarise {self.coordinator.device_name} - Alarm {self._alarm_index}"
        else:
            display_name = f"Allarise {self.coordinator.device_name} - {alarm_name}"
        return DeviceInfo(
            identifiers={(DOMAIN, f"allarise_{self.coordinator.device_name}_alarm_{self._alarm_index}")},
            name=display_name,
            manufacturer="Allarise",
            model="iOS Alarm Clock",
        )

    @property
    def available(self) -> bool:
        """Return True if the app is online and the alarm exists."""
        return (
            self.coordinator.app_online
            and self.coordinator.is_alarm_active(self._alarm_index)
        )

    @property
    def native_value(self) -> str:
        """Return the sensor value."""
        return self.coordinator.get_per_alarm_state(self._alarm_index, self._key)

    @property
    def extra_state_attributes(self) -> dict[str, int] | None:
        """Expose minutes_until for fire-time sensors."""
        if self._key not in _FIRE_TIME_PER_ALARM_KEYS:
            return None
        minutes = _minutes_until(
            self.coordinator.get_per_alarm_state(self._alarm_index, self._key)
        )
        if minutes is None:
            return None
        return {"minutes_until": minutes}

    async def async_added_to_hass(self) -> None:
        """Register a 1-minute tick for fire-time sensors so minutes_until stays fresh."""
        await super().async_added_to_hass()
        if self._key in _FIRE_TIME_PER_ALARM_KEYS:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass,
                    lambda _now: self.async_write_ha_state(),
                    _MINUTES_UNTIL_REFRESH,
                )
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.is_alarm_removed(self._alarm_index):
            return
        self.async_write_ha_state()


class AllariseCommandSensor(CoordinatorEntity[AllariseCoordinator], SensorEntity):
    """A sensor for an arm-widget command — grouped under the Dashboard device.

    One entity is dynamically created per command name the first time the app
    publishes {prefix}/{device}/command/{name}/status = fired|idle.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AllariseCoordinator,
        command_name: str,
    ) -> None:
        """Initialize the command sensor."""
        super().__init__(coordinator)
        self._command_name = command_name
        # Display name is the raw command name (e.g. "lr_shutdown" → "lr_shutdown")
        self._attr_name = command_name.replace("_", " ").title()
        self._attr_icon = "mdi:console"
        self._attr_unique_id = (
            f"allarise_{coordinator.device_name}_command_{command_name}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info — command sensors live on the Dashboard device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"allarise_{self.coordinator.device_name}_dashboard")},
            name=f"Allarise {self.coordinator.device_name} - Dashboard",
            manufacturer="Allarise",
            model="iOS Alarm Clock",
        )

    @property
    def available(self) -> bool:
        """Return True if the app is online."""
        return self.coordinator.app_online

    @property
    def native_value(self) -> str:
        """Return 'fired' or 'idle'."""
        return self.coordinator.get_command_state(self._command_name)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
