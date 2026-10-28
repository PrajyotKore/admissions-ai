#!/usr/bin/env python3
"""
Admissions AI - Unified Demo Runner
----------------------------------
Launches the FastAPI backend and Next.js frontend concurrently with
health checks, database auto-seeding, clean process shutdown, and automatic
browser launch.

Usage:
    python run_demo.py
    python run_demo.py --no-browser
    python run_demo.py --reseed
"""

import argparse
import atexit
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
IS_WINDOWS = platform.system() == "Windows"

# ANSI Colors for terminal output
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

processes: list[subprocess.Popen] = []
shutdown_initiated = False


def log(prefix: str, msg: str, color: str = ""):
    timestamp = time.strftime("%H:%M:%S")
    print(f"{color}[{timestamp}] [{prefix}]{RESET} {msg}", flush=True)


def find_python() -> str:
    """Find virtualenv python or fallback to sys.executable."""
    if IS_WINDOWS:
        venv_py = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = BACKEND_DIR / ".venv" / "bin" / "python"

    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def find_npm() -> str:
    """Find npm executable."""
    npm_cmd = "npm.cmd" if IS_WINDOWS else "npm"
    found = shutil.which(npm_cmd) or shutil.which("npm")
    if not found:
        log("Error", f"npm not found in PATH. Please install Node.js (v18+).", RED)
        sys.exit(1)
    return found


def kill_process_tree(p: subprocess.Popen):
    """Cleanly terminate process and all child processes on Windows/Unix."""
    try:
        if p.poll() is not None:
            return
        if IS_WINDOWS:
            # Use taskkill to kill the whole process tree (/T) forcefully (/F)
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            p.terminate()
            p.wait(timeout=3)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def shutdown():
    """Terminate all running sub-processes."""
    global shutdown_initiated
    if shutdown_initiated:
        return
    shutdown_initiated = True
    print()
    log("Demo", "Stopping Admissions AI services cleanly...", YELLOW)
    for p in processes:
        kill_process_tree(p)
    log("Demo", "All processes stopped. Thank you!", GREEN)


def signal_handler(sig, frame):
    shutdown()
    sys.exit(0)


def stream_output(pipe, prefix: str, color: str):
    """Stream process stdout/stderr line-by-line to console."""
    try:
        for line in iter(pipe.readline, ""):
            if not line:
                break
            line_str = line.strip()
            # Suppress noisy heartbeat logs
            if line_str and not line_str.startswith("INFO:     127.0.0.1:"):
                log(prefix, line_str, color)
    except Exception:
        pass


