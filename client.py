#!/usr/bin/env python3
"""
Remote Webcam Client Launcher
Connects to a remote webcam server by IP and Port.
Can run the modern Desktop GUI or the lightweight CLI viewer.
"""

import sys
import argparse
from client.api import RemoteWebcamApi


def main():
    parser = argparse.ArgumentParser(
        description="Remote Webcam Client - View and control remote webcam streams."
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="IP address or hostname of the remote server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port of the remote server (default: 8080)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run lightweight OpenCV CLI window instead of desktop GUI",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan local subnet for active Remote Webcam servers and exit",
    )

    args = parser.parse_args()

    if args.scan:
        print(f"Scanning local network for servers on port {args.port}...")
        found = RemoteWebcamApi.scan_local_network(port=args.port)
        if not found:
            print("No Remote Webcam servers found.")
        else:
            print("Discovered Servers:")
            for s in found:
                print(f" • http://{s['ip']}:{s['port']}/")
        sys.exit(0)

    if args.cli:
        from client.cli_viewer import run_cli_viewer
        run_cli_viewer(host=args.host, port=args.port)
    else:
        from client.desktop_gui import run_desktop_client
        run_desktop_client(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
