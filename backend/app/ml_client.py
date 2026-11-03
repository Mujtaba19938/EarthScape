"""Runs model training in Anaconda's Python, which has the ML libraries the API doesn't need."""
import os
import subprocess
import threading
from pathlib import Path

from . import config
from .notifications import notify

ML_DIR = config.ROOT_DIR / "ml"
TRAINING_TIMEOUT_SECONDS = 1800

_lock = threading.Lock()


def is_running():
    return _lock.locked()


def _environment():
    python_dir = Path(config.ML_PYTHON).parent
    paths = [python_dir, python_dir / "Library" / "bin", python_dir / "Scripts"]
    return dict(
        os.environ,
        PATH=os.pathsep.join([str(path) for path in paths] + [os.environ.get("PATH", "")]),
        MONGO_URI=config.MONGO_URI,
        MONGO_DB=config.MONGO_DB,
    )


def _run_training(username):
    command = [config.ML_PYTHON, "-W", "ignore", str(ML_DIR / "train_models.py"), "--triggered-by", username]
    try:
        result = subprocess.run(command, cwd=str(ML_DIR), env=_environment(), capture_output=True, text=True,
                                errors="replace", timeout=TRAINING_TIMEOUT_SECONDS)
        if result.returncode == 0:
            notify("Models retrained (started by %s)." % username)
        else:
            lines = result.stderr.strip().splitlines()
            notify("Model training failed: %s" % (lines[-1] if lines else "no error message"))
    except (OSError, subprocess.SubprocessError) as error:
        notify("Model training failed: %s" % error)
    finally:
        _lock.release()


def start_training(username):
    """Starts training in the background. Returns False if it is already running."""
    if not _lock.acquire(blocking=False):
        return False
    threading.Thread(target=_run_training, args=(username,), daemon=True).start()
    return True
