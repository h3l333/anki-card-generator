"""Start Postgres (Docker), the backend, and the frontend together for local dev.

Usage: python scripts/dev.py    (from anywhere; paths are resolved relative to this file)

Stops the backend and frontend on Ctrl+C. Does NOT stop the Postgres container -
it has `restart: unless-stopped` and no teardown step is documented for this project;
run `docker compose down` yourself if you want to stop it too.

See README.md "Usage" / CLAUDE.md "Running it" for what each piece does individually.
"""
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    print("Starting Postgres container (docker compose up -d)...")
    subprocess.run(["docker", "compose", "up", "-d"], cwd=REPO_ROOT, check=True)

    print("Starting backend (uvicorn) on port 5000...")
    backend = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "backend.main:app",
            "--reload", "--port", "5000", "--env-file", ".env",
        ],
        cwd=REPO_ROOT,
    )

    print("Starting frontend (http.server) on port 8080...")
    frontend = subprocess.Popen(
        [sys.executable, "-m", "http.server", "8080", "--directory", "frontend"],
        cwd=REPO_ROOT,
    )

    procs = {"backend": backend, "frontend": frontend}

    try:
        while True:
            for name, proc in procs.items():
                code = proc.poll()
                if code is not None:
                    print(f"\n{name} exited on its own (code {code}); stopping the other process.")
                    _terminate_all(p for n, p in procs.items() if n != name)
                    return 1
            time.sleep(1)
    except KeyboardInterrupt:
        print(
            "\nStopping backend and frontend "
            "(Postgres container keeps running - `docker compose down` to stop it too)..."
        )
        _terminate_all(procs.values())
        return 0


def _terminate_all(procs) -> None:
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.terminate()
        except OSError:
            pass
    for proc in procs:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
