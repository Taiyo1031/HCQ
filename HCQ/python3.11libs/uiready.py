"""Interactive Houdini startup hook for HCQ."""

try:
    import hou
    import hcq_update_bootstrap

    hcq_update_bootstrap.apply_pending(hou_module=hou)

    from hcq import app

    app.startup()
except Exception:
    import traceback

    traceback.print_exc()
