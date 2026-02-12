"""Dev worker: watch Python files and auto-restart huey_consumer.

Graceful restart: detects code changes but waits for the current
huey task queue to drain (up to DRAIN_TIMEOUT) before killing,
so long-running tasks like video downloads aren't interrupted.
"""

import signal
import subprocess
import sys
import time

from watchfiles import watch

CMD = ["huey_consumer", "app.tasks.huey_instance.huey", "-w", "4", "-k", "thread"]
WATCH_DIR = "/app/app"
DRAIN_TIMEOUT = 600  # 最多等 10 分钟让当前任务完成


def has_running_tasks():
    """Check if any pipeline steps are currently running."""
    try:
        from app.core.database import SessionLocal
        from app.models.pipeline import PipelineStep, StepStatus
        with SessionLocal() as db:
            count = db.query(PipelineStep).filter(
                PipelineStep.status == StepStatus.RUNNING.value
            ).count()
            return count > 0
    except Exception:
        return False


def graceful_restart(proc):
    """Wait for running tasks to finish, then restart."""
    if has_running_tasks():
        print(f"[dev-reload] Tasks running, waiting up to {DRAIN_TIMEOUT}s...", flush=True)
        deadline = time.time() + DRAIN_TIMEOUT
        while time.time() < deadline and has_running_tasks():
            time.sleep(5)
        if has_running_tasks():
            print("[dev-reload] Drain timeout, force restarting.", flush=True)
        else:
            print("[dev-reload] Tasks drained, restarting.", flush=True)

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def main():
    proc = subprocess.Popen(CMD)
    try:
        for changes in watch(WATCH_DIR, watch_filter=lambda _, path: path.endswith(".py")):
            changed = [c[1] for c in changes]
            print(f"[dev-reload] Changed: {changed}", flush=True)
            graceful_restart(proc)
            proc = subprocess.Popen(CMD)
            print("[dev-reload] Worker restarted.", flush=True)
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        sys.exit(0)


if __name__ == "__main__":
    main()
