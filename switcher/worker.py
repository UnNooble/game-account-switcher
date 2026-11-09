"""Runs one job on a background thread so the window stays responsive."""
import queue
import threading

from .errors import Cancelled, UserError


def _make_ask(events, replies, cancel):
    """Let the engine ask the window a question (e.g. a 2FA code) and block for the answer."""
    def ask(kind, data):
        events.put(("prompt", {"kind": kind, "data": data}))
        while not cancel.is_set():
            try:
                return replies.get(timeout=0.2)
            except queue.Empty:
                continue
        return None
    return ask


def run(store, job, events, replies, cancel):
    from .log import log
    try:
        from .riot import RiotClient
        from .vault import DPAPI, SessionFiles, Vault
        from .engine import Engine
        from .credentials import Credentials
        from . import log as logmod, VERSION
        import platform
        logmod.setup(store.root)
        log(f"--- app {VERSION}, Windows {platform.version()}")
        riot = RiotClient(store.read()["settings"]["riot_path"])
        vault = Vault(store.root, SessionFiles(riot.data), DPAPI())
        engine = Engine(riot, vault, store, lambda kind, data: events.put((kind, data)), cancel,
                        creds=Credentials(), ask=_make_ask(events, replies, cancel))
        if job.get("save_current"):
            engine.save_current(job["new_label"])
        else:
            engine.run(job.get("profile_id"), job.get("new_label"), job.get("relogin", False), job.get("new_login"))
        events.put(("done", None))
    except Cancelled as e:
        events.put(("cancelled", str(e) or "Stopped. Click any account to continue."))
    except UserError as e:
        log(f"stopped with message: {e}")
        events.put(("error", str(e)))
    except Exception as e:  # never show raw details: they could include file contents
        log(f"unexpected error: {type(e).__name__}")
        events.put(("error", "Something unexpected went wrong (" + type(e).__name__ + "). "
                    "Close Riot and try again. If a switch was interrupted it is repaired automatically next time."))
    finally:
        events.put(("finished", None))


def start(store, events, replies, **job):
    cancel = threading.Event()
    t = threading.Thread(target=run, args=(store, job, events, replies, cancel), daemon=True)
    t.start()
    return t, cancel
