import argparse
import asyncio
import logging
import signal
import sys

import websockets

parser = argparse.ArgumentParser()
parser.add_argument("--port",
                    type=int,
                    help="The port that will be listened to.",
                    default=13337)
args = parser.parse_args()

logger = logging.getLogger('IPC')
logger.setLevel(logging.INFO)

_format = logging.Formatter('[{asctime}.{msecs:.0f}] [{levelname:<7}] {name}: {message}',
                            datefmt='%Y-%m-%d %H:%M:%S', style='{')

# stdout handler
handler_c1 = logging.StreamHandler(stream=sys.stdout)
handler_c1.setLevel(logging.DEBUG)
handler_c1.addFilter(lambda msg: msg.levelno <= logging.INFO)
# stderr handler
handler_c2 = logging.StreamHandler(stream=sys.stderr)
handler_c2.setLevel(logging.WARNING)

handler_c1.setFormatter(_format)
handler_c2.setFormatter(_format)

logger.handlers = [handler_c1, handler_c2]

CLIENTS = {}


async def serve(ws: websockets.WebSocketServerProtocol):
    cluster_id = (await ws.recv()).decode()

    # reconnection
    if cluster_id in CLIENTS:
        await CLIENTS[cluster_id].close(4029, f"Cluster {cluster_id} reconnected somewhere else.")
        logger.warning(f"! Cluster[{cluster_id}] reconnected.")
    else:
        logger.info(f'$ Cluster[{cluster_id}] connected successfully.')

    CLIENTS[cluster_id] = ws
    await ws.send(b'{"status":"ok"}')

    try:
        async for msg in ws:
            logger.info(f'< Cluster[{cluster_id}]: {msg}')
            await dispatch_to_all_clusters(msg)
    except websockets.ConnectionClosed as e:
        logger.error(f'$ Cluster[{cluster_id}]\'s connection has been closed: {e}')
    finally:
        CLIENTS.pop(cluster_id)
        logger.info(f"$ Cluster[{cluster_id}] disconnected.")


async def dispatch_to_all_clusters(data):
    websockets.broadcast(CLIENTS.values(), data)
    logger.debug(f'> Sent message to clusters {",".join(CLIENTS.keys())}: {data}')


async def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

    async with websockets.serve(serve, 'localhost', args.port):
        logger.info(f"IPC is up with port {args.port}.")

        await asyncio.Future()


asyncio.run(main())
