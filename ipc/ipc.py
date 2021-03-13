import argparse
import asyncio
import logging
import signal

import websockets

parser = argparse.ArgumentParser()
parser.add_argument("--port",
                    type=int,
                    help="The port that will be listened to.",
                    default=13337)
args = parser.parse_args()

logger = logging.getLogger('IPC')
logger.setLevel(logging.INFO)

_handler = logging.StreamHandler()
_format = logging.Formatter('[{asctime}.{msecs:.0f}] [{levelname:<7}] {name}: {message}',
                            datefmt='%Y-%m-%d %H:%M:%S', style='{')
_handler.setFormatter(_format)
logger.addHandler(_handler)

CLIENTS = {}


async def serve(ws, path):
    cluster_name = (await ws.recv()).decode()

    # reconnection
    if cluster_name in CLIENTS:
        logger.warning(f"! Cluster[{cluster_name}] reconnected.")
        await CLIENTS[cluster_name].close(4029, f"Cluster {cluster_name} reconnected somewhere else.")
    else:
        await ws.send(b'{"status":"ok"}')
        logger.info(f'$ Cluster[{cluster_name}] connected successfully.')

    CLIENTS[cluster_name] = ws
    try:
        async for msg in ws:
            logger.info(f'< Cluster[{cluster_name}]: {msg}')
            await dispatch_to_all_clusters(msg)
    except websockets.ConnectionClosed as e:
        logger.error(f'$ Cluster[{cluster_name}]\'s connection has been closed: {e}')
    finally:
        CLIENTS.pop(cluster_name)


async def dispatch_to_all_clusters(data):
    for cluster_name, client in CLIENTS.items():
        await client.send(data)
        logger.info(f'> Cluster[{cluster_name}] {data}')


signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)

logger.info(f"IPC is up with port {args.port}.")
server = websockets.serve(serve, 'localhost', args.port)
loop = asyncio.get_event_loop()
loop.run_until_complete(server)
loop.run_forever()
