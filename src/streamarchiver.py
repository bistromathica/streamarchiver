"""
Runs concurrent yt-dlp processes in --wait-for-video mode.
Open a yt-dlp instance for each STREAMS_TO_MONITOR, and detect when a stream is live.
"""
import asyncio
import logging
import signal
import re
from enum import Enum
from datetime import datetime, timedelta
import configuration
from pydantic import BaseModel
import click
import sys
from pathlib import Path


class Streamer(BaseModel):
    username: str
    platform: str

    def get_stream_url(self) -> str:
        try:
            return {'Twitch': f'https://www.twitch.tv/{self.username}',
                    'Pomf': f'https://pomf.tv/stream/{self.username}'}[self.platform]
        except KeyError as e:
            raise NotImplemented from e

    def vods_location(self, parent):
        vod_dir = Path(parent).expanduser()/self.platform/self.username
        if not vod_dir.exists():
            vod_dir.mkdir(parents=True, exist_ok=True)
        return str(vod_dir)


DOWNLOADING = re.compile(r'^\[download] Destination: (.*)')
NOT_LIVE = re.compile(r'^WARNING: \[(.*): The channel is not currently live')
FINISHED_DOWNLOADING = re.compile(r'\[download] 100% of ')


class YtdlpStatus(Enum):
    NONE = 0
    STARTED = 1
    STOPPED = 2
    WAITING = 3
    DOWNLOADING = 4
    FINISHED = 5
    FAILURE = 9


TERM_TIMEOUT = 5
should_stop = asyncio.Event()


class YtdlpManager:
    """Wraps asyncio.subprocess.Process of a yt-dlp instance."""
    def __init__(self, config: configuration.Config, streamer: Streamer, priority: int):
        self.config = config
        self.priority = priority
        self.streamer = streamer
        self.status = YtdlpStatus.NONE
        self.process: None | asyncio.subprocess.Process = None
        self.task: None | asyncio.Task = None

    async def manage(self):
        cwd = self.streamer.vods_location(self.config.vods_location)

        if (Path(cwd)/'yt-dlp.conf').exists():
            logging.info(f'Found custom yt-dlp.conf in {cwd}.')

        self.process: asyncio.subprocess.Process = await asyncio.create_subprocess_shell(
            self.config.yt_dlp_command + " " + self.streamer.get_stream_url(),
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        started = datetime.now()
        logging.debug("Started %s on %s", self, started)

        try:
            self.status = YtdlpStatus.STARTED
            tasks = self.process_stderr(), self.process_stdout()
            await asyncio.gather(*tasks)
            await self.process.wait()

            if (datetime.now() - started) < timedelta(seconds=10):
                # It's restarting too fast, something is wrong
                self.status = YtdlpStatus.FAILURE
                logging.debug(f"yt-dlp self ended too quickly. Giving up. %s", self)

        except Exception:
            logging.info(f"Terminating {self}")
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), TERM_TIMEOUT)
            except asyncio.TimeoutError:
                logging.error(f"Unruly process. kill -9, you little shit: {self}")
                self.process.kill()
            raise

    def run(self):
        if self.task and not self.task.done():
            raise Exception(f"Tried to start {self} when already started.")
        logging.info("Running %s", self)
        self.task = asyncio.create_task(self.manage())

    def stop(self):
        self.task.cancel()
        logging.info("Stopping %s", self)

    def __str__(self):
        return f"YtdlpInstance(streamer={self.streamer}, status={self.status})"

    def __repr__(self):
        return f"YtdlpInstance(streamer={self.streamer}, status={self.status})"

    async def process_stdout(self) -> None:
        while line := (await self.process.stdout.readline()).decode().strip():
            if match := DOWNLOADING.match(line):
                self.downloading()
            elif match := FINISHED_DOWNLOADING.match(line):
                self.finished()
                logging.debug(f"STDOUT: %s", line)
            # logging.debug(f"STDOUT: %s", line)

    async def process_stderr(self) -> None:
        while line := (await self.process.stderr.readline()).decode().strip():
            if match := NOT_LIVE.match(line):
                self.waiting()
            # logging.debug("STDERR: %s", line)

    def downloading(self):
        if self.status != YtdlpStatus.DOWNLOADING:
            logging.info("Started downloading: %s", self)
            self.status = YtdlpStatus.DOWNLOADING

    def finished(self):
        if self.status != YtdlpStatus.FINISHED:
            logging.info("Finished downloading: %s", self)
            self.status = YtdlpStatus.FINISHED

    def waiting(self):
        if self.status != YtdlpStatus.WAITING:
            logging.info("Started waiting: %s", self)
            self.status = YtdlpStatus.WAITING


