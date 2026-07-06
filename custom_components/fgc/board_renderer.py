"""Renders a Geotren-style departure board as a PNG image, for use as a
companion-app home screen widget (via a `camera` entity).

Native Android/iOS widgets can't execute the fgc-timetable-card.js
Lovelace card (no custom JS in a widget), but they *can* show a `camera`
entity's snapshot — so this draws the same visual design (dark
background, colored line pill, destination, minutes, platform) as a
plain image instead, refreshed whenever the widget asks for a new one.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

_FONTS_DIR = Path(__file__).parent / "fonts"
_ICON_PATH = Path(__file__).parent / "icon.png"

_BG = (0, 0, 0)
_YELLOW = (255, 198, 41)
_WHITE = (255, 255, 255)
_MUTED = (170, 170, 170)
_DIVIDER = (40, 40, 40)
_DEFAULT_PILL_COLOR = (100, 100, 100)

_WIDTH = 800
_PADDING = 20
_HEADER_HEIGHT = 110
_ROW_HEIGHT = 80

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, size)
    cached = _font_cache.get(key)
    if cached is None:
        cached = ImageFont.truetype(str(_FONTS_DIR / name), size)
        _font_cache[key] = cached
    return cached


def _hex_to_rgb(hex_color: str | None) -> tuple[int, int, int] | None:
    if not hex_color or len(hex_color) != 6:
        return None
    try:
        return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    while text and draw.textbbox((0, 0), text + "…", font=font)[2] > max_width:
        text = text[:-1]
    return text + "…"


def _platform_text(platform: Any) -> str:
    if platform is None or platform == "":
        return ""
    try:
        return str(int(float(platform)))
    except (TypeError, ValueError):
        return ""


def render_board(departures: list[dict], station_name: str, rows: int = 4) -> bytes:
    """Draw the board for `station_name` and return it as PNG bytes.

    `departures` should already be sorted/deduped/filtered to the future
    (see FgcCoordinator.get_board) — this only takes the first `rows`.
    """
    now = datetime.now().astimezone()
    height = _HEADER_HEIGHT + rows * _ROW_HEIGHT + _PADDING

    img = Image.new("RGB", (_WIDTH, height), _BG)
    draw = ImageDraw.Draw(img)

    bold_44 = _font("Roboto-Bold.ttf", 44)
    bold_20 = _font("Roboto-Bold.ttf", 20)
    bold_26 = _font("Roboto-Bold.ttf", 26)
    bold_28 = _font("Roboto-Bold.ttf", 28)
    regular_30 = _font("Roboto-Regular.ttf", 30)

    # --- Header: logo, station name + clock, "Via" label ---
    logo_size = 56
    logo_x, logo_y = _PADDING, 20
    if _ICON_PATH.exists():
        logo = Image.open(_ICON_PATH).convert("RGBA").resize((logo_size, logo_size))
        img.paste(logo, (logo_x, logo_y), logo)

    text_x = logo_x + logo_size + 16
    draw.text((text_x, logo_y - 2), station_name.upper(), font=bold_20, fill=(200, 200, 200))
    draw.text((text_x, logo_y + 22), now.strftime("%H:%M"), font=bold_44, fill=_YELLOW)

    via_text = "Via"
    via_bbox = draw.textbbox((0, 0), via_text, font=bold_28)
    draw.text(
        (_WIDTH - _PADDING - (via_bbox[2] - via_bbox[0]), 40),
        via_text,
        font=bold_28,
        fill=_YELLOW,
    )

    # --- Rows ---
    visible = [dep for dep in departures if dep["datetime"] >= now][:rows]
    y = _HEADER_HEIGHT
    if not visible:
        draw.text(
            (_PADDING, y + 20), "No more departures today", font=regular_30, fill=_MUTED
        )
    else:
        for dep in visible:
            draw.line([(0, y), (_WIDTH, y)], fill=_DIVIDER, width=2)
            mins = max(0, round((dep["datetime"] - now).total_seconds() / 60))

            # Line pill.
            line_text = dep.get("line") or ""
            pill_color = _hex_to_rgb(dep.get("line_color")) or _DEFAULT_PILL_COLOR
            pill_text_color = _hex_to_rgb(dep.get("line_text_color")) or _WHITE
            pill_w, pill_h = 90, 44
            pill_x, pill_y = _PADDING, y + (_ROW_HEIGHT - pill_h) // 2
            draw.rounded_rectangle(
                [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
                radius=pill_h // 2,
                fill=pill_color,
            )
            tb = draw.textbbox((0, 0), line_text, font=bold_26)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            draw.text(
                (pill_x + (pill_w - tw) / 2, pill_y + (pill_h - th) / 2 - tb[1]),
                line_text,
                font=bold_26,
                fill=pill_text_color,
            )

            # Destination (truncated to leave room for mins/platform).
            dest_x = pill_x + pill_w + 20
            dest = _truncate(draw, dep.get("destination") or "", regular_30, _WIDTH - dest_x - 220)
            draw.text(
                (dest_x, y + (_ROW_HEIGHT - 30) / 2 - 4), dest, font=regular_30, fill=_YELLOW
            )

            # Minutes.
            mins_text = f"{mins} min"
            mb = draw.textbbox((0, 0), mins_text, font=regular_30)
            draw.text(
                (_WIDTH - _PADDING - 70 - (mb[2] - mb[0]), y + (_ROW_HEIGHT - 30) / 2 - 4),
                mins_text,
                font=regular_30,
                fill=_WHITE,
            )

            # Platform.
            platform_text = _platform_text(dep.get("platform"))
            pb = draw.textbbox((0, 0), platform_text, font=regular_30)
            draw.text(
                (_WIDTH - _PADDING - (pb[2] - pb[0]), y + (_ROW_HEIGHT - 30) / 2 - 4),
                platform_text,
                font=regular_30,
                fill=_WHITE,
            )

            y += _ROW_HEIGHT

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
