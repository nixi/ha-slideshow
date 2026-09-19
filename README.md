# SlideShow Digital Signage for Home Assistant

A custom integration for [SlideShow](https://slideshow.digital/), the free digital signage
app for Android. It talks to the player's local REST API, so everything stays on your
network — no cloud account and no broker required.

## What you get

Each player is added as one Home Assistant device:

| Entity | What it does |
| --- | --- |
| `media_player` | Pause, resume, next, previous, volume and mute for the main zone. Shows the current file, playlist and screen layout. |
| `camera` | A live screenshot of what is actually on the display. |
| `sensor` | Current playlist, screen layout, last displayed file and time, volume, screen brightness, free storage and storage used. Diagnostics for IP, versions, boot and app start time. |
| `binary_sensor` | Screen power, paused, plus diagnostics for rooted, device owner and lock task mode. |
| `button` | Next, previous, toggle fullscreen, clear playlist, clear layout, activate and deactivate screensaver, beep, reload the app and reboot the device. |

### Services

- `slideshow.show_file` — put a single file on screen for N seconds
- `slideshow.show_html` — render a block of HTML on screen
- `slideshow.show_stream` — display a video stream
- `slideshow.set_playlist` / `slideshow.set_layout` — switch playlist or screen layout
- `slideshow.synchronize` — pull content from an external server

`show_html` is the interesting one: it lets you push a rendered Home Assistant template
straight onto a wall display.

```yaml
action: slideshow.show_html
target:
  entity_id: media_player.hallway_frame
data:
  length: 20
  html: >
    <div style="font-family: sans-serif; text-align: center; padding-top: 20vh">
      <div style="font-size: 6vw">{{ states('sensor.outside_temperature') }} °C</div>
      <div style="font-size: 2vw">{{ states('weather.home') }}</div>
    </div>
```

## Requirements

- SlideShow 4.11 or newer, with the web interface reachable from Home Assistant
- The web interface username and password

## Installation

### HACS (custom repository)

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add this repository's URL with the category **Integration**.
3. Install **SlideShow Digital Signage** and restart Home Assistant.

### Manual

Copy `custom_components/slideshow` into your Home Assistant `config/custom_components`
directory and restart.

## Configuration

Go to **Settings → Devices & services → Add integration** and search for *SlideShow*.

| Field | Notes |
| --- | --- |
| Host | The player's IP address. A static lease is recommended. |
| Port | `80` on rooted devices, `8080` otherwise. HTTPS uses `443` / `8443`. |
| Username / password | Defaults to `admin` / `admin`. Change this on the device. |
| Use HTTPS | Optional. |
| Verify the SSL certificate | Leave off unless you uploaded your own certificate — SlideShow generates a self-signed one on first start. |

The polling interval (30 seconds by default) can be changed under the integration's
**Configure** button.

## Notes and limitations

- **The API has no way to list playlists or screen layouts**, so `set_playlist` and
  `set_layout` take a name, ID or number that you supply. You can find these in the
  SlideShow web interface.
- **Screen power and brightness are read-only.** The device reports them, but the public
  API has no setter. Players commonly switch the screen off by moving to a dedicated
  screen layout, which you can drive with `slideshow.set_layout`.
- **HTTP Basic Authentication is sent in the clear** unless you enable HTTPS. Keep your
  players on a trusted network segment.
- The `/ajax/shell` endpoint and the device-owner / lock-task endpoints are deliberately
  **not** exposed. They allow arbitrary command execution and can lock a device
  irrecoverably.
- Communication is local polling. SlideShow also offers MQTT, but it carries only a subset
  of the API (no screenshot, no pause/resume) and has no availability topic, so REST is
  used instead.

## Credits

SlideShow is developed by [Miroslav Macík](https://slideshow.digital/) and is not
affiliated with this integration.
