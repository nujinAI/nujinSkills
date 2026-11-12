#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess
import time
import urllib.request
import json

PID_FILE = ".server.pid"
SERVICE_NAME = "nujin-backend.service"

def has_systemd_service() -> bool:
    return os.path.exists(f"/etc/systemd/system/{SERVICE_NAME}")

def get_pid() -> int:
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                return int(f.read().strip())
        except Exception:
            return 0
    return 0

def check_status(port: int = 8000):
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"[ServerControl] ONLINE (Port {port})")
            print(json.dumps(data, indent=2))
            return True
    except Exception:
        print(f"[ServerControl] OFFLINE (Port {port})")
        return False

def start_server(host: str, port: int, daemon: bool):
    if check_status(port):
        print(f"[ServerControl] Server is already running on port {port}.")
        return

    if has_systemd_service() and daemon:
        print(f"[ServerControl] Starting {SERVICE_NAME} via systemd...")
        subprocess.run(["sudo", "systemctl", "start", SERVICE_NAME], check=True)
        time.sleep(2)
        check_status(port)
        return

    venv_python = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "python"))
    python_bin = venv_python if os.path.exists(venv_python) else sys.executable

    cmd = [
        python_bin, "-m", "uvicorn", "server.main:app",
        "--host", host,
        "--port", str(port)
    ]
    if not daemon:
        cmd.extend(["--reload", "--reload-dir", "server", "--reload-dir", "strategies"])
    
    print(f"[ServerControl] Launching Telemetry Server & Telegram Gateway on {host}:{port} with {python_bin}...")
    
    if daemon:
        proc = subprocess.Popen(
            cmd,
            stdout=open("server.log", "a"),
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid
        )
        with open(PID_FILE, "w") as f:
            f.write(str(proc.pid))
        print(f"[ServerControl] Server started in background with PID {proc.pid}. Logs: server.log")
        time.sleep(2)
        check_status(port)
    else:
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            print("\n[ServerControl] Server stopped by user.")

def stop_server():
    if has_systemd_service():
        print(f"[ServerControl] Stopping {SERVICE_NAME} via systemd...")
        subprocess.run(["sudo", "systemctl", "stop", SERVICE_NAME])

    pid = get_pid()
    if pid > 0:
        try:
            os.killpg(os.getpgid(pid), 9)
            print(f"[ServerControl] Killed process group for PID {pid}")
        except Exception:
            try:
                os.kill(pid, 9)
                print(f"[ServerControl] Killed process with PID {pid}")
            except Exception as e:
                print(f"[ServerControl] Failed to kill PID {pid}: {e}")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

    # Clean any lingering rogue uvicorn on port 8000
    try:
        res = subprocess.getoutput("lsof -t -i:8000")
        for p in res.split():
            if p.strip() and int(p.strip()) != os.getpid():
                os.kill(int(p.strip()), 9)
                print(f"[ServerControl] Cleaned lingering process {p} on port 8000")
    except Exception:
        pass

def restart_server(host: str, port: int):
    print(f"[ServerControl] Restarting server...")
    stop_server()
    time.sleep(1)
    if has_systemd_service():
        subprocess.run(["sudo", "systemctl", "restart", SERVICE_NAME], check=True)
        time.sleep(2)
        check_status(port)
    else:
        start_server(host, port, daemon=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telemetry Server Control CLI")
    parser.add_argument("action", choices=["start", "stop", "restart", "status"], help="Action to execute")
    parser.add_argument("--host", default="0.0.0.0", help="Host IP (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--daemon", action="store_true", help="Run in background daemon mode")
    args = parser.parse_args()

    if args.action == "start":
        start_server(args.host, args.port, args.daemon)
    elif args.action == "stop":
        stop_server()
    elif args.action == "restart":
        restart_server(args.host, args.port)
    elif args.action == "status":
        check_status(args.port)
