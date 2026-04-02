"""Sensor platform for Allarise Alarm integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DASHBOARD_SENSORS, DOMAIN, PER_ALARM_SENSORS
from .coordinator import AllariseCoordinator


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

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.is_alarm_removed(self._alarm_index):
            return
        self.async_write_ha_state()
