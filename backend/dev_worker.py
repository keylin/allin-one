"""Dev worker: watch Python files and auto-restart procrastinate worker.

Graceful restart: detects code changes but waits for the current
task queue to drain (up to DRAIN_TIMEOUT) before killing,
so long-running tasks like video downloads aren't interrupted.

Usage:
    python dev_worker.py                 # 启动所有队列 (默认)
    python dev_worker.py pipeline        # 仅 pipeline 队列
    python dev_worker.py scheduled       # 仅 scheduled 队列
"""

import signal
import subprocess
import sys
import time

from watchfiles import watch

WATCH_DIR = "/app/app"
DRAIN_TIMEOUT = 600  # 最多等 10 分钟让当前任务完成

# 队列配置: name → (queues, concurrency)
WORKER_PROFILES = {
    "pipeline":  (["pipeline"],  4),
    "scheduled": (["scheduled"], 2),
}


def _build_cmd(queues: list[str] | None, concurrency: int) -> list[str]:
    queues_arg = repr(queues) if queues else "None"
    return ["python", "-c", f"""
import asyncio
from app.tasks.procrastinate_app import proc_app

async def main():
    async with proc_app.open_async():
        await proc_app.run_worker_async(queues={queues_arg}, concurrency={concurrency})

asyncio.run(main())
"""]


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
    profile = sys.argv[1] if len(sys.argv) > 1 else None

    if profile and profile in WORKER_PROFILES:
        queues, concurrency = WORKER_PROFILES[profile]
        print(f"[dev-worker] Starting {profile} worker: queues={queues}, concurrency={concurrency}", flush=True)
    else:
        queues, concurrency = None, 4
        print(f"[dev-worker] Starting worker: all queues, concurrency={concurrency}", flush=True)

    cmd = _build_cmd(queues, concurrency)
    proc = subprocess.Popen(cmd)
    try:
        for changes in watch(WATCH_DIR, watch_filter=lambda _, path: path.endswith(".py")):
            changed = [c[1] for c in changes]
            print(f"[dev-reload] Changed: {changed}", flush=True)
            graceful_restart(proc)
            proc = subprocess.Popen(cmd)
            print("[dev-reload] Worker restarted.", flush=True)
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        sys.exit(0)


if __name__ == "__main__":
    main()
