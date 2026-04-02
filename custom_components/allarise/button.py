"""Button platform for Allarise Alarm integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

import json

from .const import DASHBOARD_BUTTONS, DOMAIN, PER_ALARM_BUTTONS, QUICK_ALARM_BUTTONS
from .coordinator import AllariseCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[AllariseCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Allarise buttons."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = []

    # Dashboard buttons
    for key, name_suffix, icon in DASHBOARD_BUTTONS:
        entities.append(
            AllariseDashboardButton(coordinator, key, name_suffix, icon)
        )

    # Quick Alarm buttons — Dismiss (when ringing) and Delete (cancel pending)
    for key, name_suffix, icon in QUICK_ALARM_BUTTONS:
        entities.append(
            AllariseQuickAlarmButton(coordinator, key, name_suffix, icon)
        )

    async_add_entities(entities)

    # Register factory for dynamic per-alarm button creation
    def _button_factory(coord: AllariseCoordinator, alarm_index: int) -> list:
        return [
            AllarisePerAlarmButton(coord, alarm_index, key, name_suffix, icon)
            for key, name_suffix, icon in PER_ALARM_BUTTONS
        ]

    coordinator.register_alarm_entity_factory(_button_factory, async_add_entities)


class AllariseDashboardButton(CoordinatorEntity[AllariseCoordinator], ButtonEntity):
    """A dashboard button for Allarise (dismiss, snooze, skip, kill_snoozed)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: AllariseCoordinator,
        key: str,
        name_suffix: str,
        icon: str,
    ) -> None:
        """Initialize the button."""
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
        """Return True if the button action is available."""
        if not self.coordinator.app_online:
            return False
        if self._key == "dismiss":
            return self.coordinator.is_dismiss_available()
        if self._key == "snooze":
            return self.coordinator.is_snooze_available()
        if self._key == "kill_snoozed":
            return self.coordinator.is_kill_snoozed_available()
        if self._key == "unskip":
            return self.coordinator.is_unskip_available()
        return True  # skip is always available when app is online

    async def async_press(self) -> None:
        """Handle the button press — publish MQTT command."""
        await self.coordinator.async_publish_command(self._key)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class AllarisePerAlarmButton(CoordinatorEntity[AllariseCoordinator], ButtonEntity):
    """A per-alarm button — grouped under the per-alarm device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: AllariseCoordinator,
        alarm_index: int,
        key: str,
        name_suffix: str,
        icon: str,
    ) -> None:
        """Initialize the button."""
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
        """Return True if the button is available."""
        if not self.coordinator.app_online:
            return False
        if not self.coordinator.is_alarm_active(self._alarm_index):
            return False
        if self._key == "dismiss":
            return self.coordinator.is_dismiss_available(self._alarm_index)
        if self._key == "snooze":
            return self.coordinator.is_snooze_available(self._alarm_index)
        if self._key == "skip":
            return self.coordinator.is_skip_available(self._alarm_index)
        if self._key == "unskip":
            return self.coordinator.is_unskip_available(self._alarm_index)
        if self._key == "kill_snoozed":
            return self.coordinator.is_kill_snoozed_available(self._alarm_index)
        return True

    async def async_press(self) -> None:
        """Handle the button press — publish MQTT command."""
        if self._key == "delete":
            # Delete publishes to the dashboard command topic with the index
            payload = json.dumps({"index": self._alarm_index})
            await self.coordinator.async_publish_command("delete_alarm", payload)
        else:
            await self.coordinator.async_publish_alarm_command(
                self._alarm_index, self._key
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.is_alarm_removed(self._alarm_index):
            return
        self.async_write_ha_state()


class AllariseQuickAlarmButton(CoordinatorEntity[AllariseCoordinator], ButtonEntity):
    """A quick alarm button — grouped under the Dashboard device.

    Only dismiss (when a quick alarm is ringing) and delete_quick_alarm
    (cancel the next pending quick alarm) are exposed. Snooze, skip, etc.
    are intentionally omitted because quick alarms are one-time use.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: AllariseCoordinator,
        key: str,
        name_suffix: str,
        icon: str,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name_suffix
        self._attr_icon = icon
        self._attr_unique_id = f"allarise_{coordinator.device_name}_quick_alarm_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info — grouped under the Dashboard device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"allarise_{self.coordinator.device_name}_dashboard")},
            name=f"Allarise {self.coordinator.device_name} - Dashboard",
            manufacturer="Allarise",
            model="iOS Alarm Clock",
        )

    @property
    def available(self) -> bool:
        """Return True if the button action is currently available."""
        if not self.coordinator.app_online:
            return False
        if self._key == "dismiss":
            # Dismiss is available when a quick alarm is ringing
            return self.coordinator.is_dismiss_available()
        if self._key == "delete_quick_alarm":
            # Delete is available whenever there is a pending quick alarm
            return self.coordinator.is_quick_alarm_active()
        return False

    async def async_press(self) -> None:
        """Handle the button press — publish MQTT dashboard command."""
        await self.coordinator.async_publish_command(self._key)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
