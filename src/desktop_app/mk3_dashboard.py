"""
Mirza OS MK3 — premium command dashboard for the Jarvis desktop app.

Design goals
------------
- TASM1-inspired dark command-centre language without copying a movie asset.
- Quiet-by-default JARVIS presence: useful state, not narration.
- Dense but disciplined HUDs with cyan as the system accent and restrained
  semantic colours for warning, success, analysis and Vault.
- Real local system telemetry with no extra dependencies beyond the existing
  PyQt6 + psutil desktop stack.
- Persistent work tally, quick capture, action history and theme state.
- Hand-control smoothing primitives ready for camera/MediaPipe input.
- "Web Link" relationships that visually connect related command nodes.

Run directly:
    python -m desktop_app.mk3_dashboard

Or, once the companion __main__.py change is present:
    python -m desktop_app --mk3
"""

from __future__ import annotations

import json
import math
import os
import random
import socket
import sys
import time
import webbrowser
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import psutil
from PyQt6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

try:
    from desktop_app.face_widget import get_jarvis_state
except Exception:  # pragma: no cover - optional when running module standalone
    get_jarvis_state = None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

DEFAULT_STATE = {
    "theme": "cyan",
    "focus_mode": False,
    "zero_ui": False,
    "work": {
        "target": 400,
        "file": 0,
        "gp": 0,
        "pharm": 0,
        "pa": 0,
        "tasked": 0,
        "unmatched": 0,
        "dup": 0,
    },
    "captures": [],
    "actions": [],
    "device_toggles": {
        "lights": False,
        "audio": True,
        "monitor": True,
        "privacy": True,
    },
}


class MK3Store:
    def __init__(self) -> None:
        base = Path.home() / ".config" / "jarvis"
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "mirza_mk3.json"
        self.state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return json.loads(json.dumps(DEFAULT_STATE))
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return json.loads(json.dumps(DEFAULT_STATE))

        # Merge conservatively so future keys appear without destroying old state.
        merged = json.loads(json.dumps(DEFAULT_STATE))
        for key, value in raw.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
        return merged

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self.state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def add_action(self, label: str, before: Optional[dict] = None) -> None:
        actions = self.state.setdefault("actions", [])
        actions.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "label": label,
                "before": before,
            }
        )
        del actions[:-40]
        self.save()

    def add_capture(self, text: str) -> None:
        captures = self.state.setdefault("captures", [])
        captures.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "text": text.strip(),
            }
        )
        del captures[:-30]
        self.add_action("Quick capture saved")


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

THEMES = {
    "cyan": {
        "accent": "#2ff4e8",
        "accent2": "#36a6ff",
        "soft": "#0b3535",
        "panel": "#061116",
        "panel2": "#08171d",
        "text": "#f1f7f7",
        "muted": "#7f9ca0",
    },
    "amber": {
        "accent": "#ffc247",
        "accent2": "#ff8d2a",
        "soft": "#3b2b08",
        "panel": "#130e06",
        "panel2": "#1b1308",
        "text": "#fff7e3",
        "muted": "#aa9872",
    },
    "green": {
        "accent": "#68ff8a",
        "accent2": "#28d9a0",
        "soft": "#0a3922",
        "panel": "#06120c",
        "panel2": "#071b11",
        "text": "#effff3",
        "muted": "#7ea48b",
    },
    "purple": {
        "accent": "#c383ff",
        "accent2": "#7c6cff",
        "soft": "#2b1741",
        "panel": "#100a17",
        "panel2": "#160d20",
        "text": "#faf2ff",
        "muted": "#9e86ad",
    },
    "crimson": {
        "accent": "#ff4f5f",
        "accent2": "#ff2e36",
        "soft": "#401015",
        "panel": "#150708",
        "panel2": "#1c090b",
        "text": "#fff1f2",
        "muted": "#ac7b80",
    },
    "ice": {
        "accent": "#e9fbff",
        "accent2": "#8ad9ff",
        "soft": "#173039",
        "panel": "#071015",
        "panel2": "#0c171d",
        "text": "#ffffff",
        "muted": "#8ca1aa",
    },
}

SEMANTIC = {
    "danger": "#ff4f5f",
    "warning": "#ffc247",
    "success": "#5bff93",
    "analysis": "#b985ff",
    "info": "#4bbcff",
}


def build_stylesheet(theme: dict) -> str:
    a = theme["accent"]
    a2 = theme["accent2"]
    panel = theme["panel"]
    panel2 = theme["panel2"]
    text = theme["text"]
    muted = theme["muted"]

    return f"""
    QWidget {{
        background: #02070a;
        color: {text};
        font-family: "Segoe UI", "Inter", sans-serif;
        font-size: 12px;
    }}
    QScrollArea {{
        border: none;
        background: #02070a;
    }}
    QFrame#hud {{
        background: {panel};
        border: 1px solid rgba(47, 244, 232, 0.28);
        border-radius: 2px;
    }}
    QFrame#hudAlt {{
        background: {panel2};
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 2px;
    }}
    QLabel#eyebrow {{
        color: {a};
        font-weight: 700;
        font-size: 10px;
        letter-spacing: 1px;
    }}
    QLabel#title {{
        color: {text};
        font-size: 18px;
        font-weight: 650;
    }}
    QLabel#hero {{
        color: {text};
        font-size: 28px;
        font-weight: 500;
    }}
    QLabel#muted {{
        color: {muted};
    }}
    QLabel#accent {{
        color: {a};
        font-weight: 700;
    }}
    QPushButton {{
        background: #071216;
        color: {text};
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 2px;
        padding: 6px 9px;
        min-height: 20px;
    }}
    QPushButton:hover {{
        border-color: {a};
        color: {a};
        background: #0a181d;
    }}
    QPushButton:pressed {{
        background: {theme["soft"]};
    }}
    QPushButton#active {{
        color: {a};
        border-color: {a};
        background: {theme["soft"]};
        font-weight: 700;
    }}
    QPushButton#danger {{
        color: {SEMANTIC["danger"]};
        border-color: rgba(255,79,95,0.55);
    }}
    QLineEdit {{
        background: #030a0d;
        color: {text};
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 2px;
        padding: 8px 10px;
        selection-background-color: {a2};
    }}
    QLineEdit:focus {{
        border-color: {a};
    }}
    QCheckBox {{
        color: {muted};
        spacing: 8px;
    }}
    """