class YtdlpManagerManager:
    def __init__(self, config: configuration.Config):
        # Runs, stops, and reports on a list of YtdlpManagers
        self.config = config
        self.managers = [YtdlpManager(config, Streamer(username=stream.name, platform=stream.where), priority=priority)
                         for priority, stream in enumerate(config.streams)]
        self.loop_seconds = 5
        report_task = asyncio.create_task(self.report_periodically())
        logging.debug("%s", self.managers)

    def not_started(self):
        return [manager for manager in self.managers if manager.task is None]

    def running(self):
        return [manager for manager in self.managers if manager.task and not manager.task.done()]

    def stopped(self):
        return [manager for manager in self.managers
                if manager.task and manager.task.done() and manager.status is not YtdlpStatus.FAILURE]

    def failed(self):
        return [manager for manager in self.managers if manager.status is YtdlpStatus.FAILURE]

    def downloading(self):
        downloading = [manager for manager in self.managers if manager.status is YtdlpStatus.DOWNLOADING]
        downloading.sort(key=lambda x: x.priority)
        return downloading

    def loop(self):
        self.loop_seconds = self.config.loop_seconds
        not_started, running, stopped, downloading, failed = \
            self.not_started(), self.running(), self.stopped(), self.downloading(), self.failed()

        if len(downloading) < self.config.concurrent_downloads:
            if not_started:
                not_started[0].run()
                self.loop_seconds = 1
            elif stopped:
                stopped[0].run()
        elif len(downloading) > self.config.concurrent_downloads:
            print(f"{len(downloading)} {self.config.concurrent_downloads}")
            downloading[0].stop()

    def stop_all(self):
        logging.info("Signal caught. Quitting.")
        should_stop.set()
        for manager in self.managers:
            if manager.task:
                manager.task.cancel()

    async def wait_for_quit(self):
        await asyncio.gather(*[manager.task for manager in self.managers if manager.task], return_exceptions=True)

    async def report_periodically(self):
        while not should_stop.is_set():
            not_started, running, stopped, downloading, failed = \
                self.not_started(), self.running(), self.stopped(), self.downloading(), self.failed()

            logging.debug("not_started=%s, running=%s, stopped=%s, downloading=%s, failed=%s",
                          len(not_started), len(running), len(stopped), len(downloading), len(failed))

            if downloading:
                logging.debug(f"Downloading: {', '.join(str(x.streamer) for x in downloading)}")

            await asyncio.sleep(20)


async def main(config: configuration.Config):
    """Loops infinitely. Checks if a yt-dlp instance exists in processes dict and opens
    with open_ytdlp if it does not."""
    vods = Path(config.vods_location).expanduser()
    if not vods.exists():
        vods.mkdir()

    loop = asyncio.get_running_loop()

    manager = YtdlpManagerManager(config)

    loop.add_signal_handler(signal.SIGINT, manager.stop_all)
    loop.add_signal_handler(signal.SIGTERM, manager.stop_all)

    while not should_stop.is_set():
        start = datetime.now()
        manager.loop()

        if wait := manager.loop_seconds - (datetime.now() - start).total_seconds():
            await asyncio.sleep(wait)

    # We are stopping now. Wait for all tasks to finish.
    logging.info("Stopped. Waiting for tasks to terminate.")
    await manager.wait_for_quit()

    logging.debug("Exiting")


@click.group()
@click.option('--verbose', '-v', is_flag=True, default=[], multiple=True, help='Verbose output')
@click.option('--config', '-c', default=None, help='Custom location for streamarchiver.yaml')
@click.pass_context
def cli(ctx, verbose, config: str):
    ctx.ensure_object(dict)
    loglevel = len(verbose)
    if loglevel > 1:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
    elif loglevel:
        logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    ctx.obj['config'] = configuration.get(config)


@cli.command(help='Run streamarchiver in a loop')
@click.pass_context
def run(ctx):
    asyncio.run(main(ctx.obj['config']))
