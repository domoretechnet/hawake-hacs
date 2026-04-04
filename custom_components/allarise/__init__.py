"""The Allarise Alarm integration — MQTT-based."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import media_source
from homeassistant.components.media_player import async_process_play_media_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_DEVICE_NAME,
    CONF_TOPIC_PREFIX,
    CONF_ZONE_SLUG,
    DEFAULT_TOPIC_PREFIX,
    DEFAULT_ZONE_SLUG,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import AllariseCoordinator

_LOGGER = logging.getLogger(__name__)

type AllariseConfigEntry = ConfigEntry[AllariseCoordinator]

# ─── Service schemas ──────────────────────────────────────────────────

SERVICE_UPDATE_ALARM = "update_alarm"
SERVICE_TRIGGER_ALERT = "trigger_alert"
SERVICE_DISMISS = "dismiss"
SERVICE_SNOOZE = "snooze"
SERVICE_SKIP = "skip"

ATTR_DEVICE_NAME = "device_name"

SCHEMA_UPDATE_ALARM = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_NAME): cv.string,
        vol.Required("index"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("time"): cv.string,
        vol.Optional("label"): cv.string,
        vol.Optional("enabled"): cv.boolean,
        vol.Optional("days"): cv.string,
        vol.Optional("sound"): cv.string,
        vol.Optional("volume"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("vibrate"): cv.boolean,
        vol.Optional("fade_in"): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
        vol.Optional("snooze_limit"): vol.All(vol.Coerce(int), vol.Range(min=0, max=99)),
        vol.Optional("snooze_interval"): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
        vol.Optional("mission"): cv.string,
        vol.Optional("notes"): cv.string,
    }
)

SCHEMA_TRIGGER_ALERT = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_NAME): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("sound"): cv.string,
        vol.Optional("volume"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("media_url"): cv.string,
        vol.Optional("image_url"): cv.string,
        vol.Optional("video_url"): cv.string,
        vol.Optional("link_url"): cv.string,
    }
)

SCHEMA_SIMPLE = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_NAME): cv.string,
    }
)

def _find_coordinator(
    hass: HomeAssistant, device_name: str | None
) -> AllariseCoordinator | None:
    """Find the coordinator for a given device name.

    If device_name is None or empty, auto-resolves to the only configured
    entry when exactly one exists. Useful when only one Allarise device is set up.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not device_name:
        if len(entries) == 1:
            return entries[0].runtime_data
        _LOGGER.error(
            "device_name is required when multiple Allarise devices are configured "
            "(found %d). Available: %s",
            len(entries),
            [e.data.get(CONF_DEVICE_NAME) for e in entries],
        )
        return None
    for entry in entries:
        if entry.data.get(CONF_DEVICE_NAME) == device_name:
            return entry.runtime_data
    return None


def _build_payload(call: ServiceCall, exclude: set[str] | None = None) -> str:
    """Build a JSON payload from service call data, excluding specified keys."""
    exclude = (exclude or set()) | {ATTR_DEVICE_NAME}
    data = {k: v for k, v in call.data.items() if k not in exclude}
    return json.dumps(data)


async def async_setup_entry(hass: HomeAssistant, entry: AllariseConfigEntry) -> bool:
    """Set up Allarise Alarm from a config entry."""
    device_name = entry.data[CONF_DEVICE_NAME]
    topic_prefix = entry.data.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX)
    zone_slug = entry.data.get(CONF_ZONE_SLUG, DEFAULT_ZONE_SLUG)

    coordinator = AllariseCoordinator(
        hass,
        device_name=device_name,
        topic_prefix=topic_prefix,
        config_entry_id=entry.entry_id,
        zone_slug=zone_slug,
    )

    # Store coordinator in entry runtime data
    entry.runtime_data = coordinator

    # Start MQTT subscriptions
    await coordinator.async_setup()

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register custom services (once per domain)
    if not hass.services.has_service(DOMAIN, SERVICE_UPDATE_ALARM):
        _register_services(hass)

    _LOGGER.info("Allarise integration set up for %s (MQTT prefix: %s, zone: %s)", device_name, topic_prefix, zone_slug)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AllariseConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: AllariseCoordinator = entry.runtime_data
    await coordinator.async_shutdown()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Unregister services and frontend panel if no more entries
    if not hass.config_entries.async_entries(DOMAIN):
        for service in (
            SERVICE_UPDATE_ALARM,
            SERVICE_TRIGGER_ALERT,
            SERVICE_DISMISS,
            SERVICE_SNOOZE,
            SERVICE_SKIP,
        ):
            hass.services.async_remove(DOMAIN, service)

    return unloaded