# ---------------------------------------------------------------------------
# Gesture smoothing primitives
# ---------------------------------------------------------------------------

@dataclass
class SmoothedPoint:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0


class GestureSmoother:
    """Velocity-aware low-pass filter for future camera hand tracking.

    Feed normalized camera coordinates into ``update(x, y, dt)`` and use the
    returned point for HUD positioning. Small jitter is suppressed while fast
    intentional movement remains responsive.
    """

    def __init__(
        self,
        response: float = 14.0,
        velocity_gain: float = 0.14,
        dead_zone: float = 0.0025,
    ) -> None:
        self.response = response
        self.velocity_gain = velocity_gain
        self.dead_zone = dead_zone
        self.point: Optional[SmoothedPoint] = None

    def reset(self) -> None:
        self.point = None

    def update(self, x: float, y: float, dt: float) -> SmoothedPoint:
        dt = max(1 / 240, min(dt, 0.1))
        if self.point is None:
            self.point = SmoothedPoint(x, y)
            return self.point

        dx = x - self.point.x
        dy = y - self.point.y
        distance = math.hypot(dx, dy)
        if distance < self.dead_zone:
            return self.point

        speed = distance / dt
        alpha = 1.0 - math.exp(
            -self.response * (1.0 + min(speed * self.velocity_gain, 3.0)) * dt
        )
        nx = self.point.x + dx * alpha
        ny = self.point.y + dy * alpha
        self.point.vx = (nx - self.point.x) / dt
        self.point.vy = (ny - self.point.y) / dt
        self.point.x = nx
        self.point.y = ny
        return self.point


# ---------------------------------------------------------------------------
# Reusable HUD widgets
# ---------------------------------------------------------------------------

