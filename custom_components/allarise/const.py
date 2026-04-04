"""Constants for the Allarise Alarm integration."""

DOMAIN = "allarise"
PLATFORMS = ["sensor", "binary_sensor", "button", "switch", "media_player", "number", "select"]

# Config keys
CONF_DEVICE_NAME = "device_name"
CONF_TOPIC_PREFIX = "topic_prefix"
CONF_ZONE_SLUG = "zone_slug"

DEFAULT_DEVICE_NAME = "iPhone"
DEFAULT_TOPIC_PREFIX = "allarise"
DEFAULT_ZONE_SLUG = "home"

# ─── MQTT topic templates ────────────────────────────────────────────
# {prefix} = user-configured topic prefix (default "allarise")
# {device}  = sanitised device name (lowercase, no special chars)

# Availability
TOPIC_AVAILABILITY = "{prefix}/{device}/availability"

# Dashboard sensor state  →  {prefix}/{device}/sensor/{key}
TOPIC_SENSOR = "{prefix}/{device}/sensor/{key}"

# Dashboard button availability  →  {prefix}/{device}/dashboard/{key}
TOPIC_DASHBOARD_AVAIL = "{prefix}/{device}/dashboard/{key}"

# Per-alarm sensor state  →  {prefix}/{device}/alarm/{index}/{key}
TOPIC_ALARM_SENSOR = "{prefix}/{device}/alarm/{index}/{key}"

# Per-alarm availability
TOPIC_ALARM_AVAILABILITY = "{prefix}/{device}/alarm/{index}/availability"

# Per-alarm button availability  →  {prefix}/{device}/alarm/{index}/{key}
TOPIC_ALARM_BUTTON_AVAIL = "{prefix}/{device}/alarm/{index}/{key}"

# Arm state — zone-based, shared across devices in the same zone
# {zone} = armZoneSlug from the iOS app (e.g. "home", "my_zone")
# No {device} — multiple phones with the same zone name share this topic.
TOPIC_ARM_STATE = "{prefix}/alarm/{zone}/state"

# ─── Command topics (integration publishes TO these) ─────────────────
TOPIC_COMMAND = "{prefix}/{device}/command/{cmd}"
TOPIC_ALARM_COMMAND = "{prefix}/{device}/alarm/{index}/command/{cmd}"
TOPIC_ARM_COMMAND = "{prefix}/alarm/{zone}/set"

# ─── Wildcard subscription topics (coordinator subscribes) ───────────
SUB_SENSOR_WILDCARD = "{prefix}/{device}/sensor/#"
SUB_DASHBOARD_WILDCARD = "{prefix}/{device}/dashboard/#"
SUB_ALARM_WILDCARD = "{prefix}/{device}/alarm/+/#"
SUB_AVAILABILITY = "{prefix}/{device}/availability"
SUB_ARM_STATE = "{prefix}/alarm/{zone}/state"
# Command status — app publishes {name}/status = fired|idle for each fired command
SUB_COMMAND_STATUS_WILDCARD = "{prefix}/{device}/command/+/status"

# Home Assistant birth topic
TOPIC_HA_STATUS = "homeassistant/status"

# Dashboard sensor definitions grouped by type: (key, name_suffix, icon, default_value)
# All "Alarm *" sensors are queue-based: they reflect the ringing alarm when active,
# or the next upcoming alarm when idle.
DASHBOARD_SENSORS = [
    # ── Alarm State ────────────────────────────────────────────────────
    ("alarm_state", "Alarm State", "mdi:alarm-check", "idle"),
    ("active_alarm_name", "Alarm Name", "mdi:label", "None"),
    ("active_alarm_mission", "Alarm Mission", "mdi:target", "None"),
    ("active_alarm_fire_time", "Alarm Fire Time", "mdi:calendar-clock", "None"),
    ("active_alarm_snooze_fire_time", "Alarm Snooze Fire Time", "mdi:clock-alert", "None"),
    # ── Alarm Sound & Hardware ─────────────────────────────────────────
    ("alarm_sound", "Alarm Sound", "mdi:music-note", "Unknown"),
    ("alarm_volume", "Alarm Volume", "mdi:volume-high", "0%"),
    ("alarm_vibrate", "Alarm Vibrate", "mdi:vibrate", "off"),
    ("alarm_fade_in", "Alarm Fade In", "mdi:sunrise", "Off"),
    # ── Alarm Details ──────────────────────────────────────────────────
    ("alarm_notes", "Alarm Notes", "mdi:note-text", ""),
    ("active_alarm_index", "Alarm ID", "mdi:identifier", "-1"),
    # ── Snooze ─────────────────────────────────────────────────────────
    ("snooze_count", "Alarm Snooze Count", "mdi:sleep", "0"),
    ("snoozes_remaining", "Snoozes Remaining", "mdi:sleep", "0"),
    # ── Alarm Counts ───────────────────────────────────────────────────
    ("enabled_alarm_count", "Alarm Count", "mdi:alarm-multiple", "0"),
    # ── App & Connection ───────────────────────────────────────────────
    ("broker_connection", "Broker Connection", "mdi:server-network", "Unknown"),
    ("app_version", "App Version", "mdi:cellphone-arrow-down", "Unknown"),
    ("media_alert_volume", "Alert Volume", "mdi:volume-medium", "75"),
    # ── Alert Configuration ────────────────────────────────────────────
    ("alert_sound", "Alert Sound", "mdi:bell-alert", "Default"),
    ("alert_vibrate", "Alert Vibrate", "mdi:vibrate", "on"),
    ("alert_loop_media", "Alert Loop Media", "mdi:repeat", "off"),
    ("alert_loop_delay", "Alert Loop Delay", "mdi:timer-outline", "0"),
    # ── Quick Alarm ────────────────────────────────────────────────────
    ("quick_alarm", "Quick Alarm", "mdi:timer-alert", "none"),
    ("quick_alarm_fire_time", "Quick Alarm Fire Time", "mdi:timer-sand", "none"),
    ("quick_alarm_label", "Quick Alarm Label", "mdi:label", "none"),
    ("quick_alarm_count", "Quick Alarm Count", "mdi:counter", "0"),
    # ── Sleep Sounds ───────────────────────────────────────────────────
    ("sleep_sound_volume", "Sleep Sound Volume", "mdi:volume-high", "0"),
    # ── Arm Widget Commands ────────────────────────────────────────────
    ("arm_custom_command", "Last Command Fired", "mdi:console", "None"),
]

