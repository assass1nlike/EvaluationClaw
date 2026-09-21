"""Spawn target that imports only the queue, without model SDK initialization."""

import time
from utils.search_queue import search_slot


def occupy(directory, start, acquired=None, capacity=4):
    start.wait()
    with search_slot(directory, capacity):
        if acquired is not None:
            acquired.set()
            time.sleep(30)
        else:
            time.sleep(0.15)
