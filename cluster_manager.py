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


def _get_packages_to_reload(package):
    assert (hasattr(package, "__package__"))
    fn = package.__file__
    fn_dir = os.path.dirname(fn) + os.sep
    module_visit = {fn}
    ret = set()
    del fn

    def reload_recursive_ex(module):
        for module_child in vars(module).values():
            if isinstance(module_child, types.ModuleType):
                fn_child = getattr(module_child, "__file__", None)
                if (fn_child is not None) and fn_child.startswith(fn_dir):
                    if fn_child not in module_visit:
                        module_visit.add(fn_child)
                        ret.add(module_child)
                        reload_recursive_ex(module_child)

    reload_recursive_ex(package)
    return ret


def reload_package(package):
    packages_to_reload = _get_packages_to_reload(package)

    # reload from the lowest level to the higher
    for package in reversed(list(packages_to_reload)):
        importlib.reload(package)

    log.info(f"Successfully reloaded {len(packages_to_reload)} packages.")


class Launcher:
    SHARDS_PER_CLUSTER = 2

    def __init__(self, loop, bot_name: str = 'midobot'):
        self.cluster_count = 0

        self.clusters: List[Cluster] = []

        self.future = None
        self.loop = loop
        self.alive = True

        self.keep_alive = None
        self.init = time.perf_counter()

        self.bot_name = bot_name
        self.bot_token = midobot.MidoBot.get_config(bot_name)['token']

    def get_shard_count(self):
        data = requests.get('https://discord.com/api/v7/gateway/bot', headers={
            "Authorization": "Bot " + self.bot_token,
            "User-Agent"   : "DiscordBot (https://github.com/Rapptz/discord.py 1.7.3) Python/3.8 aiohttp/3.6.1"
        })
        data.raise_for_status()

        content = data.json()
        log.info(f"Successfully got shard count of {content['shards']} ({data.status_code, data.reason})")

        return content['shards']

    def start(self):
        self.future = asyncio.ensure_future(self.startup(), loop=self.loop)

        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            self.loop.run_until_complete(self.shutdown())
        finally:
            self.cleanup()

    async def startup(self):
        shards = list(range(self.get_shard_count()))
        cluster_shard_ids = [shards[x:x + self.SHARDS_PER_CLUSTER]
                             for x in range(0, len(shards), self.SHARDS_PER_CLUSTER)]

        self.cluster_count = len(cluster_shard_ids)
        log.info(f"Preparing {self.cluster_count} clusters.")

        for i, shard_ids in enumerate(cluster_shard_ids, 0):
            self.clusters.append(
                Cluster(bot_name=self.bot_name, cluster_id=i,
                        launcher=self, shard_ids=shard_ids, max_shards=len(shards),
                        total_clusters=self.cluster_count))

        await self.start_clusters()

        self.keep_alive = self.loop.create_task(self.rebooter())
        self.keep_alive.add_done_callback(self.task_complete)

        log.info(f"Startup completed in {time.perf_counter() - self.init}s")

    async def start_clusters(self):
        for cluster in self.clusters:
            if not cluster.is_alive():
                await cluster.start()
                log.info(f"Started Cluster#{cluster.id}")

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
            for cluster in self.clusters:
                if not cluster.process.is_alive():
                    log.warning(f"Cluster#{cluster.id} exited with code {cluster.process.exitcode}.")

                    cluster.stop()  # ensure stopped

                    log.info(f"Restarting cluster#{cluster.id}")
                    await cluster.start()

            await asyncio.sleep(5)

    def task_complete(self, task):
        if task.exception():
            task.print_stack()
            self.keep_alive = self.loop.create_task(self.rebooter())
            self.keep_alive.add_done_callback(self.task_complete)

    def cleanup(self):
        self.loop.stop()
        if sys.platform == 'win32':
            log.info("press ^C again")
        self.loop.close()


class Cluster:
    def __init__(self, bot_name: str, cluster_id: int, launcher: Launcher, shard_ids: List[int], max_shards: int,
                 total_clusters: int):
        self.bot_name = bot_name
        self.launcher = launcher

        self.parent_pipe, self.child_pipe = multiprocessing.Pipe()

        self.kwargs = dict(
            shard_ids=shard_ids,
            shard_count=max_shards,
            cluster_id=cluster_id,
            bot_name=bot_name,
            total_clusters=total_clusters,
            pipe=self.child_pipe
        )

        self.id = cluster_id
        self.bot = None
        self.process = None

        self.log = logging.getLogger(f"Cluster#{cluster_id}")
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
