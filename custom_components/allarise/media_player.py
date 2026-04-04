"""Media player platform for Allarise Alarm integration.

Allows HA to call media_player.play_media to trigger an alert on the phone
with audio playback. Supports PLAY_MEDIA, MEDIA_ANNOUNCE, and VOLUME_SET.

Volume can be set via media_player.volume_set (0.0–1.0) before calling
play_media. It will be included in the alert payload automatically.

The volume_level is synced with the iOS app's `mediaAlertVolume` setting:
- Setting it here publishes a `set_media_alert_volume` MQTT command to the app.
- The app publishes changes back via the `media_alert_volume` sensor topic.
"""

from __future__ import annotations

import json
import logging

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AllariseCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[AllariseCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Allarise media player."""
    coordinator = entry.runtime_data
    async_add_entities([AllariseMediaPlayer(coordinator)])


class AllariseMediaPlayer(CoordinatorEntity[AllariseCoordinator], MediaPlayerEntity):
    """Media player entity for sending audio alerts to Allarise."""

    _attr_has_entity_name = True
    _attr_name = "Alert Media"
    _attr_icon = "mdi:speaker-wireless"
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.BROWSE_MEDIA
    )
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, coordinator: AllariseCoordinator) -> None:
        """Initialize the media player."""
        super().__init__(coordinator)
        self._attr_unique_id = f"allarise_{coordinator.device_name}_media_player"
        # Initialize volume from coordinator sensor, fallback 0.75
        self._sync_volume_from_coordinator()

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
    def state(self) -> MediaPlayerState:
        """Return the state — idle when online, off when offline."""
        if self.coordinator.app_online:
            return MediaPlayerState.IDLE
        return MediaPlayerState.OFF

    @property
    def available(self) -> bool:
        """Return True if the app is online."""
        return self.coordinator.app_online

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level (0.0–1.0).

        Publishes a `set_media_alert_volume` MQTT command to the iOS app,
        which updates the app's `mediaAlertVolume` setting.
        """
        self._attr_volume_level = volume
        self.async_write_ha_state()

        # Publish command to iOS app
        payload = json.dumps({"volume": volume})
        await self.coordinator.async_publish_command(
            "set_media_alert_volume", payload
        )

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Return a BrowseMedia instance for HA's media browser."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
        )

    async def async_play_media(
        self,
        media_type: MediaType | str,
        media_id: str,
        **kwargs,
    ) -> None:
        """Play media — sends an alert command with media_url to the phone.

        The iOS app will show a full-screen alert and play the audio.
        Extra keys (title, message, sound, image_url) can be passed via `extra`.

        The volume is taken from the entity's current volume_level (set via
        media_player.volume_set) unless overridden in `extra`.

        Handles three kinds of media_id:
        1. media-source:// URIs — resolved via HA's media_source component
        2. Local HA paths (/api/tts_proxy/...) — signed so the phone can
           fetch them without a Bearer token
        3. External URLs — passed through unchanged
        """
        extra = kwargs.get("extra") or {}

        # Resolve media-source:// URIs to actual paths
        if media_source.is_media_source_id(media_id):
            play_item = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            media_id = play_item.url

        # Sign local HA URLs (adds authSig query param) and convert
        # relative paths to absolute URLs so the phone can reach them.
        media_id = async_process_play_media_url(self.hass, media_id)
        _LOGGER.debug("Resolved media URL: %s", media_id)

        payload: dict = {
            "message": extra.get("message", "Media playback"),
            "media_url": media_id,
        }

        if "title" in extra:
            payload["title"] = extra["title"]
        if "sound" in extra:
            payload["sound"] = extra["sound"]
        if "image_url" in extra:
            payload["image_url"] = async_process_play_media_url(self.hass, extra["image_url"])

        # Volume: use explicit extra override, else the entity's volume_level.
        # Send as 0.0–1.0 float — the iOS app normalizes internally.
        if "volume" in extra:
            payload["volume"] = float(extra["volume"])
        elif self._attr_volume_level is not None:
            payload["volume"] = self._attr_volume_level

        await self.coordinator.async_publish_command(
            "alert", json.dumps(payload)
        )

    def _sync_volume_from_coordinator(self) -> None:
        """Sync volume_level from the coordinator's media_alert_volume sensor."""
        raw = self.coordinator.get_dashboard_state("media_alert_volume")
        if raw not in ("Unknown", ""):
            try:
                pct = int(raw)
                self._attr_volume_level = pct / 100.0
            except (ValueError, TypeError):
                self._attr_volume_level = 0.75
        else:
            self._attr_volume_level = 0.75

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._sync_volume_from_coordinator()
        self.async_write_ha_state()
