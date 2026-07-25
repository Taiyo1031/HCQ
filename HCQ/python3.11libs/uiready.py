"""Interactive Houdini startup hook for HCQ."""

try:
    from hcq import app

    app.startup()
except Exception:
    import traceback

    traceback.print_exc()
