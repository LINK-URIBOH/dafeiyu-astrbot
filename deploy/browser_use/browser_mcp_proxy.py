"""Bridge the Docker gateway to the Browser Use SSH reverse tunnel.

BrowserMCP runs on the Windows host and is forwarded to the cloud host's
127.0.0.1:8010 by ``ssh -R``.  Containers cannot reach the host loopback, so
this proxy listens on the Docker bridge gateway (172.18.0.1 by default) and
forwards to 127.0.0.1:8010.

Verify the gateway first:
    docker network inspect dafeiyu_default | grep Gateway
"""

import asyncio

LISTEN_HOST = "172.18.0.1"
LISTEN_PORT = 8010
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 8010


async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_reader, client_writer):
    try:
        server_reader, server_writer = await asyncio.open_connection(
            TARGET_HOST, TARGET_PORT
        )
        await asyncio.gather(
            pipe(client_reader, server_writer),
            pipe(server_reader, client_writer),
        )
    except Exception:
        pass
    finally:
        try:
            client_writer.close()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    print(
        f"browser_mcp_proxy listening on {LISTEN_HOST}:{LISTEN_PORT} -> "
        f"{TARGET_HOST}:{TARGET_PORT}",
        flush=True,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
