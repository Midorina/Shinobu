import asyncio
import importlib
import logging
import multiprocessing
import os
import signal
import types
from typing import List

import requests

import shinobu

cluster_logger = logging.getLogger('Cluster Manager')


# TODO: use ipc or a pipe to listen to clusters and use that to stop/start/restart clusters

def _get_packages_to_reload(package):
    assert (hasattr(package, "__package__"))

    main_file_path = package.__file__
    main_file_directory = os.path.dirname(main_file_path) + os.sep
    visited_module_paths = {main_file_path}
    ret = set()

    def reload_recursive_ex(module):
        for child_module in vars(module).values():
            if isinstance(child_module, types.ModuleType):
                child_module_path = getattr(child_module, "__file__", None)

                if child_module_path and child_module_path.startswith(main_file_directory) \
                        and 'env' + os.sep not in child_module_path:
                    if child_module_path not in visited_module_paths:
                        visited_module_paths.add(child_module_path)
                        ret.add(child_module)
                        reload_recursive_ex(child_module)

    reload_recursive_ex(package)
    return ret


def reload_package(package):
    packages_to_reload = _get_packages_to_reload(package)

    # reload from the lowest level to the higher
    for package in reversed(list(packages_to_reload)):
        try:
            importlib.reload(package)
        except Exception as e:
            # asyncpg has a built-in check about redefinitions, which raises a RuntimeError
            # https://github.com/MagicStack/asyncpg/blob/master/asyncpg/exceptions/_base.py#L57
            cluster_logger.error(f"Error while trying to reload the package {package}: {e}")

    cluster_logger.info(f"Successfully reloaded {len(packages_to_reload)} packages.")


class Launcher:
    SHARDS_PER_CLUSTER = 2

    def __init__(self, bot_name: str = 'shinobu', loop=None):
        self.bot_name = bot_name
        self.bot_token = shinobu.ShinobuBot.get_config(bot_name, warn=True).token

        self.clusters: List[Cluster] = []
        self.cluster_count = 0

        self.loop = loop or asyncio.get_event_loop()
        self.startup_task = None
        self.rebooter_task = None

        self.alive = True

    def start(self):
        self.startup_task = asyncio.ensure_future(self.prepare_and_start_clusters(), loop=self.loop)

        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            self.loop.run_until_complete(self.shutdown())
        finally:
            self.loop.stop()
            self.loop.close()

    def get_shard_count(self):
        cluster_logger.info(f"Getting required shard count from DiscordAPI...")

        data = requests.get('https://discord.com/api/v7/gateway/bot', headers={
            "Authorization": "Bot " + self.bot_token,
            "User-Agent"   : "DiscordBot (https://github.com/Rapptz/discord.py 1.7.3) Python/3.8 aiohttp/3.6.1"
        })

        data.raise_for_status()
        content = data.json()

        cluster_logger.info(f"Successfully got shard count of {content['shards']}.")

        return content['shards']

    async def prepare_and_start_clusters(self):
        shards = list(range(self.get_shard_count()))
        cluster_shard_ids = [shards[x:x + self.SHARDS_PER_CLUSTER]
                             for x in range(0, len(shards), self.SHARDS_PER_CLUSTER)]

        self.cluster_count = len(cluster_shard_ids)
        cluster_logger.info(f"Preparing {self.cluster_count} clusters.")

        for i, shard_ids in enumerate(cluster_shard_ids, 0):
            self.clusters.append(
                Cluster(bot_name=self.bot_name, cluster_id=i,
                        launcher=self, shard_ids=shard_ids, max_shards=len(shards),
                        total_clusters=self.cluster_count))

        await self.start_clusters()

        self.rebooter_task = self.loop.create_task(self.rebooter())
        self.rebooter_task.add_done_callback(self.task_complete)

        cluster_logger.info(f"Startup complete.")

    async def start_clusters(self):
        for cluster in self.clusters:
            if not cluster.is_alive():
                await cluster.start()
                cluster_logger.info(f"Started Cluster#{cluster.id}.")

    async def shutdown(self):
        self.alive = False

        if self.rebooter_task:
            self.rebooter_task.cancel()

        for cluster in self.clusters:
            cluster.stop()

    async def rebooter(self):
        """
        Our exit codes:

        0 -> I was shutdown properly. Don't restart me.
        Literally anything else -> Restart.
        """
        while self.alive:
            for cluster in self.clusters:
                if not cluster.process.is_alive() and cluster.dont_restart is False:
                    cluster_logger.warning(f"Cluster#{cluster.id} exited with code {cluster.process.exitcode}.")

                    cluster.stop()  # ensure stopped

                    if cluster.process.exitcode != 0:
                        cluster_logger.info(f"Restarting cluster#{cluster.id}")
                        await cluster.start()
                    else:
                        cluster.dont_restart = True

            dead_and_dont_restart_cluster_count = len([x for x in self.clusters
                                                       if not x.process.is_alive() and x.dont_restart is True])

            if dead_and_dont_restart_cluster_count == self.cluster_count:
                cluster_logger.info("All clusters seem to be dead and they don't want to be restarted, "
                                    "so I'm killing myself too. Fuck this world.")
                return await self.shutdown()

            await asyncio.sleep(5)

    def task_complete(self, task):
        try:
            # if there was an exception besides CancelledError, just restart
            if task.exception():
                task.print_stack()

                self.rebooter_task = self.loop.create_task(self.rebooter())
                self.rebooter_task.add_done_callback(self.task_complete)
                return

        except asyncio.CancelledError:
            self.loop.stop()


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
        self.log.info(f"I have been initialized with shards {shard_ids} ({len(shard_ids)}/{max_shards}).")

        self.dont_restart = False

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
        reload_package(shinobu)

        self.process = multiprocessing.Process(name=f'{self.bot_name} #{self.kwargs["cluster_id"]}',
                                               target=shinobu.ShinobuBot, kwargs=self.kwargs, daemon=True)
        self.process.start()

        self.log.info(f"Process started with PID {self.process.pid}")

    def stop(self, sign=signal.SIGTERM):
        self.log.info(f"Shutting down with signal {sign!r}.")

        try:
            os.kill(self.process.pid, sign)
        except (ProcessLookupError, PermissionError):
            pass
