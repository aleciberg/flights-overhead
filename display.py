"""
Pygame flight-card display for Raspberry Pi 7" touchscreen (800×480, dark theme).
"""

import time
import logging
import threading
import pygame
from typing import List, Optional, Tuple

from fetcher import Flight, SIMULATE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
BG = (13,  13,  20)
CARD_EVEN = (22,  22,  46)
CARD_ODD = (18,  18,  38)
HEADER_BG = (10,  10,  28)
DIVIDER = (35,  35,  60)

ACCENT = (0,   212, 255)   # cyan  — callsigns
TEXT = (220, 220, 220)   # white-ish
DIM = (110, 110, 140)   # muted
GOLD = (255, 210,  70)   # altitude
GREEN = (0,   230, 120)   # speed / climbing
RED_VR = (255,  85,  85)   # descending
CORAL = (255, 120,  90)   # distance
AMBER = (255, 185,  30)   # simulate badge
ROUTE = (180, 210, 255)   # origin -> destination

# ---------------------------------------------------------------------------
# Layout constants (pixels, 800×480 target)
# ---------------------------------------------------------------------------
W, H = 800, 480
HEADER_H = 58
FOOTER_H = 28
CARD_H = 88
CARD_GAP = 5
CARD_MX = 12    # horizontal margin

CARDS_AREA_H = H - HEADER_H - FOOTER_H          # 394 px
CARDS_PER_PAGE = CARDS_AREA_H // (CARD_H + CARD_GAP)  # 4

# ---------------------------------------------------------------------------
# Heading helpers
# ---------------------------------------------------------------------------
_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _hdg_compass(deg: float) -> str:
    return _COMPASS[round(deg / 45) % 8]


def _vr_label(fpm: Optional[float]) -> Tuple[str, Tuple]:
    if fpm is None:
        return "--", DIM
    if fpm > 150:
        return f"^ {fpm:,.0f} fpm", GREEN
    if fpm < -150:
        return f"v {abs(fpm):,.0f} fpm", RED_VR
    return "~ level", DIM


# ---------------------------------------------------------------------------
# Font loader
# ---------------------------------------------------------------------------
def _load_font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ["dejavusans", "dejavusanscondensed", "freesans", "arial",
                 "helveticaneue", "liberationsans", "sans"]:
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


