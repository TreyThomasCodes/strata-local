#!/usr/bin/env python3
import http.server
import os
import re
import subprocess
import sys

GPU = re.compile(r'^GPU (\d+): .*\(UUID: (GPU-[^)]+)\)')
LINK = re.compile(r'^\s*Link (\d+): Data (Tx|Rx): (\d+) KiB')


def parse(text):
    """Return {uuid: {(link, 'Tx'|'Rx'): bytes}} from `nvidia-smi nvlink -gt d`."""
    out, uuid = {}, None
    for line in text.splitlines():
        m = GPU.match(line)
        if m:
            uuid = m.group(2)
            out[uuid] = {}
            continue
        m = LINK.match(line)
        if m and uuid:
            out[uuid][(m.group(1), m.group(2))] = int(m.group(3)) * 1024
    return out


def render(counters, roles):
    lines = ['# HELP nvlink_data_bytes_total NVLink data moved, per link and direction.',
             '# TYPE nvlink_data_bytes_total counter']
    for uuid, links in counters.items():
        role = roles.get(uuid)
        if role is None:
            continue
        for (link, direction), value in sorted(links.items()):
            lines.append('nvlink_data_bytes_total{role="%s",link="%s",direction="%s"} %d'
                         % (role, link, direction.lower(), value))
    return '\n'.join(lines) + '\n'


def main():
    roles = {os.environ['PRIMARY_GPU_UUID']: 'primary', os.environ['PEER_GPU_UUID']: 'peer'}
    if len(roles) != 2:
        raise RuntimeError('primary and peer GPU UUIDs must differ')

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/metrics':
                self.send_error(404)
                return
            try:
                text = subprocess.run(['nvidia-smi', 'nvlink', '-gt', 'd'], check=True, timeout=15,
                                      capture_output=True, text=True).stdout
                body = render(parse(text), roles).encode()
            except (OSError, subprocess.SubprocessError):
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    http.server.ThreadingHTTPServer(('0.0.0.0', 9102), Handler).serve_forever()


if __name__ == '__main__':
    sys.exit(main())
