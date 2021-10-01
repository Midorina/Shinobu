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


async def serve(ws, path):
    cluster_id = (await ws.recv()).decode()

    # reconnection
    if cluster_id in CLIENTS:
        logger.warning(f"! Cluster[{cluster_id}] reconnected.")
        await CLIENTS[cluster_id].close(4029, f"Cluster {cluster_id} reconnected somewhere else.")
    else:
        await ws.send(b'{"status":"ok"}')
        logger.info(f'$ Cluster[{cluster_id}] connected successfully.')

    CLIENTS[cluster_id] = ws
    try:
        async for msg in ws:
            logger.info(f'< Cluster[{cluster_id}]: {msg}')
            await dispatch_to_all_clusters(msg)
    except websockets.ConnectionClosed as e:
        logger.error(f'$ Cluster[{cluster_id}]\'s connection has been closed: {e}')
    finally:
        logger.info(f"$ Cluster[{cluster_id}] disconnected.")
        CLIENTS.pop(cluster_id)


async def dispatch_to_all_clusters(data):
    for cluster_id, client in CLIENTS.items():
        await client.send(data)
        logger.debug(f'> Cluster[{cluster_id}] {data}')


signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)

logger.info(f"IPC is up with port {args.port}.")
server = websockets.serve(serve, 'localhost', args.port)
loop = asyncio.get_event_loop()
loop.run_until_complete(server)
loop.run_forever()
