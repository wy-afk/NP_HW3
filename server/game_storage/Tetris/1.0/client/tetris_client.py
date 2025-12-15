#!/usr/bin/env python3
import argparse
from client import run_client

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--user", default="Player")
    parser.add_argument("--room", default="1")
    args = parser.parse_args()

    run_client(args.host, args.port, args.user, args.room)

if __name__ == "__main__":
    main()