def _register_services(hass: HomeAssistant) -> None:
    """Register all Allarise custom services."""

    async def handle_update_alarm(call: ServiceCall) -> None:
        coordinator = _find_coordinator(hass, call.data.get(ATTR_DEVICE_NAME))
        if coordinator is None:
            _LOGGER.error("Device not found: %s", call.data.get(ATTR_DEVICE_NAME))
            return
        payload = _build_payload(call)
        await coordinator.async_publish_command("update_alarm", payload)

    async def handle_trigger_alert(call: ServiceCall) -> None:
        coordinator = _find_coordinator(hass, call.data.get(ATTR_DEVICE_NAME))
        if coordinator is None:
            _LOGGER.error("Device not found: %s", call.data.get(ATTR_DEVICE_NAME))
            return
        # Build payload and sign any local HA URLs so the phone can fetch them
        # remotely via HA's reverse proxy (same approach as sgtbatten blueprint).
        data = {k: v for k, v in call.data.items() if k != ATTR_DEVICE_NAME}
        if "media_url" in data:
            url = data["media_url"]
            if media_source.is_media_source_id(url):
                play_item = await media_source.async_resolve_media(hass, url, None)
                url = play_item.url
            data["media_url"] = async_process_play_media_url(hass, url)
        for key in ("image_url", "video_url"):
            if key in data:
                data[key] = async_process_play_media_url(hass, data[key])
        payload = json.dumps(data)
        await coordinator.async_publish_command("alert", payload)

    async def handle_dismiss(call: ServiceCall) -> None:
        coordinator = _find_coordinator(hass, call.data.get(ATTR_DEVICE_NAME))
        if coordinator is None:
            _LOGGER.error("Device not found: %s", call.data.get(ATTR_DEVICE_NAME))
            return
        await coordinator.async_publish_command("dismiss")

    async def handle_snooze(call: ServiceCall) -> None:
        coordinator = _find_coordinator(hass, call.data.get(ATTR_DEVICE_NAME))
        if coordinator is None:
            _LOGGER.error("Device not found: %s", call.data.get(ATTR_DEVICE_NAME))
            return
        await coordinator.async_publish_command("snooze")

    async def handle_skip(call: ServiceCall) -> None:
        coordinator = _find_coordinator(hass, call.data.get(ATTR_DEVICE_NAME))
        if coordinator is None:
            _LOGGER.error("Device not found: %s", call.data.get(ATTR_DEVICE_NAME))
            return
        await coordinator.async_publish_command("skip")

    hass.services.async_register(DOMAIN, SERVICE_UPDATE_ALARM, handle_update_alarm, schema=SCHEMA_UPDATE_ALARM)
    hass.services.async_register(DOMAIN, SERVICE_TRIGGER_ALERT, handle_trigger_alert, schema=SCHEMA_TRIGGER_ALERT)
    hass.services.async_register(DOMAIN, SERVICE_DISMISS, handle_dismiss, schema=SCHEMA_SIMPLE)
    hass.services.async_register(DOMAIN, SERVICE_SNOOZE, handle_snooze, schema=SCHEMA_SIMPLE)
    hass.services.async_register(DOMAIN, SERVICE_SKIP, handle_skip, schema=SCHEMA_SIMPLE)
