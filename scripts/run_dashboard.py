#!/usr/bin/env python3
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def get_local_ip():
    import socket
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80))
        ip=s.getsockname()[0]; s.close(); return ip
    except: return "unknown"

def main():
    parser=argparse.ArgumentParser(description="AtlasFX Dashboard")
    parser.add_argument("--host",default="0.0.0.0")
    parser.add_argument("--port",type=int,default=8420)
    args=parser.parse_args()
    try: import uvicorn
    except ImportError:
        print("\n Run: pip install uvicorn\n"); sys.exit(1)
    ip=get_local_ip()
    print(f"\n====================================================")
    print(f"  AtlasFX Dashboard")
    print(f"  Local  : http://localhost:{args.port}")
    print(f"  Mobile : http://{ip}:{args.port}")
    print(f"  Ctrl+C to stop")
    print(f"====================================================\n")
    uvicorn.run("dashboard.app:app",host=args.host,port=args.port,log_level="warning")

if __name__=="__main__":
    main()