# ---------------------------------------------------------------------------
# Display class
# ---------------------------------------------------------------------------
class FlightDisplay:
    def __init__(self, fullscreen: bool = False):
        pygame.init()
        flags = pygame.FULLSCREEN if fullscreen else 0
        self.screen = pygame.display.set_mode((W, H), flags)
        pygame.display.set_caption("Flights Overhead — Portland")
        pygame.mouse.set_visible(not fullscreen)

        self._f_callsign = _load_font(26, bold=True)
        self._f_meta = _load_font(18)
        self._f_dim = _load_font(15)
        self._f_header = _load_font(20, bold=True)
        self._f_sub = _load_font(15)

        self._lock = threading.Lock()
        self._flights: List[Flight] = []
        self._last_update: float = 0.0
        self._error: Optional[str] = None
        self._scroll_offset: int = 0

        # Touch-scroll tracking
        self._touch_y0: Optional[float] = None

    # ------------------------------------------------------------------ data
    def update(self, flights: List[Flight], error: Optional[str] = None) -> None:
        with self._lock:
            self._flights = flights
            self._last_update = time.time()
            self._error = error
            self._scroll_offset = 0

    # ---------------------------------------------------------------- events
    def handle_events(self) -> bool:
        """Return False to quit."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    return False
                if event.key == pygame.K_DOWN:
                    self._scroll_down()
                if event.key == pygame.K_UP:
                    self._scroll_up()
            # Touch events (Pi touchscreen sends FINGER*)
            if event.type == pygame.FINGERDOWN:
                self._touch_y0 = event.y
            if event.type == pygame.FINGERUP and self._touch_y0 is not None:
                delta = self._touch_y0 - event.y   # positive = swipe up
                if delta > 0.06:
                    self._scroll_down()
                elif delta < -0.06:
                    self._scroll_up()
                self._touch_y0 = None
        return True

    def _scroll_down(self) -> None:
        with self._lock:
            limit = max(0, len(self._flights) - CARDS_PER_PAGE)
            self._scroll_offset = min(self._scroll_offset + 1, limit)

    def _scroll_up(self) -> None:
        with self._lock:
            self._scroll_offset = max(self._scroll_offset - 1, 0)

    # ------------------------------------------------------------------ draw
    def draw(self) -> None:
        with self._lock:
            flights = list(self._flights)
            last_update = self._last_update
            error = self._error
            scroll = self._scroll_offset

        self.screen.fill(BG)
        self._draw_header(len(flights), last_update)
        self._draw_cards(flights, scroll, error)
        self._draw_footer(scroll, len(flights))
        pygame.display.flip()

    # ---------------------------------------------------------------- header
    def _draw_header(self, count: int, last_update: float) -> None:
        pygame.draw.rect(self.screen, HEADER_BG, (0, 0, W, HEADER_H))
        pygame.draw.line(self.screen, DIVIDER,
                         (0, HEADER_H - 1), (W, HEADER_H - 1), 1)

        title = self._f_header.render(
            "FLIGHTS OVERHEAD  •  Portland / Vancouver, OR", True, ACCENT)
        self.screen.blit(title, (16, 11))

        sub = self._f_sub.render(f"{count} aircraft in range", True, DIM)
        self.screen.blit(sub, (16, 36))

        if last_update:
            ts = time.strftime("%H:%M:%S", time.localtime(last_update))
            upd = self._f_sub.render(f"updated {ts}", True, DIM)
            self.screen.blit(upd, (W - upd.get_width() - 16, 24))

    # ----------------------------------------------------------------- cards
    def _draw_cards(
        self,
        flights: List[Flight],
        scroll: int,
        error: Optional[str],
    ) -> None:
        y = HEADER_H + 6
        visible = flights[scroll: scroll + CARDS_PER_PAGE]

        if not visible:
            msg_text = error if error else "No flights detected in range"
            color = RED_VR if error else DIM
            prefix = "⚠  " if error else ""
            msg = self._f_meta.render(f"{prefix}{msg_text}", True, color)
            self.screen.blit(msg, (W // 2 - msg.get_width() // 2, H // 2 - 16))
            return

        for idx, flight in enumerate(visible):
            self._draw_card(flight, y, idx)
            y += CARD_H + CARD_GAP

    def _draw_card(self, f: Flight, y: int, idx: int) -> None:
        bg = CARD_EVEN if idx % 2 == 0 else CARD_ODD
        rect = pygame.Rect(CARD_MX, y, W - CARD_MX * 2, CARD_H)
        pygame.draw.rect(self.screen, bg, rect, border_radius=7)

        lx = rect.x + 14
        ry1 = y + 13    # row 1: callsign / distance / heading
        ry2 = y + 40    # row 2: route / country
        ry3 = y + 65    # row 3: altitude / speed / vrate / type

        # --- Row 1: callsign, distance, heading ---
        cs = self._f_callsign.render(f.callsign, True, ACCENT)
        self.screen.blit(cs, (lx, ry1))

        dist = self._f_meta.render(f"{f.distance_mi:.0f} mi", True, CORAL)
        self.screen.blit(dist, (lx + 200, ry1 + 4))

        hdg_str = f"{_hdg_compass(f.heading)}  {f.heading:.0f}°" if f.heading is not None else "--"
        hdg = self._f_meta.render(hdg_str, True, TEXT)
        self.screen.blit(hdg, (rect.right - hdg.get_width() - 14, ry1 + 4))

        # --- Row 2: route (left) + country (right) ---
        if f.route:
            origin, dest = f.route
            route_str = f"From {origin} to {dest}" if dest else f"From {origin}"
            route_surf = self._f_meta.render(route_str, True, ROUTE)
            self.screen.blit(route_surf, (lx, ry2))
        elif f.airline:
            # No specific route in database — show airline name as fallback
            logger.debug(
                "card %s: no route, falling back to airline %r", f.callsign, f.airline)
            airline_surf = self._f_dim.render(f.airline, True, DIM)
            self.screen.blit(airline_surf, (lx, ry2 + 2))
        else:
            logger.debug("card %s: no route and no airline match", f.callsign)

        country_surf = self._f_dim.render(f.origin_country[:20], True, DIM)
        self.screen.blit(country_surf, (rect.right -
                         country_surf.get_width() - 14, ry2 + 2))

        # --- Row 3: altitude, speed, vrate (left) + aircraft type (right) ---
        alt_str = f"{f.altitude_ft:,.0f} ft" if f.altitude_ft is not None else "-- ft"
        self.screen.blit(self._f_meta.render(alt_str, True, GOLD), (lx, ry3))

        spd_str = f"{f.speed_kts:.0f} kts" if f.speed_kts is not None else "-- kts"
        self.screen.blit(self._f_meta.render(
            spd_str, True, GREEN), (lx + 160, ry3))

        vr_str, vr_color = _vr_label(f.vertical_rate_fpm)
        self.screen.blit(self._f_meta.render(
            vr_str, True, vr_color), (lx + 290, ry3))

        if f.aircraft_type:
            type_str = f.aircraft_type[:28]   # truncate so it stays in card
            type_surf = self._f_dim.render(type_str, True, DIM)
            self.screen.blit(
                type_surf, (rect.right - type_surf.get_width() - 14, ry3 + 2))

    # ---------------------------------------------------------------- footer
    def _draw_footer(self, scroll: int, total: int) -> None:
        fy = H - FOOTER_H
        pygame.draw.line(self.screen, DIVIDER, (0, fy), (W, fy), 1)
        pygame.draw.rect(self.screen, HEADER_BG, (0, fy, W, FOOTER_H))

        if SIMULATE:
            badge = self._f_dim.render("* SIMULATE", True, AMBER)
            self.screen.blit(badge, (16, fy + 7))

        # Scroll position indicator
        if total > CARDS_PER_PAGE:
            end = min(scroll + CARDS_PER_PAGE, total)
            pos = self._f_dim.render(
                f"showing {scroll + 1}-{end} of {total}", True, DIM)
            cx = W // 2 - pos.get_width() // 2
            self.screen.blit(pos, (cx, fy + 7))

        source = self._f_dim.render(
            "OpenSky Network  •  75 mi radius", True, DIM)
        self.screen.blit(source, (W - source.get_width() - 16, fy + 7))
