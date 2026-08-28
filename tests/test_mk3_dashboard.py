"""Lightweight tests for the Mirza OS MK3 dashboard primitives."""

from desktop_app.mk3_dashboard import GestureSmoother, THEMES


def test_gesture_smoother_initialises_at_first_point():
    smoother = GestureSmoother()
    point = smoother.update(0.25, 0.75, 1 / 60)
    assert point.x == 0.25
    assert point.y == 0.75


def test_gesture_smoother_suppresses_micro_jitter():
    smoother = GestureSmoother(dead_zone=0.01)
    first = smoother.update(0.5, 0.5, 1 / 60)
    second = smoother.update(0.504, 0.503, 1 / 60)
    assert second.x == first.x
    assert second.y == first.y


def test_gesture_smoother_tracks_deliberate_motion():
    smoother = GestureSmoother()
    smoother.update(0.1, 0.1, 1 / 60)
    point = smoother.update(0.9, 0.8, 1 / 60)
    assert point.x > 0.1
    assert point.y > 0.1
    assert point.x < 0.9
    assert point.y < 0.8


def test_mk3_has_six_premium_theme_profiles():
    assert {"cyan", "amber", "green", "purple", "crimson", "ice"}.issubset(THEMES)