# Per-alarm sensor definitions: (key, name_suffix, icon, default_value)
PER_ALARM_SENSORS = [
    ("name", "Name", "mdi:label", "Unknown"),
    ("enabled", "Enabled", "mdi:alarm-check", "off"),
    ("state", "State", "mdi:bell-ring", "idle"),
    ("fire_time", "Fire Time", "mdi:calendar-clock", "None"),
    ("snooze_fire_time", "Snooze Fire Time", "mdi:clock-alert", "None"),
    ("days", "Days", "mdi:calendar-week", "None"),
    ("mission", "Mission", "mdi:target", "None"),
    ("sound", "Sound", "mdi:music-note", "Unknown"),
    ("snoozes", "Snoozes", "mdi:sleep", "0"),
    ("volume", "Volume", "mdi:volume-high", "0%"),
    ("vibrate", "Vibrate", "mdi:vibrate", "off"),
    ("fade_in", "Fade In", "mdi:sunrise", "Off"),
    ("notes", "Notes", "mdi:note-text", ""),
    ("sort_order", "Sort Order", "mdi:sort-numeric-ascending", "0"),
    ("commands", "Commands", "mdi:console", "None"),
    ("swipe_left_command", "Swipe Left Command", "mdi:gesture-swipe-left", "None"),
    ("swipe_right_command", "Swipe Right Command", "mdi:gesture-swipe-right", "None"),
    ("widget_command_1", "Widget Command 1", "mdi:numeric-1-box", "None"),
    ("widget_command_2", "Widget Command 2", "mdi:numeric-2-box", "None"),
    ("widget_command_3", "Widget Command 3", "mdi:numeric-3-box", "None"),
    ("widget_command_4", "Widget Command 4", "mdi:numeric-4-box", "None"),
]

# Dashboard button definitions: (key, name_suffix, icon)
DASHBOARD_BUTTONS = [
    ("dismiss", "Dismiss Alarm", "mdi:alarm-off"),
    ("snooze", "Snooze Alarm", "mdi:alarm-snooze"),
    ("skip", "Skip Alarm", "mdi:skip-next"),
    ("unskip", "Unskip Alarm", "mdi:skip-previous"),
    ("delete_next_alarm", "Delete Next Alarm", "mdi:delete-forever"),
    ("kill_snoozed", "Kill Snoozed Alarm", "mdi:alarm-off"),
    ("sleep_sound_stop", "Sleep Sound Stop", "mdi:stop"),
    ("sleep_sound_pause", "Sleep Sound Pause", "mdi:pause"),
    ("sleep_sound_resume", "Sleep Sound Resume", "mdi:play"),
]

# Quick alarm button definitions: (key, name_suffix, icon)
# Quick alarms are one-time ephemeral alarms — only dismiss (when ringing) and delete are relevant.
QUICK_ALARM_BUTTONS = [
    ("dismiss", "Dismiss Alarm", "mdi:alarm-off"),
    ("delete_quick_alarm", "Delete Quick Alarm", "mdi:trash-can"),
]

# Per-alarm button definitions: (key, name_suffix, icon)
PER_ALARM_BUTTONS = [
    ("dismiss", "Dismiss", "mdi:alarm-off"),
    ("snooze", "Snooze", "mdi:alarm-snooze"),
    ("skip", "Skip", "mdi:skip-next"),
    ("unskip", "Unskip", "mdi:skip-previous"),
    ("kill_snoozed", "Kill Snoozed", "mdi:alarm-off"),
    ("delete", "Delete", "mdi:delete"),
]

# Text entity definitions: (key, name_suffix, icon)
# (currently empty — update_alarm removed)
TEXT_ENTITIES: list = []
