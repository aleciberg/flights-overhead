# Flights Overhead

A Raspberry Pi 4 desk display showing aircraft currently flying overhead near Portland / Vancouver, OR. Dark-themed flight cards on a 7" touchscreen, refreshing every 45 seconds from the OpenSky Network free API.

![Simulated display showing 5 flight cards — UPS445, QXE3491, UAL412, DAL891, SWA667 — with altitude, speed, heading, and vertical rate](docs/screenshot.png)

---

## Hardware

| Part | Notes |
|---|---|
| Raspberry Pi 4 | Any RAM tier works |
| Official 7" Touchscreen | 800×480, DSI connector |
| Case | Pi Foundation case or 3D-printed stand |

---

## What's built

### `fetcher.py` — flight data
- Queries the [OpenSky Network REST API](https://opensky-network.org/apidoc/rest.html) with a bounding box covering a ~75-mile radius around Portland (44.4–46.6°N, 124.3–121.0°W)
- Parses state vectors: callsign, position, barometric altitude, speed, heading, vertical rate, origin country
- Converts units: meters → feet, m/s → knots, m/s → fpm
- Calculates distance from Portland center using the Haversine formula
- Sorts results by proximity
- Filters out ground traffic (`on_ground = true`)
- `SIMULATE=true` mode injects 12 realistic fake flights (Portland-area mix of domestic/international carriers, FedEx, UPS) with small random jitter so the data looks live — no network or hardware needed

### `display.py` — Pygame UI
- 800×480 dark theme, three zones: header / cards / footer
- **Header**: title, aircraft count, last-updated timestamp
- **Cards**: up to 5 visible at once, alternating row shading
  - Callsign (cyan, large), distance (coral), origin country (dim)
  - Compass heading + degrees (N / NE / E … NW), right-aligned
  - Altitude (gold), speed (green), vertical rate with direction indicator
- **Footer**: SIMULATE badge, scroll position ("showing 1–5 of 12"), data source credit
- Keyboard scroll: `↑` / `↓` arrow keys
- Touch scroll: swipe up/down on the Pi touchscreen (FINGERUP/FINGERDOWN events)
- Thread-safe: background data thread and Pygame render loop are decoupled

### `main.py` — entry point
- `--simulate` flag (or `SIMULATE=true` env var) for fake-data mode
- `--fullscreen` flag for the Pi display
- `--interval SEC` to change the refresh cadence (default 45s)
- Initial fetch is synchronous so the display is populated immediately on startup
- Background thread refreshes data on the interval; errors surface as a card-area message without crashing

### `flights.service` — systemd unit
- Runs as the `pi` user under the existing X session (`DISPLAY=:0`)
- 8-second startup delay to let the desktop session come up before Pygame tries to open a window
- `Restart=always` — recovers from crashes or network failures automatically

### `install.sh` — Pi installer
- Installs system packages (`python3-pygame` from apt to avoid a source build, `fonts-dejavu-core`)
- Creates a virtualenv with `--system-site-packages` so it picks up the apt pygame
- Installs Python deps (`requests`)
- Runs a 5-second smoke test in SIMULATE mode
- Installs and enables the systemd service

---

## Running locally (macOS / Linux dev machine)

```bash
pip install -r requirements.txt

# Fake data — no network needed, window opens immediately
python main.py --simulate

# Live OpenSky data
python main.py

# Faster refresh for testing
python main.py --simulate --interval 10
```

Press `Q` or `Escape` to quit. `↑` / `↓` scroll through more than 5 flights.

---

## Pi deploy

```bash
# On the Pi (as the pi user):
git clone <this-repo> ~/flights-overhead
cd ~/flights-overhead
bash install.sh
```

After install:
```bash
sudo systemctl status flights-overhead
journalctl -u flights-overhead -f
sudo systemctl restart flights-overhead
```

To test the display without network on the Pi itself, add `Environment=SIMULATE=true` to `/etc/systemd/system/flights.service` and `sudo systemctl restart flights-overhead`.

---

## What's next

### Data quality
- **Aircraft type lookup** — OpenSky's metadata endpoint (`/api/metadata/aircraft/icao/{icao24}`) returns manufacturer, model, and registration. Requires a free account. Would add a third line to each card: `Boeing 737-800 · N12345`.
- **Origin/destination** — OpenSky's flight route endpoint (`/api/routes?callsign=UAL412`) can often return departure and arrival airports. Hit it once per callsign and cache until the flight disappears.
- **Age indicator** — dim or border cards where `last_contact` is >90s old; OpenSky sometimes serves stale positions.

### Display
- **Mini map** — a small Portland-area map in the header or a sidebar showing aircraft dots at their lat/lon, sized by altitude. Pygame `draw.circle` is sufficient; no tile server needed.
- **Scrollable with momentum** — current touch scroll is one card per swipe; a velocity-based momentum scroll would feel better on the Pi touchscreen.
- **Pagination dots** — small indicators in the footer showing which page of cards is visible.
- **Highlighted nearest** — always pin the closest flight at the top with a slightly brighter card background.

### Operations
- **Rate-limit handling** — OpenSky's anonymous tier throttles to ~400 requests/day (~1 per 3.6 min). The current 45s default is fine, but adding a backoff on 429 responses would be more robust.
- **Offline graceful degradation** — show last-known data with a "stale" banner rather than an error card when the network drops.
- **Config file** — move center lat/lon, radius, refresh interval, and display size to a `config.toml` so they can be changed without touching code.
- **Screen dimming** — dim the display at a configurable hour (e.g. midnight–6am) using `pygame.display.set_gamma` or a simple black overlay.
