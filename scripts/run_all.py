#!/usr/bin/env python3
import sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def run_agent():
    from paper_trading.agent import PaperTradingAgent
    try:
        agent = PaperTradingAgent()
        agent.start()
    except Exception as e:
        print(f"Agent error: {e}")

def run_dashboard():
    time.sleep(2)  # Let agent initialise first
    try:
        import uvicorn
        uvicorn.run("dashboard.app:app", host="0.0.0.0", port=8420, log_level="warning")
    except Exception as e:
        print(f"Dashboard error: {e}")

def get_local_ip():
    import socket
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80)); ip=s.getsockname()[0]; s.close(); return ip
    except: return "unknown"

if __name__ == "__main__":
    ip = get_local_ip()
    print(f"\n{'='*55}")
    print(f"  AtlasFX — Starting all systems")
    print(f"  Dashboard : http://localhost:8420")
    print(f"  Mobile    : http://{ip}:8420")
    print(f"  Agent     : scanning every hour")
    print(f"  Ctrl+C to stop everything")
    print(f"{'='*55}\n")

    t = threading.Thread(target=run_dashboard, daemon=True)
    t.start()
    run_agent()
