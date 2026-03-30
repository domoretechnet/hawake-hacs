# HaWake Alarm — Home Assistant Integration

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Min Version](https://img.shields.io/badge/HA-2024.1%2B-blue.svg)](https://www.home-assistant.io)

Control and monitor the **HaWake Alarm** iOS app from Home Assistant. Dismiss alarms, snooze, send full-screen alerts to your phone, automate alarm schedules, and expose alarm state as sensors — all over MQTT.

---

## Requirements

- [HaWake Alarm](https://apps.apple.com/app/hawake-alarm/id0000000000) iOS app (v2.0+)
- A running MQTT broker (e.g. Mosquitto via the HA add-on)
- The MQTT integration configured in Home Assistant
- The HaWake app connected to the same MQTT broker

---

## MQTT Broker Setup

This section covers creating a dedicated MQTT user for the HaWake app and locking it down to only the topics it needs.

### 1 — Create a dedicated user in the Mosquitto add-on

Open **Settings → Add-ons → Mosquitto broker → Configuration** and add a login under the `logins` key:

```yaml
logins:
  - username: hawake
    password: "your_secure_password"
customize:
  active: true
  folder: mosquitto
```

Using a dedicated user (rather than your HA admin account) keeps the app isolated — it can only see HaWake topics and nothing else in your broker.

Save and restart the Mosquitto add-on.

### 2 — Create the ACL file

With `customize.active: true` set above, Mosquitto loads any `.conf` files from the `/share/mosquitto/` folder.

Create the file `/share/mosquitto/hawake_acl.conf` — the easiest way is via the **File editor** add-on or SSH:

```
# HaWake iOS app — restrict to HaWake topics only

user hawake
topic readwrite hawake/#
```

This gives the `hawake` user read/write access to every topic under your configured prefix (default `hawake/`), which covers:

| Access | Topics |
|---|---|
| **Publish** (app → broker) | `hawake/{device}/sensor/…` · `hawake/{device}/alarm/…` · `hawake/{device}/availability` · `hawake/{device}/arm/state` |
| **Subscribe** (app listens) | `hawake/{device}/command/…` · `hawake/{device}/alarm/…/command/…` · `hawake/{device}/arm/command` |

If you use a custom topic prefix in the app (e.g. `myhome`), replace `hawake/#` with `myhome/#`.

Restart the Mosquitto add-on again to apply the ACL.

### 3 — Connect the HaWake app

In the HaWake iOS app, go to **Settings → MQTT Settings** and enter:

- **Host** — your Home Assistant IP or hostname
- **Port** — `1883` (or `8883` for TLS)
- **Username** — `hawake`
- **Password** — the password you set above

The HA MQTT integration itself uses a separate system account that already has broader broker access — you do not need to modify its credentials.

---

## Installation

### Via HACS (recommended)

1. In Home Assistant, go to **HACS → Integrations → ⋮ → Custom repositories**
2. Add this repository URL and select **Integration** as the category
3. Find **HaWake Alarm** in the HACS store and click **Download**
4. Restart Home Assistant

### Manual

1. Copy `custom_components/hawake/` into your HA `config/custom_components/` directory
2. Restart Home Assistant

---

## Configuration

1. Open **Settings → Devices & Services → Add Integration**
2. Search for **HaWake Alarm**
3. Enter the **Device Name** and **MQTT Topic Prefix** — these must exactly match what is set in the HaWake iOS app under **Settings → MQTT Settings**

> Default values: Device Name = `iPhone`, Topic Prefix = `hawake`

You can add multiple devices (one entry per iPhone).

---

## Entities

### Sensors (Dashboard)

| Sensor | Description |
|---|---|
| Alarm State | `idle` / `ringing` / `snoozed` / `dismissed` |
| Alarm Name | Name of the currently ringing or next upcoming alarm |
| Alarm Mission | Mission type required to dismiss (shake, math, HA, none) |
| Alarm Fire Time | Scheduled fire time of the active or next alarm |
| Alarm Snooze Fire Time | When a snoozed alarm will re-fire |
| Alarm Sound | Sound ID playing for the active alarm |
| Alarm Volume | Volume % for the active alarm |
| Alarm Vibrate | Whether vibration is enabled |
| Alarm Fade In | Whether fade-in is active |
| Alarm Notes | Notes attached to the active alarm |
| Alarm ID | MQTT index of the active alarm |
| Alarm Snooze Count | Number of times the current alarm has been snoozed |
| Snoozes Remaining | Snoozes left before alarm is force-dismissed |
| Alarm Count | Number of active (enabled) alarms |
| App Version | HaWake app version string |
| Broker Connection | MQTT connection state reported by the app |
| Alert Volume | Volume used for HA-triggered alert alarms (%) |
| Alert Sound | Default sound for HA alert alarms |
| Alert Vibrate | Whether HA alert alarms vibrate |
| Alert Loop Media | Whether media audio loops during HA alerts |
| Alert Loop Delay | Seconds between media audio loops |
| Quick Alarm | Active quick alarm state |
| Quick Alarm Fire Time | When the quick alarm fires |
| Quick Alarm Label | Label of the quick alarm |
| Quick Alarm Count | Number of active quick alarms |
| Sleep Sound Volume | Current sleep sounds volume (%) |

### Binary Sensor

| Sensor | Description |
|---|---|
| App Online | `on` when the iOS app is connected to the broker |

### Per-Alarm Sensors

For each alarm you create in the app, a dedicated HA device is created containing:

`Name` · `Enabled` · `State` · `Fire Time` · `Snooze Fire Time` · `Days` · `Mission` · `Sound` · `Snoozes` · `Volume` · `Vibrate` · `Fade In` · `Notes` · `Sort Order` · `Commands` · `Swipe Left/Right Commands`

### Buttons

**Dashboard buttons** (act on the currently active alarm):

| Button | Action |
|---|---|
| Dismiss Alarm | Dismiss the ringing/snoozed alarm |
| Snooze Alarm | Snooze the ringing alarm |
| Skip Alarm | Skip the next upcoming fire for the active alarm |
| Unskip Alarm | Remove the skip flag from the next alarm |
| Delete Next Alarm | Delete the next alarm in the queue |
| Kill Snoozed Alarm | Immediately end a snoozed alarm session |
| Sleep Sound Stop / Pause / Resume | Control sleep sounds |

**Per-alarm buttons** (on each alarm's device):

`Dismiss` · `Snooze` · `Skip` · `Unskip` · `Kill Snoozed` · `Delete`

### Switches

| Switch | Description |
|---|---|
| Arm | Master arm/disarm toggle (HA is source of truth) |
| Alarm N — Enabled | Enable or disable a specific alarm |
| Alert Vibrate | Toggle vibration for HA alert alarms |
| Alert Loop Media | Toggle media looping for HA alert alarms |

### Media Player

The integration exposes a **media player** entity that lets you play audio or TTS to the phone. Supports `media_player.play_media`, `media_player.media_announce`, and `media_player.volume_set`.

```yaml
service: media_player.play_media
target:
  entity_id: media_player.hawake_iphone
data:
  media_content_id: media-source://tts/cloud?message=Good+morning
  media_content_type: music
```

### Notify

Send a full-screen alert to the phone using the standard HA notify service:

```yaml
service: notify.hawake_iphone
data:
  title: "Door Alert"
  message: "Front door opened"
  data:
    sound: "Perimeter_Breach"
    volume: 0.8
    media_url: "http://your-ha.local:8123/local/doorbell.mp3"
```

---

## Services

### `hawake.update_alarm`

Modify an alarm by index or name.

```yaml
service: hawake.update_alarm
data:
  device_name: iPhone        # optional if only one device
  name: "Work Alarm"         # target by name (or use index)
  time: "07:30"
  enabled: true
  days: [1, 2, 3, 4, 5]     # 0=Sunday … 6=Saturday
  sound: "Alarm_Clock"
  volume: 0.8
  snooze_duration: 9
  max_snooze_count: 3
  notes: "Team meeting at 9am"
```

### `hawake.trigger_alert`

Show a full-screen alert alarm on the phone.

```yaml
service: hawake.trigger_alert
data:
  device_name: iPhone
  title: "Motion Detected"
  message: "Front camera triggered"
  sound: "Perimeter_Breach"
  volume: 0.9
  media_url: "http://ha.local:8123/local/alert.mp3"
```

### `hawake.dismiss`

Dismiss the currently ringing or snoozed alarm.

```yaml
service: hawake.dismiss
data:
  device_name: iPhone
```

### `hawake.snooze`

Snooze the currently ringing alarm.

```yaml
service: hawake.snooze
data:
  device_name: iPhone
```

### `hawake.skip`

Skip the next fire of the next upcoming alarm.

```yaml
service: hawake.skip
data:
  device_name: iPhone
```

---

## Example Automations

### Re-enable Monday alarm on Sunday evening

```yaml
automation:
  alias: "Re-enable work alarm on Sunday"
  trigger:
    - platform: time
      at: "20:00:00"
  condition:
    - condition: time
      weekday: [sun]
  action:
    - service: hawake.update_alarm
      data:
        name: "Work Alarm"
        enabled: true
```

### Alert phone when front door opens at night

```yaml
automation:
  alias: "Front door night alert"
  trigger:
    - platform: state
      entity_id: binary_sensor.front_door
      to: "on"
  condition:
    - condition: time
      after: "22:00:00"
      before: "06:00:00"
  action:
    - service: hawake.trigger_alert
      data:
        title: "Front Door"
        message: "Front door opened"
        sound: "Perimeter_Breach"
        volume: 1.0
```

### Snooze alarm when leaving the bedroom

```yaml
automation:
  alias: "Auto snooze when leaving bedroom"
  trigger:
    - platform: state
      entity_id: sensor.hawake_iphone_alarm_state
      to: "ringing"
  action:
    - delay: "00:00:30"
    - condition: state
      entity_id: binary_sensor.bedroom_presence
      state: "off"
    - service: hawake.snooze
      data:
        device_name: iPhone
```

---

## MQTT Topic Structure

All topics follow the pattern `{prefix}/{device}/…`

| Direction | Topic Pattern | Description |
|---|---|---|
| App → HA | `hawake/iphone/sensor/{key}` | Dashboard sensor values |
| App → HA | `hawake/iphone/alarm/{n}/{key}` | Per-alarm sensor values |
| App → HA | `hawake/iphone/availability` | App online/offline |
| App → HA | `hawake/iphone/arm/state` | Arm state |
| HA → App | `hawake/iphone/command/{cmd}` | Dashboard commands |
| HA → App | `hawake/iphone/alarm/{n}/command/{cmd}` | Per-alarm commands |
| HA → App | `hawake/iphone/arm/command` | Arm command |

---

## Links

- [HaWake App](https://hawake.app)
- [MQTT Reference](https://hawake.app/docs/hass-api)
- [Report an issue](https://github.com/hawake/hawake-hacs/issues)
