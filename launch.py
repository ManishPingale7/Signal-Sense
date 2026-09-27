"""Start the local app, or reuse its running instance without a port collision."""
import argparse
import getpass
import json
import os
import socket
import urllib.request
from pathlib import Path
from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--demo", action="store_true", help="Browse saved demo without an API key")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535.")
    url = f"http://127.0.0.1:{args.port}"
    with socket.socket() as probe:
        occupied = probe.connect_ex(("127.0.0.1", args.port)) == 0
    if occupied:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=2) as response:
                running = json.load(response)
            if running.get("app") == "signal-and-sense":
                print("Signal & Sense is already running.")
                print(url + ("/?demo=1" if args.demo else ""))
                print("After code changes, stop the existing server with Ctrl+C and start again.")
                return
        except Exception:
            pass
        print(f"Port {args.port} is occupied. Stop the previous app, or use .\\Start.ps1 -Port {args.port + 1}")
        return
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    if not os.environ.get("GEMINI_API_KEY") and not args.demo:
        try:
            key = getpass.getpass("Gemini API key (hidden; Enter to browse saved briefings): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nStartup cancelled.")
            return
        if key:
            os.environ["GEMINI_API_KEY"] = key
            del key
    import uvicorn
    from app import app
    print("Open " + url + ("/?demo=1" if args.demo else "") + " in your browser. Ctrl+C stops the server.")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