class HUD(QFrame):
    def __init__(
        self,
        title: str,
        eyebrow: str = "",
        accent: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("hud")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(8)

        if eyebrow:
            eye = QLabel(eyebrow.upper())
            eye.setObjectName("eyebrow")
            if accent:
                eye.setStyleSheet(f"color:{accent};")
            self._layout.addWidget(eye)

        label = QLabel(title)
        label.setObjectName("title")
        if accent:
            label.setStyleSheet(f"color:{accent}; font-size:18px; font-weight:650;")
        self._layout.addWidget(label)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


class MetricPill(QFrame):
    def __init__(self, label: str, value: str, accent: str) -> None:
        super().__init__()
        self.setObjectName("hudAlt")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(2)
        l = QLabel(label.upper())
        l.setObjectName("muted")
        l.setStyleSheet("font-size:9px;")
        self.value = QLabel(value)
        self.value.setStyleSheet(
            f"font-size:17px; font-weight:650; color:{accent}; background:transparent;"
        )
        layout.addWidget(l)
        layout.addWidget(self.value)


class TinyBar(QWidget):
    def __init__(self, accent: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.value = 0.0
        self.accent = QColor(accent)
        self.setMinimumHeight(8)
        self.setMaximumHeight(8)

    def set_value(self, value: float) -> None:
        self.value = max(0.0, min(float(value), 1.0))
        self.update()

    def set_accent(self, accent: str) -> None:
        self.accent = QColor(accent)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor("#0d1b20"))
        fill = QRectF(r)
        fill.setWidth(r.width() * self.value)
        p.fillRect(fill, self.accent)


class ReactorWidget(QWidget):
    """Central TASM-inspired web reactor with a custom spider glyph."""

    def __init__(self, accent: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.accent = QColor(accent)
        self.phase = 0.0
        self.alert_level = 0
        self.setMinimumHeight(360)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def set_accent(self, accent: str) -> None:
        self.accent = QColor(accent)
        self.update()

    def set_alert_level(self, level: int) -> None:
        self.alert_level = max(0, min(level, 3))
        self.update()

    def _tick(self) -> None:
        self.phase = (self.phase + 0.012) % (math.pi * 2)
        self.update()

    def _draw_spider(self, p: QPainter, cx: float, cy: float, scale: float) -> None:
        pen = QPen(QColor("#f5fbff"), max(1.5, 2.2 * scale))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Body
        path = QPainterPath()
        path.moveTo(cx, cy - 44 * scale)
        path.lineTo(cx - 9 * scale, cy - 18 * scale)
        path.lineTo(cx - 7 * scale, cy + 35 * scale)
        path.lineTo(cx, cy + 58 * scale)
        path.lineTo(cx + 7 * scale, cy + 35 * scale)
        path.lineTo(cx + 9 * scale, cy - 18 * scale)
        path.closeSubpath()
        p.drawPath(path)

        # Long angular legs: recognisably spider-like, intentionally not a movie asset.
        for side in (-1, 1):
            leg_paths = [
                [(10, -28), (24, -55), (34, -92), (46, -116)],
                [(10, -15), (32, -34), (48, -62), (62, -80)],
                [(9, 4), (34, 20), (50, 52), (64, 76)],
                [(7, 23), (25, 54), (34, 88), (42, 112)],
            ]
            for points in leg_paths:
                lp = QPainterPath()
                x0, y0 = points[0]
                lp.moveTo(cx + side * x0 * scale, cy + y0 * scale)
                for x, y in points[1:]:
                    lp.lineTo(cx + side * x * scale, cy + y * scale)
                p.drawPath(lp)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2 - 12
        radius = min(w, h) * 0.34

        # faint web geometry
        web = QColor(self.accent)
        web.setAlpha(38)
        p.setPen(QPen(web, 1))
        for i in range(8):
            angle = i * math.pi / 4 + self.phase * 0.05
            p.drawLine(
                QPointF(cx, cy),
                QPointF(
                    cx + math.cos(angle) * radius * 1.55,
                    cy + math.sin(angle) * radius * 1.55,
                ),
            )

        for ring in range(1, 6):
            rr = radius * ring / 5
            alpha = 20 + ring * 8
            col = QColor(self.accent)
            col.setAlpha(alpha)
            p.setPen(QPen(col, 1))
            p.drawEllipse(QPointF(cx, cy), rr, rr)

        # reactor arcs
        arc_col = QColor(self.accent)
        arc_col.setAlpha(170)
        p.setPen(QPen(arc_col, 2))
        for ring, start in ((0.72, 25), (0.9, 95), (1.08, 175), (1.26, 255)):
            rr = radius * ring
            rect = QRectF(cx - rr, cy - rr, rr * 2, rr * 2)
            p.drawArc(rect, int((start + self.phase * 30) * 16), int(58 * 16))
            p.drawArc(rect, int((start + 180 + self.phase * 18) * 16), int(42 * 16))

        # alert marks
        if self.alert_level:
            danger = QColor(SEMANTIC["danger"])
            danger.setAlpha(170)
            p.setPen(QPen(danger, 2))
            for i in range(self.alert_level * 2):
                ang = (i / max(1, self.alert_level * 2)) * math.pi * 2 + self.phase
                r1 = radius * 1.32
                r2 = radius * 1.47
                p.drawLine(
                    QPointF(cx + math.cos(ang) * r1, cy + math.sin(ang) * r1),
                    QPointF(cx + math.cos(ang) * r2, cy + math.sin(ang) * r2),
                )

        # centre glow
        glow = QColor(self.accent)
        glow.setAlpha(55)
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), radius * 0.58, radius * 0.58)

        self._draw_spider(p, cx, cy, max(0.75, radius / 170))

        p.setPen(QColor("#efffff"))
        f = QFont("Segoe UI", 11, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        p.setFont(f)
        p.drawText(
            QRectF(0, h - 62, w, 20),
            Qt.AlignmentFlag.AlignCenter,
            "MIRZA AUTHENTICATED",
        )
        p.setPen(self.accent)
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        p.drawText(
            QRectF(0, h - 40, w, 18),
            Qt.AlignmentFlag.AlignCenter,
            "ALL SYSTEMS OPERATIONAL",
        )


class Sparkline(QWidget):
    def __init__(self, accent: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.accent = QColor(accent)
        self.values = deque(maxlen=60)
        self.setMinimumHeight(50)

    def push(self, value: float) -> None:
        self.values.append(float(value))
        self.update()

    def set_accent(self, accent: str) -> None:
        self.accent = QColor(accent)
        self.update()

    def paintEvent(self, event) -> None:
        if len(self.values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        vals = list(self.values)
        lo, hi = min(vals), max(vals)
        span = max(hi - lo, 1e-6)
        path = QPainterPath()
        for i, v in enumerate(vals):
            x = i * self.width() / max(1, len(vals) - 1)
            y = self.height() - ((v - lo) / span) * (self.height() - 6) - 3
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.setPen(QPen(self.accent, 1.5))
        p.drawPath(path)


class CaptureDialog(QDialog):
    def __init__(self, accent: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick Capture")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        label = QLabel("QUICK CAPTURE // save a thought, task, link or note")
        label.setStyleSheet(f"color:{accent}; font-weight:700;")
        layout.addWidget(label)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type anything…")
        layout.addWidget(self.input)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        save = QPushButton("Save")
        save.setObjectName("active")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)
        self.input.returnPressed.connect(self.accept)

    def text(self) -> str:
        return self.input.text().strip()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MirzaMK3Window(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = MK3Store()
        self.theme_name = self.store.state.get("theme", "cyan")
        self.theme = THEMES.get(self.theme_name, THEMES["cyan"])
        self.smoother = GestureSmoother()
        self._last_clipboard = ""
        self._cpu_series = deque(maxlen=60)
        self._greeting = self._make_greeting()

        self.setWindowTitle("MIRZA OS // MK3")
        self.resize(1600, 960)
        self.setMinimumSize(1180, 740)

        self._build_ui()
        self._apply_theme()
        self._restore_modes()
        self._wire_clipboard()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_live_data)
        self.timer.start(1000)
        self._refresh_live_data()
        self.store.add_action("MK3 command deck opened")

    # -------------------------- build --------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 8, 12, 10)
        outer.setSpacing(8)

        self.header = self._build_header()
        outer.addWidget(self.header)

        self.nav = self._build_nav()
        outer.addWidget(self.nav)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)

        content = QWidget()
        self.scroll.setWidget(content)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)

        main_row = QHBoxLayout()
        main_row.setSpacing(10)
        self.left_column = self._build_left_column()
        self.center_column = self._build_center_column()
        self.right_column = self._build_right_column()

        main_row.addLayout(self.left_column, 3)
        main_row.addLayout(self.center_column, 5)
        main_row.addLayout(self.right_column, 4)
        self.content_layout.addLayout(main_row)

        self.bottom_modules = self._build_bottom_modules()
        self.content_layout.addLayout(self.bottom_modules)

        self.footer = self._build_footer()
        outer.addWidget(self.footer)

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("hudAlt")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)

        brand = QLabel("MIRZA OS")
        brand.setStyleSheet("font-size:20px; font-weight:700; letter-spacing:2px;")
        mk = QLabel("MK3")
        mk.setObjectName("accent")
        mk.setStyleSheet("font-size:14px; font-weight:800; padding-top:3px;")
        row.addWidget(brand)
        row.addWidget(mk)
        row.addSpacing(18)

        self.system_badge = QLabel("● SYSTEM ONLINE")
        self.system_badge.setStyleSheet(f"color:{SEMANTIC['success']}; font-weight:700;")
        row.addWidget(self.system_badge)

        row.addStretch()

        self.clock_label = QLabel("--:--")
        self.clock_label.setStyleSheet("font-size:19px; font-weight:500;")
        row.addWidget(self.clock_label)

        self.jarvis_badge = QPushButton("JARVIS // IDLE")
        self.jarvis_badge.clicked.connect(self._jarvis_info)
        row.addWidget(self.jarvis_badge)

        self.spider_badge = QPushButton("SPIDER-SENSE // QUIET")
        self.spider_badge.setObjectName("danger")
        row.addWidget(self.spider_badge)

        self.theme_button = QPushButton("STYLE")
        self.theme_button.clicked.connect(self._cycle_theme)
        row.addWidget(self.theme_button)

        self.focus_button = QPushButton("FOCUS")
        self.focus_button.clicked.connect(self._toggle_focus)
        row.addWidget(self.focus_button)

        self.zero_button = QPushButton("ZERO UI")
        self.zero_button.clicked.connect(self._toggle_zero_ui)
        row.addWidget(self.zero_button)

        return frame

    def _build_nav(self) -> QFrame:
        frame = QFrame()
        row = QHBoxLayout(frame)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(6)
        self.nav_buttons: Dict[str, QPushButton] = {}
        for name in ("GENERAL", "WORK", "MOVIE", "BROWSE", "GAME", "VAULT"):
            btn = QPushButton(name)
            if name == "GENERAL":
                btn.setObjectName("active")
            btn.clicked.connect(lambda checked=False, n=name: self._select_mode(n))
            row.addWidget(btn)
            self.nav_buttons[name] = btn
        return frame

    def _build_left_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(10)

        day = HUD("Day Core", "JARVIS // NOW")
        hero = QHBoxLayout()
        self.day_time = QLabel("--:--")
        self.day_time.setObjectName("hero")
        self.day_focus = MetricPill("Focus", "ACTIVE", self.theme["accent"])
        hero.addWidget(self.day_time, 2)
        hero.addWidget(self.day_focus, 1)
        day.add_layout(hero)
        self.greeting_label = QLabel(self._greeting)
        self.greeting_label.setWordWrap(True)
        self.greeting_label.setObjectName("muted")
        day.add_widget(self.greeting_label)
        col.addWidget(day)

        system = HUD("System Health", "LIVE TELEMETRY")
        grid = QGridLayout()
        self.cpu_metric = MetricPill("CPU", "--", SEMANTIC["info"])
        self.ram_metric = MetricPill("RAM", "--", SEMANTIC["analysis"])
        self.disk_metric = MetricPill("Disk", "--", SEMANTIC["warning"])
        self.net_metric = MetricPill("Network", "--", SEMANTIC["success"])
        grid.addWidget(self.cpu_metric, 0, 0)
        grid.addWidget(self.ram_metric, 0, 1)
        grid.addWidget(self.disk_metric, 1, 0)
        grid.addWidget(self.net_metric, 1, 1)
        system.add_layout(grid)
        self.cpu_spark = Sparkline(self.theme["accent"])
        system.add_widget(self.cpu_spark)
        col.addWidget(system)

        devices = HUD("Device Network", "LOCAL NODE MAP")
        self.device_label = QLabel("Scanning local interfaces…")
        self.device_label.setWordWrap(True)
        self.device_label.setObjectName("muted")
        devices.add_widget(self.device_label)
        toggles = QHBoxLayout()
        self.device_buttons: Dict[str, QPushButton] = {}
        for key, label in (("lights", "LIGHTS"), ("audio", "AUDIO"), ("monitor", "MONITOR")):
            b = QPushButton(label)
            b.clicked.connect(lambda checked=False, k=key: self._toggle_device(k))
            toggles.addWidget(b)
            self.device_buttons[key] = b
        devices.add_layout(toggles)
        col.addWidget(devices)

        media = HUD("Quran / Media Capsule", "PLAYBACK")
        title = QLabel("Ready for playback")
        title.setObjectName("accent")
        media.add_widget(title)
        wave = QLabel("▁▂▃▅▇▆▄▂▁  ▂▄▆▇▅▃▂▁")
        wave.setStyleSheet(f"color:{self.theme['accent2']}; font-family:monospace;")
        media.add_widget(wave)
        row = QHBoxLayout()
        row.addWidget(QPushButton("◀"))
        row.addWidget(QPushButton("▶ / ❚❚"))
        row.addWidget(QPushButton("▶"))
        media.add_layout(row)
        col.addWidget(media)

        return col

    def _build_center_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(10)

        self.reactor_frame = QFrame()
        self.reactor_frame.setObjectName("hud")
        reactor_layout = QVBoxLayout(self.reactor_frame)
        reactor_layout.setContentsMargins(8, 8, 8, 8)
        self.reactor = ReactorWidget(self.theme["accent"])
        reactor_layout.addWidget(self.reactor)
        col.addWidget(self.reactor_frame)

        web = HUD("Web Link System", "CONTEXT RELATIONSHIPS")
        self.web_link_label = QLabel(
            "WORK TARGET  ───  PACE  ───  ACTION STACK\n"
            "CLIPBOARD    ───  JARVIS  ───  QUICK CAPTURE\n"
            "SIGNAL       ───  VAULT   ───  ANALYSIS"
        )
        self.web_link_label.setStyleSheet(
            f"font-family:Consolas,monospace; color:{self.theme['muted']};"
        )
        web.add_widget(self.web_link_label)
        col.addWidget(web)

        suggest = HUD("JARVIS Suggestions", "QUIET INTELLIGENCE")
        self.suggestion_label = QLabel("No priority suggestion.")
        self.suggestion_label.setWordWrap(True)
        suggest.add_widget(self.suggestion_label)
        actions = QHBoxLayout()
        capture = QPushButton("QUICK CAPTURE")
        capture.clicked.connect(self._quick_capture)
        undo = QPushButton("SYSTEM REPLAY // UNDO")
        undo.clicked.connect(self._undo_last_action)
        actions.addWidget(capture)
        actions.addWidget(undo)
        suggest.add_layout(actions)
        col.addWidget(suggest)

        return col

    def _build_right_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(10)

        work = HUD("Work Command Centre", "PACE • TARGET • ALLOCATION")
        top = QHBoxLayout()
        self.work_total = QLabel("0 / 400")
        self.work_total.setObjectName("hero")
        self.work_percent = MetricPill("Progress", "0%", self.theme["accent"])
        top.addWidget(self.work_total, 2)
        top.addWidget(self.work_percent, 1)
        work.add_layout(top)

        self.work_bar = TinyBar(self.theme["accent"])
        work.add_widget(self.work_bar)

        self.counter_labels: Dict[str, QLabel] = {}
        work_grid = QGridLayout()
        for idx, key in enumerate(("file", "gp", "pharm", "pa", "tasked", "unmatched", "dup")):
            cell = QFrame()
            cell.setObjectName("hudAlt")
            cell_l = QVBoxLayout(cell)
            cell_l.setContentsMargins(7, 6, 7, 6)
            name = QLabel(key.upper())
            name.setObjectName("muted")
            val = QLabel("0")
            val.setStyleSheet("font-size:17px; font-weight:650;")
            buttons = QHBoxLayout()
            minus = QPushButton("−")
            plus = QPushButton("+")
            minus.setMaximumWidth(30)
            plus.setMaximumWidth(30)
            minus.clicked.connect(lambda checked=False, k=key: self._change_count(k, -1))
            plus.clicked.connect(lambda checked=False, k=key: self._change_count(k, 1))
            buttons.addWidget(minus)
            buttons.addWidget(plus)
            cell_l.addWidget(name)
            cell_l.addWidget(val)
            cell_l.addLayout(buttons)
            self.counter_labels[key] = val
            work_grid.addWidget(cell, idx // 4, idx % 4)
        work.add_layout(work_grid)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("TARGET"))
        self.target_input = QLineEdit()
        self.target_input.setMaximumWidth(90)
        self.target_input.setText(str(self.store.state["work"].get("target", 400)))
        self.target_input.returnPressed.connect(self._set_target)
        target_row.addWidget(self.target_input)
        target_row.addStretch()
        reset = QPushButton("RESET")
        reset.setObjectName("danger")
        reset.clicked.connect(self._reset_work)
        target_row.addWidget(reset)
        work.add_layout(target_row)
        col.addWidget(work)

        mission = HUD("Mission Control", "NEXT UP")
        self.mission_label = QLabel(
            "01  Finish current work target\n"
            "02  Review priority messages\n"
            "03  Check next scheduled item"
        )
        self.mission_label.setObjectName("muted")
        mission.add_widget(self.mission_label)
        col.addWidget(mission)

        clipboard = HUD("Clipboard Intelligence", "CONTEXT DOCK")
        self.clipboard_label = QLabel("Copy something and MK3 will surface it here.")
        self.clipboard_label.setWordWrap(True)
        self.clipboard_label.setObjectName("muted")
        clipboard.add_widget(self.clipboard_label)
        clip_actions = QHBoxLayout()
        open_clip = QPushButton("OPEN LINK")
        open_clip.clicked.connect(self._open_clipboard_if_url)
        capture_clip = QPushButton("SAVE")
        capture_clip.clicked.connect(self._capture_clipboard)
        clip_actions.addWidget(open_clip)
        clip_actions.addWidget(capture_clip)
        clipboard.add_layout(clip_actions)
        col.addWidget(clipboard)

        return col

    def _build_bottom_modules(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        intel = HUD("Live Intel", "SIGNAL FEED")
        self.intel_label = QLabel(
            "SYSTEM   Local telemetry active\n"
            "WORK     Pace engine linked\n"
            "VAULT    Stand-by\n"
            "NETWORK  Local interfaces visible"
        )
        self.intel_label.setObjectName("muted")
        intel.add_widget(self.intel_label)
        row.addWidget(intel, 2)

        activity = HUD("Action Stack", "RECENT ACTIVITY")
        self.activity_label = QLabel("No actions yet.")
        self.activity_label.setObjectName("muted")
        activity.add_widget(self.activity_label)
        row.addWidget(activity, 2)

        privacy = HUD("Privacy / Presence", "CAM • MIC • SCREEN")
        self.privacy_label = QLabel("LOCAL VIEW // privacy guard active")
        self.privacy_label.setStyleSheet(f"color:{SEMANTIC['success']};")
        privacy.add_widget(self.privacy_label)
        self.privacy_checkbox = QCheckBox("Privacy guard")
        self.privacy_checkbox.setChecked(
            self.store.state["device_toggles"].get("privacy", True)
        )
        self.privacy_checkbox.toggled.connect(self._privacy_changed)
        privacy.add_widget(self.privacy_checkbox)
        row.addWidget(privacy, 1)

        return row

    def _build_footer(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("hudAlt")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 6, 12, 6)

        quick = QLabel("QUICK LAUNCH")
        quick.setObjectName("eyebrow")
        row.addWidget(quick)

        links = (
            ("TEAMS", "https://teams.microsoft.com/"),
            ("WHATSAPP", "https://web.whatsapp.com/"),
            ("YOUTUBE", "https://www.youtube.com/"),
            ("GITHUB", "https://github.com/"),
        )
        for label, url in links:
            b = QPushButton(label)
            b.clicked.connect(lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            row.addWidget(b)

        row.addStretch()

        self.hand_status = QLabel("HAND // SMOOTHER READY")
        self.hand_status.setObjectName("accent")
        row.addWidget(self.hand_status)

        self.spatial_status = QLabel("SPATIAL // STANDBY")
        self.spatial_status.setObjectName("muted")
        row.addWidget(self.spatial_status)

        return frame

    # -------------------------- data --------------------------

    def _make_greeting(self) -> str:
        hour = datetime.now().hour
        if hour < 12:
            openings = [
                "Good morning. Systems are quiet and ready.",
                "Morning. Everything is where you left it.",
                "Good morning. Nothing dramatic to report — ideal.",
                "Morning. Command deck restored.",
            ]
        elif hour < 18:
            openings = [
                "Good afternoon. The deck is ready when you are.",
                "Afternoon. I kept the noise to a minimum.",
                "Welcome back. Nothing worth interrupting you over.",
                "Afternoon. Your active thread is restored.",
            ]
        else:
            openings = [
                "Good evening. Systems are standing by.",
                "Evening. Everything important is already surfaced.",
                "Welcome back. The quiet kind of evening, so far.",
                "Evening. I've kept the unnecessary chatter out.",
            ]
        return random.choice(openings)

    def _refresh_live_data(self) -> None:
        now = datetime.now()
        stamp = now.strftime("%H:%M:%S")
        self.clock_label.setText(stamp)
        self.day_time.setText(now.strftime("%H:%M"))

        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage(Path.home().anchor or "/").percent
        net = psutil.net_io_counters()
        net_mb = (net.bytes_sent + net.bytes_recv) / (1024 * 1024)

        self.cpu_metric.value.setText(f"{cpu:.0f}%")
        self.ram_metric.value.setText(f"{mem:.0f}%")
        self.disk_metric.value.setText(f"{disk:.0f}%")
        self.net_metric.value.setText(f"{net_mb:.0f} MB")
        self.cpu_spark.push(cpu)

        # JARVIS state stays compact: no narration.
        jarvis_text = "JARVIS // READY"
        if get_jarvis_state is not None:
            try:
                state = get_jarvis_state().state.value.upper()
                jarvis_text = f"JARVIS // {state}"
            except Exception:
                pass
        self.jarvis_badge.setText(jarvis_text)

        self._refresh_work_ui()
        self._refresh_activity_ui()
        self._refresh_devices()
        self._refresh_spider_sense(cpu, mem)
        self._refresh_suggestion(cpu, mem)

    def _refresh_work_ui(self) -> None:
        work = self.store.state["work"]
        target = max(1, int(work.get("target", 400)))
        # File is the daily headline count; fall back to sum if it's zero.
        headline = int(work.get("file", 0))
        if headline == 0:
            headline = sum(
                int(work.get(k, 0))
                for k in ("gp", "pharm", "pa", "tasked", "unmatched", "dup")
            )
        progress = min(1.0, headline / target)
        self.work_total.setText(f"{headline} / {target}")
        self.work_percent.value.setText(f"{progress * 100:.0f}%")
        self.work_bar.set_value(progress)
        for key, label in self.counter_labels.items():
            label.setText(str(int(work.get(key, 0))))

    def _refresh_activity_ui(self) -> None:
        actions = self.store.state.get("actions", [])
        if not actions:
            self.activity_label.setText("No actions yet.")
            return
        recent = actions[-5:][::-1]
        lines = []
        for item in recent:
            try:
                dt = datetime.fromisoformat(item["time"]).strftime("%H:%M")
            except Exception:
                dt = "--:--"
            lines.append(f"{dt}  {item.get('label', '')}")
        self.activity_label.setText("\n".join(lines))

    def _refresh_devices(self) -> None:
        try:
            host = socket.gethostname()
            interfaces = []
            for name, stats in psutil.net_if_stats().items():
                if stats.isup:
                    interfaces.append(name)
            iface = ", ".join(interfaces[:3]) if interfaces else "no active interface"
            self.device_label.setText(
                f"HOST  {host}\nLINK  {iface}\n"
                f"STATE local-only command node"
            )
        except Exception:
            self.device_label.setText("Local network status unavailable.")

        toggles = self.store.state["device_toggles"]
        for key, button in self.device_buttons.items():
            active = bool(toggles.get(key, False))
            button.setText(f"{button.text().split(' //')[0]} // {'ON' if active else 'OFF'}")
            button.setObjectName("active" if active else "")
            button.style().unpolish(button)
            button.style().polish(button)

    def _refresh_spider_sense(self, cpu: float, mem: float) -> None:
        work = self.store.state["work"]
        target = max(1, int(work.get("target", 400)))
        file_count = int(work.get("file", 0))
        level = 0
        text = "SPIDER-SENSE // QUIET"

        if cpu > 92 or mem > 92:
            level = 3
            text = "SPIDER-SENSE // SYSTEM LOAD"
        elif int(work.get("unmatched", 0)) > 0 or int(work.get("dup", 0)) > 5:
            level = 2
            text = "SPIDER-SENSE // WORK CHECK"
        elif file_count and file_count >= target:
            level = 1
            text = "SPIDER-SENSE // TARGET CLEARED"

        self.spider_badge.setText(text)
        self.reactor.set_alert_level(level)

    def _refresh_suggestion(self, cpu: float, mem: float) -> None:
        work = self.store.state["work"]
        target = max(1, int(work.get("target", 400)))
        current = int(work.get("file", 0))
        remaining = max(0, target - current)

        if cpu > 90:
            text = "System load is high. Non-critical background work should wait."
        elif int(work.get("unmatched", 0)) > 0:
            text = f"{work.get('unmatched')} unmatched item(s) are still open."
        elif current >= target:
            text = "Work target cleared. No need for me to keep mentioning it."
        elif current:
            text = f"{remaining} remaining to target. You're at {(current/target)*100:.0f}%."
        elif self._last_clipboard:
            text = "Clipboard context is available if you want to capture or open it."
        else:
            text = "No priority suggestion. The interface can stay quiet."
        self.suggestion_label.setText(text)

    # -------------------------- actions --------------------------

    def _change_count(self, key: str, delta: int) -> None:
        work = self.store.state["work"]
        before = {"work": dict(work)}
        work[key] = max(0, int(work.get(key, 0)) + delta)
        self.store.add_action(f"{key.upper()} {'+' if delta > 0 else ''}{delta}", before)
        self._refresh_work_ui()

    def _set_target(self) -> None:
        try:
            target = max(1, int(self.target_input.text().strip()))
        except ValueError:
            self.target_input.setText(str(self.store.state["work"].get("target", 400)))
            return
        before = {"work": dict(self.store.state["work"])}
        self.store.state["work"]["target"] = target
        self.store.add_action(f"Work target set to {target}", before)
        self._refresh_work_ui()

    def _reset_work(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset work counters?",
            "Reset all MK3 work counters to zero?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        before = {"work": dict(self.store.state["work"])}
        for key in ("file", "gp", "pharm", "pa", "tasked", "unmatched", "dup"):
            self.store.state["work"][key] = 0
        self.store.add_action("Work counters reset", before)
        self._refresh_work_ui()

    def _undo_last_action(self) -> None:
        actions = self.store.state.get("actions", [])
        for idx in range(len(actions) - 1, -1, -1):
            item = actions[idx]
            before = item.get("before")
            if isinstance(before, dict) and "work" in before:
                self.store.state["work"] = dict(before["work"])
                removed = actions.pop(idx)
                self.store.add_action(f"Replay undo: {removed.get('label', 'change')}")
                self._refresh_work_ui()
                return
        QMessageBox.information(self, "System Replay", "No reversible work action found.")

    def _quick_capture(self) -> None:
        dialog = CaptureDialog(self.theme["accent"], self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.text():
            self.store.add_capture(dialog.text())
            self._refresh_activity_ui()

    def _wire_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(self._clipboard_changed)
        self._clipboard_changed()

    def _clipboard_changed(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text or text == self._last_clipboard:
            return
        self._last_clipboard = text[:1200]
        preview = self._last_clipboard.replace("\n", " ")
        if len(preview) > 180:
            preview = preview[:177] + "…"
        kind = "LINK" if self._looks_like_url(self._last_clipboard) else "TEXT"
        self.clipboard_label.setText(f"{kind} // {preview}")
        self.store.add_action(f"Clipboard {kind.lower()} detected")

    @staticmethod
    def _looks_like_url(text: str) -> bool:
        t = text.strip().lower()
        return t.startswith("http://") or t.startswith("https://")

    def _open_clipboard_if_url(self) -> None:
        if self._looks_like_url(self._last_clipboard):
            QDesktopServices.openUrl(QUrl(self._last_clipboard))
            self.store.add_action("Clipboard link opened")
        else:
            QMessageBox.information(self, "Clipboard", "The current clipboard is not a URL.")

    def _capture_clipboard(self) -> None:
        if not self._last_clipboard:
            return
        self.store.add_capture(self._last_clipboard)
        self._refresh_activity_ui()

    def _toggle_device(self, key: str) -> None:
        toggles = self.store.state["device_toggles"]
        toggles[key] = not bool(toggles.get(key, False))
        self.store.add_action(f"{key.title()} {'on' if toggles[key] else 'off'}")
        self._refresh_devices()

    def _privacy_changed(self, active: bool) -> None:
        self.store.state["device_toggles"]["privacy"] = bool(active)
        self.store.add_action(f"Privacy guard {'enabled' if active else 'disabled'}")
        self.privacy_label.setText(
            "LOCAL VIEW // privacy guard active"
            if active
            else "PRIVACY GUARD // OFF"
        )
        self.privacy_label.setStyleSheet(
            f"color:{SEMANTIC['success'] if active else SEMANTIC['warning']};"
        )

    def _select_mode(self, name: str) -> None:
        for n, b in self.nav_buttons.items():
            b.setObjectName("active" if n == name else "")
            b.style().unpolish(b)
            b.style().polish(b)
        self.store.add_action(f"Mode changed to {name}")
        if name == "VAULT":
            self.reactor.set_alert_level(1)
        self.spatial_status.setText(f"SPATIAL // {name}")

    def _toggle_focus(self) -> None:
        enabled = not bool(self.store.state.get("focus_mode", False))
        self.store.state["focus_mode"] = enabled
        self.store.add_action(f"Focus mode {'enabled' if enabled else 'disabled'}")
        self._apply_focus(enabled)

    def _apply_focus(self, enabled: bool) -> None:
        # Keep command essentials; reduce secondary noise.
        for widget in (
            self.web_link_label.parentWidget(),
            self.intel_label.parentWidget(),
            self.privacy_label.parentWidget(),
        ):
            if widget is not None:
                widget.setVisible(not enabled)
        self.focus_button.setObjectName("active" if enabled else "")
        self.focus_button.style().unpolish(self.focus_button)
        self.focus_button.style().polish(self.focus_button)
        self.day_focus.value.setText("LOCKED" if enabled else "ACTIVE")

    def _toggle_zero_ui(self) -> None:
        enabled = not bool(self.store.state.get("zero_ui", False))
        self.store.state["zero_ui"] = enabled
        self.store.add_action(f"Zero UI {'enabled' if enabled else 'disabled'}")
        self._apply_zero_ui(enabled)

    def _apply_zero_ui(self, enabled: bool) -> None:
        self.nav.setVisible(not enabled)
        self.scroll.setVisible(not enabled)
        self.zero_button.setObjectName("active" if enabled else "")
        self.zero_button.style().unpolish(self.zero_button)
        self.zero_button.style().polish(self.zero_button)
        if enabled:
            self.statusBar().showMessage(
                "ZERO UI active — use the ZERO UI control in the top bar to restore.",
                4000,
            )

    def _restore_modes(self) -> None:
        self._apply_focus(bool(self.store.state.get("focus_mode", False)))
        self._apply_zero_ui(bool(self.store.state.get("zero_ui", False)))

    def _cycle_theme(self) -> None:
        keys = list(THEMES.keys())
        idx = keys.index(self.theme_name) if self.theme_name in keys else 0
        self.theme_name = keys[(idx + 1) % len(keys)]
        self.theme = THEMES[self.theme_name]
        self.store.state["theme"] = self.theme_name
        self.store.add_action(f"Theme changed to {self.theme_name}")
        self._apply_theme()

    def _apply_theme(self) -> None:
        self.setStyleSheet(build_stylesheet(self.theme))
        self.reactor.set_accent(self.theme["accent"])
        self.cpu_spark.set_accent(self.theme["accent"])
        self.work_bar.set_accent(self.theme["accent"])
        self.web_link_label.setStyleSheet(
            f"font-family:Consolas,monospace; color:{self.theme['muted']};"
        )
        self.greeting_label.setStyleSheet(f"color:{self.theme['muted']};")
        self.hand_status.setStyleSheet(
            f"color:{self.theme['accent']}; font-weight:700;"
        )
        self.work_percent.value.setStyleSheet(
            f"font-size:17px; font-weight:650; color:{self.theme['accent']};"
        )
        self.day_focus.value.setStyleSheet(
            f"font-size:17px; font-weight:650; color:{self.theme['accent']};"
        )

    def _jarvis_info(self) -> None:
        QMessageBox.information(
            self,
            "JARVIS // Presence Engine",
            "MK3 keeps JARVIS quiet by default.\n\n"
            "Normal navigation, HUD movement and routine actions stay silent. "
            "Speech should be reserved for direct questions, meaningful changes, "
            "priority alerts and varied session greetings.",
        )

    def closeEvent(self, event) -> None:
        self.store.save()
        event.accept()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Mirza OS MK3")
    window = MirzaMK3Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
