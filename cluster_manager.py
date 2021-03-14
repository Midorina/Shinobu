import asyncio
import importlib
import logging
import multiprocessing
import os
import signal
import sys
import time
import types
from typing import List

import requests

import midobot

log = logging.getLogger('Cluster Manager')

CLUSTER_NAMES = iter((
    'Alpha', 'Beta', 'Charlie', 'Delta', 'Echo', 'Foxtrot', 'Golf', 'Hotel',
    'India', 'Juliett', 'Kilo', 'Mike', 'November', 'Oscar', 'Papa', 'Quebec',
    'Romeo', 'Sierra', 'Tango', 'Uniform', 'Victor', 'Whisky', 'X-ray', 'Yankee', 'Zulu'
))


def reload_package(package):
    # reloading from top level cause some bugs such as this https://thomas-cokelaer.info/blog/2011/09/382/
    # so reload from the lowest level if something behaves weird
    assert (hasattr(package, "__package__"))
    fn = package.__file__
    fn_dir = os.path.dirname(fn) + os.sep
    module_visit = {fn}
    del fn

    def reload_recursive_ex(module):
        importlib.reload(module)

        for module_child in vars(module).values():
            if isinstance(module_child, types.ModuleType):
                fn_child = getattr(module_child, "__file__", None)
                if (fn_child is not None) and fn_child.startswith(fn_dir):
                    if fn_child not in module_visit:
                        log.debug("Reloading module:", fn_child, "\tFrom:", module)
                        module_visit.add(fn_child)
                        reload_recursive_ex(module_child)

    return reload_recursive_ex(package)


class Launcher:
    def __init__(self, loop, bot_name: str = 'midobot'):
        self.cluster_count = 0

        self.clusters: List[Cluster] = []

        self.fut = None
        self.loop = loop
        self.alive = True

        self.keep_alive = None
        self.init = time.perf_counter()

        self.bot_name = bot_name
        self.bot_token = midobot.MidoBot.get_config(bot_name)['token']

    def get_shard_count(self):
        data = requests.get('https://discordapp.com/api/v7/gateway/bot', headers={
            "Authorization": "Bot " + self.bot_token,
            "User-Agent"   : "DiscordBot (https://github.com/Rapptz/discord.py 1.3.0a) Python/3.7 aiohttp/3.6.1"
        })
        data.raise_for_status()
        content = data.json()
        log.info(f"Successfully got shard count of {content['shards']} ({data.status_code, data.reason})")
        return content['shards']

    def start(self):
        self.fut = asyncio.ensure_future(self.startup(), loop=self.loop)

        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            self.loop.run_until_complete(self.shutdown())
        finally:
            self.cleanup()

    def cleanup(self):
        self.loop.stop()
        if sys.platform == 'win32':
            print("press ^C again")
        self.loop.close()

    def task_complete(self, task):
        if task.exception():
            task.print_stack()
            self.keep_alive = self.loop.create_task(self.rebooter())
            self.keep_alive.add_done_callback(self.task_complete)

    async def startup(self):
        shards = list(range(self.get_shard_count()))
        cluster_shard_ids = [shards[x:x + 4] for x in range(0, len(shards), 4)]

        self.cluster_count = len(cluster_shard_ids)
        log.info(f"Preparing {self.cluster_count} clusters")

        for shard_ids in cluster_shard_ids:
            self.clusters.append(
                Cluster(bot_name=self.bot_name, cluster_name=next(CLUSTER_NAMES),
                        launcher=self, shard_ids=shard_ids, max_shards=len(shards),
                        total_clusters=self.cluster_count))
        await self.start_clusters()

        self.keep_alive = self.loop.create_task(self.rebooter())
        self.keep_alive.add_done_callback(self.task_complete)
        log.info(f"Startup completed in {time.perf_counter() - self.init}s")

    async def shutdown(self):
        log.info("Shutting down clusters")
        self.alive = False
        if self.keep_alive:
            self.keep_alive.cancel()
        for cluster in self.clusters:
            cluster.stop()
        self.cleanup()

    async def rebooter(self):
        while self.alive:
            if not self.clusters:
                log.warning("All clusters appear to be dead")
                asyncio.ensure_future(self.shutdown())

            for cluster in self.clusters:
                if not cluster.process.is_alive():
                    log.warning(f"Cluster#{cluster.name} exited with code {cluster.process.exitcode}.")
                    cluster.stop()  # ensure stopped
                    log.info(f"Restarting cluster#{cluster.name}")
                    await cluster.start()

            await asyncio.sleep(5)

    async def start_clusters(self):
        for cluster in self.clusters:
            if not cluster.is_alive():
                log.info(f"Starting Cluster#{cluster.name}")
                await cluster.start()
                log.info("Done!")


class Cluster:
    def __init__(self, bot_name: str, cluster_name: str, launcher: Launcher, shard_ids: List[int], max_shards: int,
                 total_clusters: int):
        self.bot_name = bot_name
        self.launcher = launcher
        self.kwargs = dict(
            shard_ids=shard_ids,
            shard_count=max_shards,
            cluster_name=cluster_name,
            bot_name=bot_name,
            total_clusters=total_clusters
        )
        self.name = cluster_name
        self.bot = None
        self.process = None

        self.log = logging.getLogger(f"Cluster#{cluster_name}")
        self.log.info(f"Initialized with shard ids {shard_ids}, total shards {max_shards}")

    def wait_close(self):
        return self.process.join()

    def is_alive(self):
        return self.process and self.process.is_alive()

    async def start(self, *, force=False):
        if self.process and self.is_alive():
            if not force:
                self.log.warning("Start called with already running cluster, pass `force=True` to override")
                return

            self.log.info("Terminating existing process")
            self.process.terminate()
            self.process.close()

        # reload the bot so that the changes we've made takes effect
        reload_package(midobot)

        self.process = multiprocessing.Process(target=midobot.MidoBot, kwargs=self.kwargs, daemon=True)
        self.process.start()
        self.log.info(f"Process started with PID {self.process.pid}")

        return True

    def stop(self, sign=signal.SIGINT):
        self.log.info(f"Shutting down with signal {sign!r}")
        try:
            os.kill(self.process.pid, sign)
        except ProcessLookupError:
            pass
