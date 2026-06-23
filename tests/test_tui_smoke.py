import importlib


def test_tui_modules_import():
    for name in ("controller", "monitor", "app", "view"):
        importlib.import_module(f"lpk25.tui.{name}")


def test_app_exposes_run_and_dispatch():
    from lpk25.tui import app
    assert callable(app.run)
    assert callable(app.dispatch)


def test_view_exposes_draw_and_overlays():
    from lpk25.tui import view
    for fn in ("draw", "prompt", "choose", "confirm"):
        assert callable(getattr(view, fn))
