"""Deterministic WASAPI simulation for a real Windows worker subprocess."""
import os
from pathlib import Path
import threading
import time
import numpy as np


def query_hostapis():
    return [{'name': 'Windows WASAPI'}]


def query_devices(device=None, kind=None):
    items = [dict(name='Test Mic', hostapi=0, max_input_channels=1, max_output_channels=0),
             dict(name='CABLE Input (VB-Audio Virtual Cable)', hostapi=0, max_input_channels=0, max_output_channels=2)]
    return items[0] if kind else items


def WasapiSettings(**kwargs):
    return kwargs


class CallbackStop(Exception):
    pass


class InputStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.stop = threading.Event()

    def __enter__(self):
        def capture():
            size = self.kwargs['blocksize']
            while not self.stop.wait(size / self.kwargs['samplerate']):
                self.kwargs['callback'](np.full((size, 1), .05, np.float32), size, None,
                                        type('Status', (), {'input_overflow': False})())
        self.thread = threading.Thread(target=capture, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(1)
        (Path(os.environ['ONLY_VOICE_TEST_DIRECTORY']) / 'capture-closed').touch()


class OutputStream:
    def __init__(self, **kwargs):
        self.active = True

    def __enter__(self):
        return self

    def write(self, frame):
        with (Path(os.environ['ONLY_VOICE_TEST_DIRECTORY']) / 'output.raw').open('ab') as stream:
            stream.write(frame.tobytes())

    def __exit__(self, *_):
        self.active = False
        (Path(os.environ['ONLY_VOICE_TEST_DIRECTORY']) / 'playback-closed').touch()