def wait_for_service(url: str, name: str, timeout_seconds: int = 40) -> bool:
    """Poll URL until status 200 or timeout."""
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HealthCheck"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status in (200, 304):
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def free_stale_ports(ports: list[int]):
    """Terminate existing processes on target ports to avoid EADDRINUSE on Windows."""
    if not IS_WINDOWS:
        return
    for port in ports:
        try:
            cmd = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
            res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
            for line in res.stdout.strip().splitlines():
                pid = line.strip()
                if pid and pid.isdigit() and int(pid) > 0 and int(pid) != os.getpid():
                    subprocess.run(["taskkill", "/F", "/PID", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def seed_database_if_needed(py_bin: str, force_reseed: bool = False):
    db_file = BACKEND_DIR / "dev.db"
    if force_reseed or not db_file.exists():
        log("Database", "Seeding database with demo organization, counsellors, and student leads...", CYAN)
        res = subprocess.run([py_bin, "-m", "app.seed"], cwd=str(BACKEND_DIR))
        if res.returncode == 0:
            log("Database", "Seed completed successfully.", GREEN)
        else:
            log("Database", "Seed warning: exited with non-zero code.", YELLOW)


def print_banner(backend_port: int, frontend_port: int):
    print("\n" + "=" * 70, flush=True)
    print(f"{BOLD}{CYAN}      🎓 ADMISSIONS AI — MULTI-TENANT CRM & TELEPHONY PLATFORM{RESET}", flush=True)
    print("=" * 70, flush=True)
    print(f" {BOLD}Frontend Dashboard:{RESET}     {GREEN}http://localhost:{frontend_port}{RESET}")
    print(f" {BOLD}Backend API Docs:{RESET}       {GREEN}http://localhost:{backend_port}/docs{RESET}")
    print(f" {BOLD}Public Chat Widget:{RESET}     {CYAN}http://localhost:{frontend_port}/widget/chat?org=497f28de-ae92-4049-a931-d4ce6168cc76{RESET}")
    print(f" {BOLD}Public Lead Form:{RESET}       {CYAN}http://localhost:{frontend_port}/widget/form?org=497f28de-ae92-4049-a931-d4ce6168cc76{RESET}")
    print("-" * 70, flush=True)
    print(f" {BOLD}Default Demo Credentials:{RESET}")
    print(f"   • Owner:       {YELLOW}owner@demo.example{RESET}       / {YELLOW}demo-password-123{RESET}")
    print(f"   • Counsellor:  {YELLOW}counsellor@demo.example{RESET}  / {YELLOW}demo-password-123{RESET}")
    print("=" * 70)
    print(f"{CYAN}Press Ctrl+C at any time to shut down all services gracefully.{RESET}\n", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Run Admissions AI Full Demo Stack")
    parser.add_argument("--backend-port", type=int, default=8000, help="Backend port (default: 8000)")
    parser.add_argument("--frontend-port", type=int, default=3000, help="Frontend port (default: 3000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the browser")
    parser.add_argument("--reseed", action="store_true", help="Force re-seed database before starting")
    args = parser.parse_args()

    # Register exit handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(shutdown)

    # Pre-flight
    free_stale_ports([args.backend_port, args.frontend_port])
    python_bin = find_python()
    npm_bin = find_npm()

    log("Setup", f"Using Python: {python_bin}")
    log("Setup", f"Using npm: {npm_bin}")

    # Seed data
    seed_database_if_needed(python_bin, force_reseed=args.reseed)

    # 1. Start Backend
    backend_cmd = [
        python_bin,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--port",
        str(args.backend_port),
    ]
    log("Backend", f"Starting FastAPI server on port {args.backend_port}...", CYAN)
    p_backend = subprocess.Popen(
        backend_cmd,
        cwd=str(BACKEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    processes.append(p_backend)
    t_back = threading.Thread(target=stream_output, args=(p_backend.stdout, "Backend", CYAN), daemon=True)
    t_back.start()

    # 2. Start Frontend
    frontend_cmd = [npm_bin, "run", "dev", "--", "-p", str(args.frontend_port)]
    log("Frontend", f"Starting Next.js App Router on port {args.frontend_port}...", MAGENTA)
    p_frontend = subprocess.Popen(
        frontend_cmd,
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    processes.append(p_frontend)
    t_front = threading.Thread(target=stream_output, args=(p_frontend.stdout, "Frontend", MAGENTA), daemon=True)
    t_front.start()

    # 3. Wait for services to be healthy
    log("Health", "Waiting for backend API readiness...", YELLOW)
    backend_ready = wait_for_service(f"http://localhost:{args.backend_port}/api/health", "Backend", timeout_seconds=25)
    if backend_ready:
        log("Health", f"Backend healthy at http://localhost:{args.backend_port}/api/health", GREEN)
    else:
        log("Health", "Backend health check timed out; proceeding anyway.", YELLOW)

    log("Health", "Waiting for frontend web readiness...", YELLOW)
    frontend_ready = wait_for_service(f"http://localhost:{args.frontend_port}/login", "Frontend", timeout_seconds=30)
    if frontend_ready:
        log("Health", f"Frontend ready at http://localhost:{args.frontend_port}", GREEN)

    # 4. Show Banner
    print_banner(args.backend_port, args.frontend_port)

    # 5. Open browser
    if not args.no_browser:
        time.sleep(1)
        webbrowser.open(f"http://localhost:{args.frontend_port}/login")

    # Keep main thread alive until Ctrl+C
    try:
        while True:
            time.sleep(1)
            # Check if any process died unexpectedly
            if p_backend.poll() is not None:
                log("Backend", f"Backend exited unexpectedly with code {p_backend.poll()}", RED)
                break
            if p_frontend.poll() is not None:
                log("Frontend", f"Frontend exited unexpectedly with code {p_frontend.poll()}", RED)
                break
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    main()
