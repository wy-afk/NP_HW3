#!/usr/bin/env python3
import argparse
from client import run_client
import json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--user", default="Player")
    parser.add_argument("--room", default="1")
    args = parser.parse_args()

    # run_client returns the final result dict (e.g., {'winners': [...]})
    try:
        result = run_client(args.host, args.port, args.user, args.room)
    except Exception as e:
        # print an ERROR result for callers to consume
        print(json.dumps({"error": str(e)}))
        return

    # Print final result as a single JSON line so launcher can capture it
    try:
        print(json.dumps(result))
    except Exception:
        # fallback: print a simple status
        print(json.dumps({"status": "finished"}))

if __name__ == "__main__":
    main()
