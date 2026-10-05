"""Enforce GPU UUID-bound power caps in a separate utility-only container."""
import csv
import os
import subprocess
import sys
import time


def policy():
    primary, peer = os.environ['PRIMARY_GPU_UUID'], os.environ['PEER_GPU_UUID']
    if not primary.startswith('GPU-') or not peer.startswith('GPU-') or primary == peer:
        raise ValueError('Configure two distinct GPU UUIDs')
    caps = {primary: int(os.environ.get('PRIMARY_POWER_W', '300')),
            peer: int(os.environ.get('PEER_POWER_W', '350'))}
    if any(watts <= 0 for watts in caps.values()):
        raise ValueError('Power limits must be positive')
    return caps


def read_limits():
    result = subprocess.check_output([
        'nvidia-smi', '--query-gpu=uuid,power.limit', '--format=csv,noheader,nounits',
    ], text=True, encoding='utf-8', timeout=10)
    return {row[0].strip(): float(row[1]) for row in csv.reader(result.splitlines())}


def check(caps):
    actual = read_limits()
    return all(uuid in actual and abs(actual[uuid] - watts) < .5 for uuid, watts in caps.items())


def enforce(caps):
    actual = read_limits()
    for uuid, watts in caps.items():
        if uuid not in actual:
            raise RuntimeError(f'Required physical GPU missing: {uuid}')
        if abs(actual[uuid] - watts) >= .5:
            subprocess.run(['nvidia-smi', '-i', uuid, '-pl', str(watts)], check=True, timeout=15)
            print(f'Power policy applied: {uuid} -> {watts} W', flush=True)
    if not check(caps):
        raise RuntimeError('Power policy failed readback verification')


if __name__ == '__main__':
    caps = policy()
    if sys.argv[1:] == ['--check']:
        sys.exit(0 if check(caps) else 1)
    if sys.argv[1:]:
        sys.exit('usage: power-policy.py [--check]')
    while True:
        enforce(caps)
        time.sleep(30)
