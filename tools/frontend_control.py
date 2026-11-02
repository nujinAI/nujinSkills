#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess
import time
import urllib.request
from pathlib import Path

# Ensure modern Node.js is in PATH if nvm is available
def setup_node_path():
    # Prioritize /snap/bin if available for Node 22+
    snap_bin = "/snap/bin"
    if os.path.exists(snap_bin) and snap_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{snap_bin}:{os.environ.get('PATH', '')}"

    nvm_node_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_node_dir.exists():
        # Find latest node version
        versions = sorted([d for d in nvm_node_dir.iterdir() if d.is_dir()], key=lambda x: x.name, reverse=True)
        if versions:
            latest_node_bin = str(versions[0] / "bin")
            if latest_node_bin not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{latest_node_bin}:{os.environ.get('PATH', '')}"

setup_node_path()

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
PID_FILE = ROOT_DIR / ".frontend.pid"
LOG_FILE = ROOT_DIR / "frontend_server.log"
SERVICE_NAME = "nujin-frontend.service"

def has_systemd_service() -> bool:
    return os.path.exists(f"/etc/systemd/system/{SERVICE_NAME}")

import ssl

def check_status(port: int = 3000):
    for scheme in ["https", "http"]:
        url = f"{scheme}://127.0.0.1:{port}"
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with opener.open(req, timeout=3) as resp:
                print(f"[FrontendControl] ONLINE ({scheme.upper()} Port {port}, Status {resp.status})")
                return True
        except Exception:
            continue
    print(f"[FrontendControl] OFFLINE (Port {port})")
    return False

def build_frontend():
    print(f"[FrontendControl] Using Node version: {subprocess.getoutput('node --version')}")
    print(f"[FrontendControl] Installing npm dependencies & building UI in {FRONTEND_DIR}...")
    
    if not (FRONTEND_DIR / "node_modules").exists():
        subprocess.run(["npm", "install"], cwd=str(FRONTEND_DIR), check=True, env=os.environ)
        
    subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND_DIR), check=True, env=os.environ)
    print("[FrontendControl] Frontend build completed successfully!")

def start_frontend(port: int, daemon: bool):
    if check_status(port):
        print(f"[FrontendControl] Frontend is already running on port {port}.")
        return

    if has_systemd_service() and daemon:
        print(f"[FrontendControl] Starting {SERVICE_NAME} via systemd...")
        subprocess.run(["sudo", "systemctl", "start", SERVICE_NAME], check=True)
        time.sleep(2)
        check_status(port)
        return

    if not (FRONTEND_DIR / "node_modules").exists():
        print("[FrontendControl] Installing dependencies first...")
        subprocess.run(["npm", "install"], cwd=str(FRONTEND_DIR), check=True, env=os.environ)

    cmd = ["npx", "vite", "preview", "--port", str(port), "--host"]
    print(f"[FrontendControl] Using Node version: {subprocess.getoutput('node --version')}")
    print(f"[FrontendControl] Starting Vite Preview Server on port {port}...")
    
    if daemon:
        log_f = open(str(LOG_FILE), "a")
        proc = subprocess.Popen(
            cmd,
            cwd=str(FRONTEND_DIR),
            stdout=log_f,
            stderr=log_f,
            env=os.environ,
            preexec_fn=os.setsid
        )
        with open(str(PID_FILE), "w") as f:
            f.write(str(proc.pid))
        print(f"[FrontendControl] Frontend started in background with PID {proc.pid}. Logs: {LOG_FILE.name}")
        time.sleep(3)
        check_status(port)
    else:
        try:
            subprocess.run(cmd, cwd=str(FRONTEND_DIR), env=os.environ)
        except KeyboardInterrupt:
            print("\n[FrontendControl] Frontend stopped by user.")

def stop_frontend():
    if has_systemd_service():
        print(f"[FrontendControl] Stopping {SERVICE_NAME} via systemd...")
        subprocess.run(["sudo", "systemctl", "stop", SERVICE_NAME])

    if PID_FILE.exists():
        try:
            with open(str(PID_FILE), "r") as f:
                pid = int(f.read().strip())
            try:
                os.killpg(os.getpgid(pid), 9)
                print(f"[FrontendControl] Killed process group for PID {pid}")
            except Exception:
                os.kill(pid, 9)
                print(f"[FrontendControl] Killed process with PID {pid}")
            PID_FILE.unlink(missing_ok=True)
        except Exception as e:
            print(f"[FrontendControl] Failed to stop frontend process: {e}")
            PID_FILE.unlink(missing_ok=True)
    else:
        print("[FrontendControl] No active PID file found.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Frontend UI Control CLI")
    parser.add_argument("action", choices=["build", "start", "stop", "status"], help="Action to execute")
    parser.add_argument("--port", type=int, default=3000, help="Port (default: 3000)")
    parser.add_argument("--daemon", action="store_true", help="Run in background daemon mode")
    args = parser.parse_args()

    if args.action == "build":
        build_frontend()
    elif args.action == "start":
        start_frontend(args.port, args.daemon)
    elif args.action == "stop":
        stop_frontend()
    elif args.action == "status":
        check_status(args.port)
