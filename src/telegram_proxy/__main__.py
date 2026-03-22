# telegram_proxy/__main__.py
"""CLI entry point for standalone/service mode.

Usage:
    python -m telegram_proxy --port 1353 --mode socks5
    python -m telegram_proxy --port 1353
    python -m telegram_proxy --mode both
"""

import argparse
import asyncio
import logging
import signal
import sys

from telegram_proxy.wss_proxy import TelegramWSProxy


def main():
    parser = argparse.ArgumentParser(
        description="Telegram WebSocket Proxy — bypass IP blocking",
    )
    parser.add_argument(
        "--port", type=int, default=1353,
        help="SOCKS5 listen port (default: 1353)",
    )
    parser.add_argument(
        "--mode", choices=["socks5"], default="socks5",
        help="Proxy mode (default: socks5)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    proxy = TelegramWSProxy(
        port=args.port,
        mode=args.mode,
        on_log=lambda msg: print(f"[TG-PROXY] {msg}"),
    )

    async def run():
        await proxy.start()

        # Handle graceful shutdown
        stop_event = asyncio.Event()

        def on_signal():
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, on_signal)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        # On Windows, use Ctrl+C via KeyboardInterrupt
        try:
            await stop_event.wait()
        except (KeyboardInterrupt, SystemExit):
            pass

        await proxy.stop()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
