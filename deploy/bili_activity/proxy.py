#!/usr/bin/env python3
"""Forward a private Docker bridge address to the local SSH reverse tunnel."""
import argparse
import asyncio
import ipaddress


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, ConnectionError):
            pass


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", default="172.18.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    host = ipaddress.ip_address(args.listen_host)
    if not host.is_private or host.is_loopback or host.is_unspecified or host.is_multicast:
        raise SystemExit("listen-host must be a specific private Docker bridge address")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port must be between 1024 and 65535")

    async def handle(reader, writer):
        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", args.port), timeout=5)
            tasks = [asyncio.create_task(pipe(reader, remote_writer)),
                     asyncio.create_task(pipe(remote_reader, writer))]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (OSError, TimeoutError):
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    server = await asyncio.start_server(handle, args.listen_host, args.port, limit=131072)
    print(f"Bilibili MCP proxy {args.listen_host}:{args.port} -> loopback:{args.port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
