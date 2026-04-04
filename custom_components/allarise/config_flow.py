"""Config flow for Allarise Alarm integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_DEVICE_NAME,
    CONF_TOPIC_PREFIX,
    CONF_ZONE_SLUG,
    DEFAULT_DEVICE_NAME,
    DEFAULT_TOPIC_PREFIX,
    DEFAULT_ZONE_SLUG,
    DOMAIN,
)
from .coordinator import AllariseCoordinator


class AllariseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Allarise Alarm."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — collect device name and topic prefix."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_name = user_input[CONF_DEVICE_NAME]
            topic_prefix = user_input.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX)
            zone_slug = user_input.get(CONF_ZONE_SLUG, DEFAULT_ZONE_SLUG)

            # Check for duplicate device names
            await self.async_set_unique_id(f"allarise_{device_name}")
            self._abort_if_unique_id_configured()

            # Validate MQTT is available
            if not self.hass.config_entries.async_entries("mqtt"):
                errors["base"] = "mqtt_not_configured"
            else:
                return self.async_create_entry(
                    title=f"Allarise - {device_name}",
                    data={
                        CONF_DEVICE_NAME: device_name,
                        CONF_TOPIC_PREFIX: topic_prefix,
                        CONF_ZONE_SLUG: zone_slug,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE_NAME, default=DEFAULT_DEVICE_NAME
                    ): str,
                    vol.Optional(
                        CONF_TOPIC_PREFIX, default=DEFAULT_TOPIC_PREFIX
                    ): str,
                    vol.Optional(
                        CONF_ZONE_SLUG, default=DEFAULT_ZONE_SLUG
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "docs_url": "https://allarise.app/docs/hass-api"
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return AllariseOptionsFlow(config_entry)


class AllariseOptionsFlow(OptionsFlow):
    """Handle options for Allarise — lets users view their config."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show integration options."""
        if user_input is not None:
            return self.async_create_entry(data={})

        device_name = self._config_entry.data.get(CONF_DEVICE_NAME, "Unknown")
        topic_prefix = self._config_entry.data.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX)
        zone_slug = self._config_entry.data.get(CONF_ZONE_SLUG, DEFAULT_ZONE_SLUG)
        sanitized = AllariseCoordinator.sanitize_device_name(device_name)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
            description_placeholders={
                "device_name": device_name,
                "topic_prefix": topic_prefix,
                "zone_slug": zone_slug,
                "mqtt_topic": f"{topic_prefix}/{sanitized}/#",
                "arm_topic": f"{topic_prefix}/alarm/{zone_slug}/state",
            },
        )
