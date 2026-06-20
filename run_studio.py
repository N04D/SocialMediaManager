from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent


class ProcessStreamer(threading.Thread):
    def __init__(self, prefix: str, stream) -> None:
        super().__init__(daemon=True)
        self.prefix = prefix
        self.stream = stream

    def run(self) -> None:
        for line in iter(self.stream.readline, ""):
            sys.stdout.write(f"[{self.prefix}] {line}")
            sys.stdout.flush()



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local dashboard and persistent LinkedIn worker together.")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    parser.add_argument("--port", type=int, default=8080, help="Dashboard port")
    return parser.parse_args()



def spawn(name: str, cmd: list[str]) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        cmd,
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    ProcessStreamer(name, process.stdout).start()
    return process



def terminate_process(process: subprocess.Popen[str], *, timeout_seconds: float = 8.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)



def main() -> int:
    args = parse_args()
    dashboard_cmd = [sys.executable, str(ROOT_DIR / 'dashboard.py'), '--config', args.config, '--host', args.host, '--port', str(args.port)]
    worker_cmd = [sys.executable, str(ROOT_DIR / 'worker.py'), '--config', args.config, '--channel-jobs-only', '--channel-id', 'linkedin']

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    dashboard = spawn('dashboard', dashboard_cmd)
    worker = spawn('linkedin-worker', worker_cmd)
    processes = [dashboard, worker]

    try:
        time.sleep(1.0)
        for process in processes:
            if process.poll() not in {None, 0}:
                return process.returncode or 1
        while not stop_event.is_set():
            for process in processes:
                if process.poll() not in {None, 0}:
                    stop_event.set()
                    return process.returncode or 1
            time.sleep(0.5)
    finally:
        for process in reversed(processes):
            terminate_process(process)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
