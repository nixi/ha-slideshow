# SlideShow Digital Signage for Home Assistant

A custom integration for [SlideShow](https://slideshow.digital/), the free digital signage
app for Android. It talks to the player's local REST API, so everything stays on your
network — no cloud account and no broker required.

![A SlideShow player showing a live Home Assistant dashboard](docs/panel.png)

*A player showing the live panel. Home Assistant renders the template and streams updates
to it, so nothing reloads and no token ever reaches the display. The template behind this
is [`docs/panel-example.jinja`](docs/panel-example.jinja).*

## What you get

Each player is added as one Home Assistant device:

| Entity | What it does |
| --- | --- |
| `select` | The playlist playing in the main zone, chosen by name. |
| `media_player` | Pause, resume, next, previous, volume and mute for the main zone. Switches playlist through its source list. Browses the Home Assistant media library, plays music and video, and accepts text-to-speech. Shows the current file, playlist and screen layout. |
| `camera` | A live screenshot of what is actually on the display. |
| `sensor` | Current playlist, screen layout, last displayed file and time, volume, screen brightness, free storage and storage used. Diagnostics for IP, versions, boot and app start time. |
| `switch` | Screen power. There is no screen power endpoint, so this selects the layout SlideShow uses while a schedule has the display off, and reads the real state back from `screenPower`. The media player's turn on/off does the same. |
| `binary_sensor` | Screen power, paused, plus diagnostics for rooted, device owner and lock task mode. |
| `button` | Next, previous, toggle fullscreen, clear playlist, clear layout, activate and deactivate screensaver, beep, reload the app and reboot the device. |

### Services

- `slideshow.show_file` — put a single file on screen for N seconds
- `slideshow.show_html` — render a block of HTML on screen
- `slideshow.show_stream` — display a video stream
- `slideshow.set_playlist` / `slideshow.set_layout` — switch playlist or screen layout
- `slideshow.show_camera` — put a camera on the display
- `slideshow.create_content` / `slideshow.delete_content` — manage what the player can play
- `slideshow.install_panel` — add the live dashboard to the player as its own playlist
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
    <div style="font-family: sans-serif; text-align: center;
                padding-top: 20vh; color: #fff">
      <div style="font-size: 6vw">{{ states('sensor.outside_temperature') }} °C</div>
      <div style="font-size: 2vw">{{ states('weather.home') }}</div>
    </div>
```

> [!TIP]
> **Always set a text colour.** The player renders HTML on a black background, but the
> default text colour is also black, so unstyled HTML shows up as a blank black screen
> for the full duration. Set `color: #fff`, or give your own element a background such as
> `<body style="background:#fff;color:#000">`.

## Managing content and playlists

### How SlideShow models this

There is one idea to get straight, because it explains the whole API. A **content entry**
is a source of things to play — a folder of photos, a single file, a weather screen, an
RSS feed. Every content entry gets a **playlist** of its own, and the entry carries that
playlist's ID.

That is also the only way to enumerate playlists: the API has no list-playlists endpoint,
so the **Playlist** select is built by reading the content entries and collecting their
playlist IDs. Anything you create here shows up in that dropdown.

### Creating content

```yaml
action: slideshow.create_content
target:
  entity_id: media_player.frame
data:
  content_name: Holiday photos
  path: photos/holiday
  content_type: ALPHABETICALLY
response_variable: created
```

`created` then holds `content_id` and `playlist_id`, so you can switch to it immediately:

```yaml
action: slideshow.set_playlist
target:
  entity_id: media_player.frame
data:
  playlist_id: "{{ created.playlist_id }}"
```

### Content types

| Type | What `path` means |
| --- | --- |
| `ALPHABETICALLY` | A folder or file on the player, played in name order |
| `RANDOM` | The same, shuffled |
| `STREAM` | The address of an HTTP or RTSP stream |
| `YOUTUBE` | A YouTube video address |
| `RSS` | A feed address |
| `WEATHER`, `DATE_TIME`, `TEXT`, `VIDEO_INPUT` | Generated on the device; `path` carries that type's own setting |

There is **no web page type** — SlideShow shows a web page by playing a text file whose
contents are the address, saved with a `.url` extension. That is what `install_panel` does
for you, and you can do the same for any page:

```yaml
# 1. Get the .url file onto the player. There is no upload endpoint, but the
#    player can fetch one from any address it can reach.
action: slideshow.synchronize
target:
  entity_id: media_player.frame
data:
  url: https://example.com/files/weather.url
  target: weather.url

# 2. Make it playable.
action: slideshow.create_content
target:
  entity_id: media_player.frame
data:
  content_name: Weather page
  path: weather.url
  content_type: ALPHABETICALLY
```

### Removing content

```yaml
action: slideshow.delete_content
target:
  entity_id: media_player.frame
data:
  content_id: 34
```

The device refuses to delete an entry that a schedule still refers to.

### A worked example: rotate a playlist by time of day

```yaml
automation:
  - alias: Frame shows the dashboard in the morning
    triggers:
      - trigger: time
        at: "06:30:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.frame_playlist
        data:
          option: Home Assistant panel

  - alias: Frame goes back to photos in the evening
    triggers:
      - trigger: time
        at: "19:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.frame_playlist
        data:
          option: All files in cycle
```

## A live dashboard that stays on screen

`show_html` is a *notification* mechanism: it overrides the playlist, then hands back. For
a dashboard that is always up, the integration serves a page of its own.

Home Assistant renders your Jinja template **inside Home Assistant**, where it already has
full access to state, and streams re-renders to the page over server-sent events. The page
swaps its own markup, so there is no reload and no flicker. Nothing needs a login, and no
Home Assistant token is ever handed to the player.

[`docs/panel-example.jinja`](docs/panel-example.jinja) is the template behind the
screenshot at the top, and a reasonable starting point: weather and electricity price, room
temperatures, door and alarm status, departures and an agenda. Only the six lists at the
top need changing.

**Setting it up**

1. Open the integration's **Configure** dialog and paste in a template — the shipped
   default, or the example above. Only the lists at the top need changing — point them at
   your own entities.
2. Run `slideshow.install_panel`. The player has no upload endpoint, so Home Assistant
   serves a one-line `.url` file, tells the player to fetch it, and creates a content entry
   pointing at it. The dashboard then appears in the **Playlist** select like any other.

To do it by hand instead, copy the **Panel URL** sensor and add a content item of type
**Web page** with that address in SlideShow's web interface.

That item behaves like any other slide, so it survives reboots and app restarts, and it
can share a rotation with your photos.

**How it updates.** Home Assistant watches exactly the entities your template touches and
re-renders only when one of them changes, so an idle dashboard costs nothing. A template
using `now()` also re-renders on the minute, which is enough for a clock.

**Styling.** The page supplies the theme, so a template only emits content and can never
come out invisible the way sent HTML can. These classes are available: `ss-grid`, `ss-row`,
`ss-card`, `ss-label`, `ss-big`, `ss-mid`, `ss-muted`, `ss-list`, and `ss-ok` / `ss-warn` /
`ss-bad` for state colours. Your template can include its own `<style>` block as well.

> [!IMPORTANT]
> **Load the URL directly — do not put it in an `<iframe>`.** Home Assistant sends
> `X-Frame-Options: SAMEORIGIN`, so a cross-origin frame renders as a broken image. A
> *Web page* content item loads it directly and works.

> [!TIP]
> Set **Internal URL** under Settings → System → Network. Without it Home Assistant only
> knows the external address, and the Panel URL sensor has to hand the player an HTTPS URL
> it may not be able to load — older Android players often cannot manage a modern
> certificate chain in their browser, even though media playback works fine.

> [!NOTE]
> The panel URL contains a secret generated for each player and is reachable **without a
> Home Assistant login** — that is what lets the player load it. Anyone who has the URL can
> see that page, so treat it as you would a share link. It exposes only what your template
> renders, never an API token, and the rest of Home Assistant stays authenticated.

### A reusable HTML slide

`<style>` blocks, flexbox, gradients and `vh`/`vw` units all work (the player runs a
Chromium WebView). This skeleton sets a background and a colour, so it is visible, and
centres its content at any resolution:

```yaml
script:
  frame_show:
    alias: Show something on the frame
    fields:
      content:
        selector: { text: { multiline: true } }
      seconds:
        default: 20
        selector: { number: { min: 1, max: 3600 } }
    sequence:
      - action: slideshow.show_html
        target:
          entity_id: media_player.frame
        data:
          length: "{{ seconds | int(20) }}"
          html: >
            <style>
              html,body{height:100%;margin:0}
              body{display:flex;flex-direction:column;
                   align-items:center;justify-content:center;
                   background:linear-gradient(135deg,#1b4965,#0d2436);
                   color:#fff;font-family:-apple-system,Roboto,sans-serif}
              .big{font-size:16vh;font-weight:300;line-height:1}
              .sub{font-size:5vh;opacity:.75;margin-top:2vh}
            </style>
            {{ content }}
```

Then every caller is one line of markup:

```yaml
action: script.frame_show
data:
  seconds: 20
  content: >
    <div class="big">{{ states('sensor.outside_temperature') }} °C</div>
    <div class="sub">{{ states('weather.home') }}</div>
```

## Playing media on the player

The `media_player` entity is a real Home Assistant media player, so the usual things work:

- **Browse and play** from your media library, with the media browser in the more-info
  dialog.
- **Text-to-speech.** Point any `tts` action at the player.
- **Music plays in the audio zone**, so whatever is on screen is left alone. Video and
  images take over the main zone.

```yaml
action: tts.speak
target:
  entity_id: tts.google_en_com
data:
  media_player_entity_id: media_player.hallway_frame
  message: The washing machine has finished.
```

### Cameras

```yaml
action: slideshow.show_camera
target:
  entity_id: media_player.hallway_frame
data:
  camera_entity_id: camera.front_door
  duration: 60
```

This uses the camera's own RTSP stream where there is one, because the player renders
RTSP directly and that avoids sending the video through Home Assistant. Cameras with no
stream fall back to a still image that refreshes once a second.

> [!IMPORTANT]
> Media from Home Assistant — the media library, text-to-speech, camera stills — is served
> as a URL pointing at Home Assistant, so **the player must be able to reach your Home
> Assistant instance over the network**. If the player is on an isolated IoT VLAN, this is
> the part that will not work.

Home Assistant does not know how long a track is, so playback is requested for one hour by
default and is expected to end on its own. Pass a different `duration` if you need to:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.hallway_frame
data:
  media_content_id: media-source://media_source/local/doorbell.mp3
  media_content_type: music
  extra:
    duration: 15
```

## Sample content

`samples/` holds a starter pack, and every release has a ready-made `samples.zip`
attached. Upload the ZIP through the web interface (menu **Files**) — SlideShow unpacks it
automatically — then add the slides to a playlist.

- `slides/01.jpg` … `05.jpg` — five numbered slides, so playlist cycling, next/previous
  and transitions are obvious at a glance
- `hello.html` — a plain HTML page with a live clock
- `dashboard.url` — a one-line file holding a web address; edit it to point at your own
  dashboard

Regenerate them at your display's own resolution with:

```sh
python scripts/make_samples.py samples --width 1920 --height 1080
```

## Requirements

- Home Assistant 2025.3 or newer (developed and tested against 2026.9)
- SlideShow 4.11 or newer, with the web interface reachable from Home Assistant
- The web interface username and password

## Installation

> [!NOTE]
> This is not in the HACS default store yet — the submission is
> [hacs/default#11146](https://github.com/hacs/default/pull/11146). Until it is merged, add
> it as a custom repository as described below. Nothing changes for you once it is merged;
> it simply becomes searchable in HACS without step 2.

### With HACS

1. Open **HACS** from the Home Assistant sidebar.
2. Click the three dots in the top right, choose **Custom repositories**, paste
   `https://github.com/nixi/ha-slideshow`, set the type to **Integration**, and click
   **ADD**.
3. Search for **SlideShow Digital Signage**, open it, and click **Download**.
4. **Restart Home Assistant.** HACS only copies the files; the running instance keeps the
   old code until it restarts.

Updating later works the same way: HACS offers the new version, and you restart. HACS
checks for updates on a slow cycle, so use **Update information** in the repository's
three-dot menu if you want it to look straight away.

### Manually

1. Download **Source code (zip)** from the
   [latest release](https://github.com/nixi/ha-slideshow/releases/latest) and extract it.
2. Copy the `custom_components/slideshow` folder into your Home Assistant configuration
   directory — the one holding `configuration.yaml`. Create `custom_components` if it is
   not there. You should end up with:

   ```
   config/
   ├── configuration.yaml
   └── custom_components/
       └── slideshow/
           ├── __init__.py
           ├── manifest.json
           └── ...
   ```

3. **Restart Home Assistant.**

Copy only the inner `slideshow` folder, not the whole repository — a
`custom_components/ha-slideshow/custom_components/slideshow` nesting will not be found.

### Adding your player

After restarting, go to **Settings** → **Devices & services** → **Add integration** and
search for **SlideShow**. See [Configuration](#configuration) for what to enter.

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

- **Playlists are discovered from the player's content entries**, each of which carries the
  ID of the playlist it belongs to — there is no list-playlists endpoint. They are re-read
  every five minutes, so a playlist added on the device shows up shortly afterwards.
- **Screen layouts cannot be listed**, so `set_layout` takes a name or ID that you supply.
  You can find these in the SlideShow web interface.
- **Playlists set by `show_file`, `show_html` and media playback override the current
  playlist** for the duration you give, then the player returns to what it was doing. Use
  the *Clear playlist* button to cut an override short.
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

## Development

```sh
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt
pytest tests/ --cov=custom_components.slideshow --cov-report=term-missing
```

CI runs hassfest, HACS validation, ruff and the test suite on every push, with coverage
held at 85% or above.

`scripts/make_panel_screenshot.py` regenerates `docs/panel.png` from the real page shell
and the example template, using invented data. Re-run it if the panel styling changes.

`scripts/live_check.py` exercises the API client against a real player, including the
error paths. It performs one deliberately no-op write:

```sh
SLIDESHOW_HOST=192.168.1.100 SLIDESHOW_PORT=8080 python scripts/live_check.py
```
