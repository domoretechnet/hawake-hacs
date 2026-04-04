"""DataUpdateCoordinator for Allarise Alarm integration — MQTT-based."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DASHBOARD_SENSORS,
    DEFAULT_ZONE_SLUG,
    DOMAIN,
    PER_ALARM_SENSORS,
    SUB_ALARM_WILDCARD,
    SUB_AVAILABILITY,
    SUB_ARM_STATE,
    SUB_COMMAND_STATUS_WILDCARD,
    SUB_DASHBOARD_WILDCARD,
    SUB_SENSOR_WILDCARD,
    TOPIC_ALARM_COMMAND,
    TOPIC_ARM_COMMAND,
    TOPIC_ARM_STATE,
    TOPIC_COMMAND,
    TOPIC_HA_STATUS,
)

_LOGGER = logging.getLogger(__name__)

# Factory signature: (coordinator, alarm_index) -> list of entities
AlarmEntityFactory = Callable[["AllariseCoordinator", int], list[Entity]]

# Factory signature: (coordinator, command_name) -> list of entities
CommandEntityFactory = Callable[["AllariseCoordinator", str], list[Entity]]

# Dashboard sensor keys that describe the currently active alarm.
# These are suppressed (kept at their idle defaults) while an alert mission is active
# so that alert alarms do not appear as regular alarms on the HA Dashboard device.
_ACTIVE_ALARM_SENSOR_KEYS = frozenset({
    "alarm_state",
    "active_alarm_index",
    "active_alarm_name",
    "active_alarm_mission",
    "active_alarm_fire_time",
    "active_alarm_snooze_fire_time",
})


class AllariseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Allarise Alarm data — subscribes to MQTT topics."""

    @staticmethod
    def sanitize_device_name(name: str) -> str:
        """Sanitize a device name to match the iOS app's topic format.

        Mirrors DeviceSettings.sanitizedDeviceName in Swift:
        lowercase, spaces→dashes, strip non-alphanumeric (keep dashes).
        """
        sanitized = name.lower().replace(" ", "-")
        return re.sub(r"[^a-z0-9-]", "", sanitized)

    def __init__(
        self,
        hass: HomeAssistant,
        device_name: str,
        topic_prefix: str,
        config_entry_id: str = "",
        zone_slug: str = DEFAULT_ZONE_SLUG,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Allarise {device_name}",
        )
        self.device_name = self.sanitize_device_name(device_name)
        self.topic_prefix = topic_prefix
        self._zone_slug = zone_slug
        self._config_entry_id = config_entry_id

        # State storage
        self._dashboard_states: dict[str, str] = {}
        self._per_alarm_states: dict[int, dict[str, str]] = {}
        self._active_alarms: set[int] = set()
        self._app_online = False
        self._arm_state = False

        # Button availability
        self._dismiss_available = False
        self._snooze_available = False
        self._kill_snoozed_available = False
        self._unskip_available = False
        self._per_alarm_dismiss_available: dict[int, bool] = {}
        self._per_alarm_snooze_available: dict[int, bool] = {}
        self._per_alarm_skip_available: dict[int, bool] = {}
        self._per_alarm_kill_snoozed_available: dict[int, bool] = {}
        self._per_alarm_unskip_available: dict[int, bool] = {}

        # MQTT subscription unsubscribe callbacks
        self._unsubs: list[Any] = []

        # Dynamic entity creation: alarm indices that already have entities
        self._known_alarm_indices: set[int] = set()
        # Alarm indices that have been removed — entities must stop updating
        self._removed_alarm_indices: set[int] = set()
        # Alarm indices whose mission is "alert" — no per-alarm HA entities created
        self._alert_alarm_indices: set[int] = set()
        # True while an MQTT alert command is the active alarm — suppresses dashboard sensors
        self._alert_active: bool = False
        # Per-platform factory + async_add_entities pairs
        self._alarm_entity_factories: list[
            tuple[AlarmEntityFactory, AddEntitiesCallback]
        ] = []

        # Dynamic command sensor state: command_name → "fired" | "idle"
        self._command_states: dict[str, str] = {}
        # Command names that already have entities created for them
        self._known_commands: set[str] = set()
        # Per-platform factory + async_add_entities pairs for command sensors
        self._command_entity_factories: list[
            tuple[CommandEntityFactory, AddEntitiesCallback]
        ] = []

        # Initialize default dashboard states
        for key, _, _, default in DASHBOARD_SENSORS:
            self._dashboard_states[key] = default

    # ─── Topic helpers ────────────────────────────────────────────────

    def _topic(self, template: str, **kwargs: Any) -> str:
        """Format a topic template with prefix, device name, and zone slug."""
        return template.format(
            prefix=self.topic_prefix,
            device=self.device_name,
            zone=self._zone_slug,
            **kwargs,
        )

    # ─── Dynamic entity registration ─────────────────────────────────

    def register_alarm_entity_factory(
        self,
        factory: AlarmEntityFactory,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Register a per-alarm entity factory for dynamic alarm creation.

        When a new alarm index appears via MQTT, each registered factory
        is called to create entities for that alarm.

        Factory signature: (coordinator, alarm_index) -> list[Entity]
        """
        self._alarm_entity_factories.append((factory, async_add_entities))

        # Create entities for any alarm indices that already exist
        for alarm_index in sorted(self._known_alarm_indices):
            new_entities = factory(self, alarm_index)
            if new_entities:
                async_add_entities(new_entities)

    def register_command_entity_factory(
        self,
        factory: CommandEntityFactory,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Register a per-command entity factory for dynamic command sensor creation.

        When a new command name appears via command/+/status, each registered
        factory is called to create sensor entities for that command.

        Factory signature: (coordinator, command_name) -> list[Entity]
        """
        self._command_entity_factories.append((factory, async_add_entities))

        # Create entities for any command names already discovered
        for command_name in sorted(self._known_commands):
            new_entities = factory(self, command_name)
            if new_entities:
                async_add_entities(new_entities)

    def _create_entities_for_new_command(self, command_name: str) -> None:
        """Create sensor entities for a newly discovered command name."""
        if command_name in self._known_commands:
            return
        self._known_commands.add(command_name)
        _LOGGER.info("New command %r discovered — creating sensor entity", command_name)

        for factory, async_add_entities in self._command_entity_factories:
            new_entities = factory(self, command_name)
            if new_entities:
                async_add_entities(new_entities)

    def get_command_state(self, command_name: str) -> str:
        """Get the current state of a command sensor ("fired" or "idle")."""
        return self._command_states.get(command_name, "idle")

    def _create_entities_for_new_alarm(self, alarm_index: int) -> None:
        """Create entities across all platforms for a newly discovered alarm."""
        if alarm_index in self._known_alarm_indices:
            return
        # Skip entity creation for alert-mission alarms — they are ephemeral and
        # should not appear in the HA Alarms device.
        if alarm_index in self._alert_alarm_indices:
            return
        self._known_alarm_indices.add(alarm_index)
        _LOGGER.info("New alarm %d discovered — creating entities", alarm_index)

        for factory, async_add_entities in self._alarm_entity_factories:
            new_entities = factory(self, alarm_index)
            if new_entities:
                async_add_entities(new_entities)

    def is_alarm_removed(self, alarm_index: int) -> bool:
        """Return True if the alarm has been deleted and its entities should stop updating."""
        return alarm_index in self._removed_alarm_indices

    def _remove_alarm_device(self, alarm_index: int) -> None:
        """Remove the HA device (and all its entities) for a deleted alarm.

        Uses the HA-recommended pattern: remove the config entry association
        from the device, which triggers HA to cascade-remove the device and
        all its entities cleanly.
        """
        if alarm_index not in self._known_alarm_indices:
            return
        self._known_alarm_indices.discard(alarm_index)
        self._removed_alarm_indices.add(alarm_index)
        self._per_alarm_states.pop(alarm_index, None)

        # Remove per-alarm button availability state
        self._per_alarm_dismiss_available.pop(alarm_index, None)
        self._per_alarm_snooze_available.pop(alarm_index, None)
        self._per_alarm_skip_available.pop(alarm_index, None)
        self._per_alarm_kill_snoozed_available.pop(alarm_index, None)
        self._per_alarm_unskip_available.pop(alarm_index, None)

        device_reg = dr.async_get(self.hass)
        device_id = (DOMAIN, f"allarise_{self.device_name}_alarm_{alarm_index}")
        device_entry = device_reg.async_get_device(identifiers={device_id})
        if device_entry and self._config_entry_id:
            device_reg.async_update_device(
                device_entry.id,
                remove_config_entry_id=self._config_entry_id,
            )
            _LOGGER.info(
                "Removed HA device for deleted alarm %d", alarm_index
            )
        elif device_entry:
            # Fallback: direct removal if config_entry_id unavailable
            device_reg.async_remove_device(device_entry.id)
            _LOGGER.info(
                "Removed HA device for deleted alarm %d (direct)", alarm_index
            )

    # ─── Public properties ────────────────────────────────────────────

    @property
    def app_online(self) -> bool:
        """Return whether the app is online."""
        return self._app_online

    @property
    def arm_state(self) -> bool:
        """Return the arm state."""
        return self._arm_state

    def get_dashboard_state(self, key: str) -> str:
        """Get a dashboard sensor state."""
        return self._dashboard_states.get(key, "Unknown")

    def get_per_alarm_state(self, alarm_index: int, key: str) -> str:
        """Get a per-alarm sensor state."""
        alarm_states = self._per_alarm_states.get(alarm_index, {})
        default = "Unknown"
        for sensor_key, _, _, sensor_default in PER_ALARM_SENSORS:
            if sensor_key == key:
                default = sensor_default
                break
        return alarm_states.get(key, default)

    def is_alarm_active(self, alarm_index: int) -> bool:
        """Return whether an alarm index is active (exists)."""
        return alarm_index in self._active_alarms

    def is_dismiss_available(self, alarm_index: int | None = None) -> bool:
        """Return whether dismiss is available."""
        if alarm_index is not None:
            return self._per_alarm_dismiss_available.get(alarm_index, False)
        return self._dismiss_available

    def is_snooze_available(self, alarm_index: int | None = None) -> bool:
        """Return whether snooze is available."""
        if alarm_index is not None:
            return self._per_alarm_snooze_available.get(alarm_index, False)
        return self._snooze_available

    def is_skip_available(self, alarm_index: int | None = None) -> bool:
        """Return whether skip is available for a per-alarm button."""
        if alarm_index is not None:
            return self._per_alarm_skip_available.get(alarm_index, False)
        return True

    def is_kill_snoozed_available(self, alarm_index: int | None = None) -> bool:
        """Return whether kill snoozed is available."""
        if alarm_index is not None:
            return self._per_alarm_kill_snoozed_available.get(alarm_index, False)
        return self._kill_snoozed_available

    def is_unskip_available(self, alarm_index: int | None = None) -> bool:
        """Return whether unskip is available for a per-alarm or dashboard button."""
        if alarm_index is not None:
            return self._per_alarm_unskip_available.get(alarm_index, False)
        return self._unskip_available

    def is_quick_alarm_active(self) -> bool:
        """Return True if there is a pending or active quick alarm."""
        state = self.get_dashboard_state("quick_alarm")
        return state not in ("none", "Unknown")

    # ─── MQTT publish helper ──────────────────────────────────────────

    async def async_publish(self, topic: str, payload: str) -> None:
        """Publish a message to an MQTT topic."""
        await mqtt.async_publish(self.hass, topic, payload)

    async def async_publish_command(self, cmd: str, payload: str = "") -> None:
        """Publish a dashboard command."""
        topic = self._topic(TOPIC_COMMAND, cmd=cmd)
        await self.async_publish(topic, payload)

    async def async_publish_alarm_command(
        self, alarm_index: int, cmd: str, payload: str = ""
    ) -> None:
        """Publish a per-alarm command."""
        topic = self._topic(TOPIC_ALARM_COMMAND, index=alarm_index, cmd=cmd)
        await self.async_publish(topic, payload)

    async def async_set_arm_state(self, armed: bool) -> None:
        """Set the arm state — HA is the source of truth.

        Updates the coordinator state immediately (optimistic) and publishes
        the new state retained to arm/state so the iOS app syncs on connect.
        """
        self._arm_state = armed
        self.async_set_updated_data(self._dashboard_states)
        topic = self._topic(TOPIC_ARM_STATE)
        await mqtt.async_publish(self.hass, topic, "ON" if armed else "OFF", retain=True)

    # ─── MQTT setup / teardown ────────────────────────────────────────

    async def async_setup(self) -> None:
        """Subscribe to all MQTT topics for this device."""
        subs = [
            (self._topic(SUB_AVAILABILITY), self._handle_availability_msg),
            (self._topic(SUB_SENSOR_WILDCARD), self._handle_sensor_msg),
            (self._topic(SUB_DASHBOARD_WILDCARD), self._handle_dashboard_msg),
            (self._topic(SUB_ALARM_WILDCARD), self._handle_alarm_msg),
            (self._topic(SUB_ARM_STATE), self._handle_arm_state_msg),
            # arm/command — iOS app sends arm/disarm requests here;
            # HA processes and republishes the authoritative state to arm/state.
            (self._topic(TOPIC_ARM_COMMAND), self._handle_arm_command_msg),
            # command/{name}/status — app publishes "fired"/"idle" for each command
            (self._topic(SUB_COMMAND_STATUS_WILDCARD), self._handle_command_msg),
            (TOPIC_HA_STATUS, self._handle_ha_status_msg),
        ]

        for topic, handler in subs:
            unsub = await mqtt.async_subscribe(self.hass, topic, handler)
            self._unsubs.append(unsub)

        _LOGGER.info(
            "Allarise MQTT subscriptions active for %s (prefix: %s)",
            self.device_name,
            self.topic_prefix,
        )

    async def async_shutdown(self) -> None:
        """Unsubscribe from all MQTT topics."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        _LOGGER.info("Allarise MQTT subscriptions removed for %s", self.device_name)

    # ─── MQTT message handlers ────────────────────────────────────────

    def _set_app_online_from_data(self) -> None:
        """Infer the app is online when any data message is received.

        The explicit availability topic is the primary signal, but if the app
        publishes sensor/dashboard/alarm data the connection is clearly live.
        This handles the case where the availability retained message is missing
        or was not delivered before data messages started arriving.
        """
        if not self._app_online:
            _LOGGER.info(
                "Allarise: inferred app online from data message for %s",
                self.device_name,
            )
            self._app_online = True

    @callback
    def _handle_availability_msg(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle {prefix}/{device}/availability."""
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        was_online = self._app_online
        self._app_online = payload == "online"
        if self._app_online != was_online:
            _LOGGER.info(
                "Allarise availability changed to %s for %s", payload, self.device_name
            )
        else:
            _LOGGER.debug("Allarise availability: %s", payload)

        # When the app goes offline, clear all active alarms.
        # They will be re-created when the app reconnects and
        # republishes per-alarm availability messages.
        if not self._app_online:
            self._active_alarms.clear()

        self.async_set_updated_data(self._dashboard_states)

    @callback
    def _handle_sensor_msg(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle {prefix}/{device}/sensor/{key}."""
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")

        self._set_app_online_from_data()

        # Extract sensor key from topic: …/sensor/{key}
        parts = msg.topic.split("/")
        if len(parts) < 1:
            return
        key = parts[-1]

        # ── Alert-mission suppression ────────────────────────────────────
        # When active_alarm_mission = "alert" arrives, enter suppression mode:
        # revert all active-alarm sensors to their idle defaults so the
        # Dashboard device never reflects an alert as a regular alarm state.
        if key == "active_alarm_mission" and payload == "alert":
            self._alert_active = True
            for sensor_key, _, _, default in DASHBOARD_SENSORS:
                if sensor_key in _ACTIVE_ALARM_SENSOR_KEYS:
                    self._dashboard_states[sensor_key] = default
            self.async_set_updated_data(self._dashboard_states)
            return

        # When alarm_state returns to idle the alert has been dismissed —
        # leave suppression mode and allow the idle update through.
        if key == "alarm_state" and payload == "idle":
            self._alert_active = False

        # While an alert is active, ignore any updates to active-alarm sensors.
        if self._alert_active and key in _ACTIVE_ALARM_SENSOR_KEYS:
            return
        # ─────────────────────────────────────────────────────────────────

        self._dashboard_states[key] = payload

        # Track arm state from sensor too
        if key == "arm_state":
            self._arm_state = payload == "ON"

        self.async_set_updated_data(self._dashboard_states)

    @callback
    def _handle_dashboard_msg(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle {prefix}/{device}/dashboard/{key} — button availability."""
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")

        self._set_app_online_from_data()

        parts = msg.topic.split("/")
        key = parts[-1]  # e.g. "dismiss_availability"
        is_available = payload == "online"

        if key == "dismiss_availability":
            self._dismiss_available = is_available
        elif key == "snooze_availability":
            self._snooze_available = is_available
        elif key == "kill_snoozed_availability":
            self._kill_snoozed_available = is_available
        elif key == "unskip_availability":
            self._unskip_available = is_available

        self.async_set_updated_data(self._dashboard_states)

    @callback
    def _handle_alarm_msg(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle {prefix}/{device}/alarm/{index}/{key_or_sub}.

        Covers: sensor state, availability, button availability.
        Topic structure:
          alarm/{index}/{key}                      → sensor state
          alarm/{index}/availability               → alarm online/offline
          alarm/{index}/{key}_availability          → button availability
          alarm/{index}/command/{name}/status       → command status (ignored)
        """
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")

        # Parse topic: {prefix}/{device}/alarm/{index}/...rest
        parts = msg.topic.split("/")
        try:
            alarm_idx_pos = parts.index("alarm") + 1
            alarm_index = int(parts[alarm_idx_pos])
        except (ValueError, IndexError):
            return

        if alarm_index < 1:
            return

        # Everything after the index
        rest = parts[alarm_idx_pos + 1:]
        if not rest:
            return

        suffix = rest[-1]

        # Per-alarm availability — handle BEFORE the empty-payload guard
        # because an empty payload on this topic means the alarm was deleted
        # (the app publishes retain=true with empty payload to clear it).
        if rest == ["availability"]:
            is_deleted = not payload  # empty payload = retained message cleared
            is_online = payload == "online" if payload else False

            if is_deleted:
                # Alarm was deleted — remove the HA device and all entities
                self._active_alarms.discard(alarm_index)
                self._remove_alarm_device(alarm_index)
            elif is_online:
                # Only trust per-alarm availability when the app is confirmed
                # online.  When the coordinator first subscribes, the broker
                # delivers stale retained "online" messages for alarms that
                # were deleted before the cleanup fix.  The device-level
                # availability topic tells us the app is actually running;
                # until that arrives, ignore per-alarm availability.
                if not self._app_online:
                    _LOGGER.debug(
                        "Ignoring retained availability for alarm %d "
                        "(app not online yet)",
                        alarm_index,
                    )
                    return
                # Skip alert-mission alarms entirely — no per-alarm HA entities.
                if alarm_index in self._alert_alarm_indices:
                    return
                self._active_alarms.add(alarm_index)
                if alarm_index not in self._per_alarm_states:
                    self._per_alarm_states[alarm_index] = {}
                # Dynamically create entities for this alarm if new
                self._create_entities_for_new_alarm(alarm_index)
            else:
                # "offline" payload — alarm temporarily unavailable
                self._active_alarms.discard(alarm_index)
            self.async_set_updated_data(self._dashboard_states)
            return

        # Ignore empty payloads for all other topics — these are
        # retained-message deletions and carry no useful state.
        if not payload:
            return

        # Per-alarm button availability (e.g. dismiss_availability)
        if suffix.endswith("_availability"):
            is_avail = payload == "online"
            base = suffix.removesuffix("_availability")
            if base == "dismiss":
                self._per_alarm_dismiss_available[alarm_index] = is_avail
            elif base == "snooze":
                self._per_alarm_snooze_available[alarm_index] = is_avail
            elif base == "skip":
                self._per_alarm_skip_available[alarm_index] = is_avail
            elif base == "kill_snoozed":
                self._per_alarm_kill_snoozed_available[alarm_index] = is_avail
            elif base == "unskip":
                self._per_alarm_unskip_available[alarm_index] = is_avail
            self.async_set_updated_data(self._dashboard_states)
            return

        # Command status: alarm/{index}/command/{name}/status → ignore
        if len(rest) >= 2 and rest[0] == "command":
            return

        # Normal per-alarm sensor: alarm/{index}/{key}
        # Only store data for alarms that are already active (availability=online).
        # Stale retained MQTT data from deleted alarms is silently ignored.
        if len(rest) == 1:
            key = rest[0]
            # Actual sensor data confirms the app is live (not stale availability).
            self._set_app_online_from_data()
            if alarm_index not in self._active_alarms:
                return
            if alarm_index not in self._per_alarm_states:
                self._per_alarm_states[alarm_index] = {}
            self._per_alarm_states[alarm_index][key] = payload

            # If this alarm's mission turns out to be "alert", remove any
            # per-alarm HA entities that were created before the mission data arrived.
            if key == "mission" and payload == "alert":
                self._alert_alarm_indices.add(alarm_index)
                self._active_alarms.discard(alarm_index)
                self._remove_alarm_device(alarm_index)
                _LOGGER.debug(
                    "Alert-mission alarm %d detected — per-alarm entities removed",
                    alarm_index,
                )
                self.async_set_updated_data(self._dashboard_states)
                return

            self.async_set_updated_data(self._dashboard_states)

    @callback
    def _handle_command_msg(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle {prefix}/{device}/command/{name}/status — command fired/idle.

        Dynamically creates a Dashboard sensor entity the first time each
        command name is seen, then updates its state to "fired" or "idle".
        """
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        payload = payload.strip().lower()

        # Extract command name from topic: …/command/{name}/status
        parts = msg.topic.split("/")
        # Expect: prefix / device / command / {name} / status
        try:
            cmd_idx = parts.index("command") + 1
            command_name = parts[cmd_idx]
        except (ValueError, IndexError):
            return

        if not command_name or command_name == "status":
            return

        self._command_states[command_name] = payload

        # Create entities for this command if we haven't seen it before
        self._create_entities_for_new_command(command_name)

        self.async_set_updated_data(self._dashboard_states)

    @callback
    def _handle_arm_state_msg(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle {prefix}/alarm/{zone}/state — HA's own retained publish arriving back.

        This fires on the coordinator's own initial subscription delivery.
        We update internal state so the switch entity reflects the broker's
        retained value on integration startup.
        """
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        if payload in ("ON", "OFF"):
            self._arm_state = payload == "ON"
            self.async_set_updated_data(self._dashboard_states)

    @callback
    def _handle_arm_command_msg(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle {prefix}/alarm/{zone}/set — arm request FROM the iOS app.

        HA is the source of truth. When the app requests a change, we honour it,
        update the HA entity, and re-publish the authoritative retained state to
        alarm/{zone}/state so every subscriber (including the app) receives the confirmation.
        """
        payload = msg.payload
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        payload = payload.strip()
        if payload not in ("ON", "OFF"):
            _LOGGER.warning("Unexpected arm/command payload: %r — ignoring", payload)
            return
        armed = payload == "ON"
        _LOGGER.debug("Arm command from app: %s", payload)
        self._arm_state = armed
        self.async_set_updated_data(self._dashboard_states)
        # Re-publish authoritative retained state so the app and any other
        # subscriber gets the confirmed value back immediately.
        self.hass.async_create_task(
            mqtt.async_publish(
                self.hass,
                self._topic(TOPIC_ARM_STATE),
                "ON" if armed else "OFF",
                retain=True,
            )
        )

    @callback
    def _handle_ha_status_msg(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle homeassistant/status — HA just came online.

        Re-publish the current arm state retained so that any iOS app instance
        that was connected before HA restarted re-syncs immediately.
        """
        _LOGGER.debug("HA status: %s", msg.payload)
        self.hass.async_create_task(
            mqtt.async_publish(
                self.hass,
                self._topic(TOPIC_ARM_STATE),
                "ON" if self._arm_state else "OFF",
                retain=True,
            )
        )

    # ─── DataUpdateCoordinator override ───────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """No polling — all data comes via MQTT."""
        return self._dashboard_states
