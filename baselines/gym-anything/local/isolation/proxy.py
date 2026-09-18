"""Expose the existing loopback proxy to the private generation network."""
import asyncio


async def copy(reader, writer):
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    writer.write_eof()


async def relay(reader, writer):
    upstream_reader, upstream_writer = await asyncio.open_connection('127.0.0.1', 7890)
    try:
        await asyncio.gather(copy(reader, upstream_writer), copy(upstream_reader, writer))
    finally:
        upstream_writer.close()
        writer.close()


async def main():
    server = await asyncio.start_server(relay, '10.250.0.1', 17890)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
