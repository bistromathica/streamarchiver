from pydantic import BaseModel, PositiveInt
from typing import Optional, List
from pathlib import Path
import yaml
import logging


class StreamToMonitor(BaseModel):
    name: str
    where: str

    class Config:
        extra = 'forbid'


class Config(BaseModel):
    concurrent_downloads: int
    yt_dlp_config: str
    yt_dlp_command: str
    streams: List[StreamToMonitor]
    loop_seconds: PositiveInt
    vods_location: str

    class Config:
        extra = 'forbid'


defaults = {
    'concurrent_downloads': 20,
    'yt_dlp_command': 'yt-dlp --wait-for-video 15',
    'yt_dlp_config': '',
    'streams': [{'name': 'OurChickenLife', 'where': 'twitch'}],
    'loop_seconds': 5,
    'vods_location': '~/VODs'
}


def load_config_file(config_file_path: str) -> Config:
    with open(config_file_path, 'r') as f:
        config_data = yaml.safe_load(f)
        logging.info(f"Loaded config from {config_file_path}")
    return Config(**config_data)


def get(custom=None):
    if custom:
        return load_config_file(custom)
    for path in ('/etc/streamarchiver.yaml', './streamarchiver.yaml'):
        if Path(path).is_file():
            return load_config_file(path)
    return Config(**defaults)
