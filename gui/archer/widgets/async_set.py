"""
Helpers for safely running daemon setter calls from a GTK signal handler.

The previous pattern across pages was:

    threading.Thread(
        target=lambda: self.client.set_X(value),
        daemon=True,
    ).start()

That fired-and-forgot the result, so a daemon-side failure (or an
authorization denial) left the UI control showing the requested value
even though the hardware never changed. async_set captures the result
dict and, on failure, runs an `on_failure(error_msg)` callback on the
GLib main thread — typically the page reverts the control and the
window shows a toast.
"""

import threading

from gi.repository import GLib


def async_set(setter_fn, args=None, kwargs=None,
              on_success=None, on_failure=None):
    """Run `setter_fn(*args, **kwargs)` on a daemon thread.

    setter_fn returns the standard {"success": bool, "error": str?, ...}
    dict that ArcherClient already returns. Both callbacks are dispatched
    via GLib.idle_add so they always run on the main thread.

    on_success(data_dict)   — invoked with resp.get("data", {}) on success.
    on_failure(error_str)   — invoked with resp.get("error") on failure
                              (or a generic message if absent).
    """
    args = args or ()
    kwargs = kwargs or {}

    def _runner():
        try:
            resp = setter_fn(*args, **kwargs)
        except Exception as e:
            if on_failure:
                GLib.idle_add(on_failure, f"{e}")
            return
        if not isinstance(resp, dict):
            if on_failure:
                GLib.idle_add(on_failure, "Unexpected daemon response")
            return
        if resp.get("success"):
            if on_success:
                GLib.idle_add(on_success, resp.get("data", {}))
        else:
            if on_failure:
                msg = resp.get("error") or "Daemon refused the request"
                GLib.idle_add(on_failure, msg)

    threading.Thread(target=_runner, daemon=True).start()
