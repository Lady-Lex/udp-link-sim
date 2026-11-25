"""Fixed-peer duplex IPv4 UDP relay. Usage: python udp_proxy.py routes.csv"""
import os
import shutil
from dataclasses import dataclass
import csv
import heapq
import itertools
import math
import random
import selectors
import socket
import sys
import time
from contextlib import ExitStack
from ipaddress import IPv4Address


def endpoint(row, prefix):
    ip = str(IPv4Address(row[prefix + '_ip'].strip()))
    port = int(row[prefix + '_port'])
    if not (0 if prefix == 'source' else 1) <= port <= 65535:
        raise ValueError(f'invalid {prefix} port: {port}')
    return ip, port


@dataclass
class Channel:
    src: tuple
    dst: tuple
    base: float
    sigma: float
    rx: int = 0
    tx: int = 0
    errors: int = 0
    last_tx: int = 0


def display(channels, interval, udp_resets):
    cols, rows = shutil.get_terminal_size()
    lines = [f'UDP relay | Win10054={udp_resets} | Ctrl+C to exit',
             ' CH       RX       TX   QUEUE   ERR   TX/s  SOURCE -> TARGET']
    for i, c in enumerate(channels, 1):
        rate = (c.tx - c.last_tx) / interval
        c.last_tx = c.tx
        lines.append(f'{i:3} {c.rx:8} {c.tx:8} {c.rx-c.tx-c.errors:7} '
                     f'{c.errors:5} {rate:6.1f}  {c.src[0]}:{c.src[1]} -> {c.dst[0]}:{c.dst[1]}')
    if len(lines) > rows:
        lines = lines[:max(0, rows-1)] + ['Enlarge terminal to see more channels']
    frame = ''.join(f'\x1b[{i};1H' + line[:max(0, cols-1)] + '\x1b[K'
                    for i, line in enumerate(lines, 1))
    print(frame + '\x1b[J', end='', flush=True)


def receive(sock):
    try:
        return sock.recvfrom(65535)
    except ConnectionResetError as exc:
        if getattr(exc, 'winerror', None) != 10054:
            raise
        return None  # asynchronous ICMP notification, not a data packet


def run(path):
    udp_resets = 0
    channels = []
    pending, seq = [], itertools.count()
    with ExitStack() as stack:
        sel = stack.enter_context(selectors.DefaultSelector())
        listeners = {}
        with open(path, newline='', encoding='utf-8-sig') as f:
            for line, row in enumerate(csv.DictReader(f), 2):
                src, dst = endpoint(row, 'listen'), endpoint(row, 'target')
                peer = endpoint(row, 'source')
                if src in (peer, dst) or peer == dst or src[0] == '0.0.0.0':
                    raise ValueError(f'line {line}: use distinct concrete endpoints')
                base, sigma = float(row['base_ms']), float(row['sigma_ms'])
                if not all(math.isfinite(x) and x >= 0 for x in (base, sigma)):
                    raise ValueError(f'line {line}: invalid delay')
                if src not in listeners:
                    sock = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
                    sock.bind(src)
                    listeners[src] = {}
                    sel.register(sock, selectors.EVENT_READ, listeners[src])
                routes = listeners[src]
                if peer in routes:
                    raise ValueError(f'line {line}: duplicate source on listener {src}')
                c = Channel(peer, dst, base, sigma)
                channels.append(c)
                routes[peer] = c
        if not sel.get_map():
            raise ValueError('no routes in CSV')
        live = sys.stdout.isatty()
        if live:
            if os.name == 'nt':
                os.system('')  # Enable ANSI processing in modern Windows consoles.
            print('\x1b[?1049h\x1b[2J\x1b[?25l', end='', flush=True)
            stack.callback(print, '\x1b[?25h\x1b[?1049l', end='', flush=True)
        else:
            print(f'Forwarding {len(channels)} channels (dashboard requires a terminal)', flush=True)
        last = time.monotonic() - 0.25
        while True:
            while pending and pending[0][0] <= time.monotonic():
                _, _, out, c, data = heapq.heappop(pending)
                try:
                    out.sendto(data, c.dst)
                    c.tx += 1
                except OSError:
                    c.errors += 1
            timeout = max(0, pending[0][0] - time.monotonic()) if pending else 1
            if live:
                now = time.monotonic()
                if now - last >= 0.25:
                    display(channels, now - last, udp_resets)
                    last = now
                timeout = min(timeout, max(0, last + 0.25 - time.monotonic()))
            for key, _ in sel.select(min(timeout, 1)):
                packet = receive(key.fileobj)
                if packet is None:
                    udp_resets += 1
                    continue
                data, peer = packet
                c = key.data.get(peer) or key.data.get((peer[0], 0))
                if c is None:
                    continue
                c.rx += 1
                delay = max(0, random.gauss(c.base, c.sigma)) / 1000
                heapq.heappush(pending, (time.monotonic() + delay, next(seq), key.fileobj, c, data))


if __name__ == '__main__':
    try:
        run(sys.argv[1] if len(sys.argv) > 1 else 'routes.csv')
    except KeyboardInterrupt:
        pass
