#!/usr/bin/env python3
"""Export GDDR6X memory junction temperature for GA102 cards (RTX 3090).

NVML reports N/A for this sensor. The driver does not support this read; the register
offset comes from community reverse engineering. The reader opens one read-only sysfs
BAR0 file per GPU, maps one page read-only, and reads one 32-bit register. It never writes.
"""
import http.server
import mmap
import os
import struct
import sys

PAGE = 0xE000
OFFSET = 0x2A8  # register 0xE2A8
MIN_C, MAX_C = 10.0, 125.0


def decode(raw):
    return (raw & 0xFFF) / 32.0


def read_temp(path):
    """Return the memory junction temperature in C, or None if the read is not plausible."""
    fd = os.open(path, os.O_RDONLY)
    try:
        with mmap.mmap(fd, mmap.PAGESIZE, mmap.MAP_SHARED, mmap.PROT_READ, offset=PAGE) as page:
            temp = decode(struct.unpack_from('<I', page, OFFSET)[0])
    finally:
        os.close(fd)
    return temp if MIN_C <= temp <= MAX_C else None


def render(temps):
    lines = ['# HELP gpu_memory_junction_celsius GDDR6X memory junction temperature.',
             '# TYPE gpu_memory_junction_celsius gauge']
    lines += ['gpu_memory_junction_celsius{role="%s"} %.1f' % (r, t) for r, t in temps.items() if t is not None]
    lines += ['# HELP gpu_memory_junction_read_ok 1 when the register read was plausible.',
              '# TYPE gpu_memory_junction_read_ok gauge']
    lines += ['gpu_memory_junction_read_ok{role="%s"} %d' % (r, t is not None) for r, t in temps.items()]
    return '\n'.join(lines) + '\n'


def gather(paths):
    temps = {}
    for role, path in paths.items():
        try:
            temps[role] = read_temp(path)
        except OSError:
            temps[role] = None
    return temps


def main():
    paths = {'primary': '/pci/primary/resource0', 'peer': '/pci/peer/resource0'}
    if '--once' in sys.argv:
        print(render(gather(paths)), end='')
        return

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/metrics':
                self.send_error(404)
                return
            body = render(gather(paths)).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    http.server.ThreadingHTTPServer(('0.0.0.0', 9103), Handler).serve_forever()


if __name__ == '__main__':
    sys.exit(main())
