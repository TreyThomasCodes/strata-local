"""Start the pinned engine with an external key and UUID-ordered peer GPUs."""
import json
import os
from pathlib import Path


def main():
    key = Path('/run/secrets/strata_api_key').read_text(encoding='utf-8').strip()
    if not key:
        raise RuntimeError('A nonempty API key is required, including for LAN serving')
    primary = os.environ['PRIMARY_GPU_UUID']
    peer = os.environ['PEER_GPU_UUID']
    if not primary.startswith('GPU-') or not peer.startswith('GPU-') or primary == peer:
        raise ValueError('Configure two distinct GPU UUIDs')
    cfg = json.loads(Path('/config/strata-iq3_s.json').read_text(encoding='utf-8'))
    cfg.pop('api_key', None)
    cfg['gpu'] = 1  # Upstream server selects the engine; cfg.env sets explicit ordering.
    cfg['env'] = {'CUDA_VISIBLE_DEVICES': f'{primary},{peer}',
                  'CUDA_DEVICE_ORDER': 'PCI_BUS_ID'}
    cfg['host'], cfg['port'] = '0.0.0.0', 8080
    state = Path('/var/lib/strata')
    state.mkdir(parents=True, exist_ok=True)
    cfg['log'] = str(state / 'strata.log')
    for path in [cfg['exe'], cfg['tokenizer']] + [x for x in cfg['args'] if x.startswith('/')]:
        if not Path(path).exists():
            raise FileNotFoundError(path)
    runtime = state / 'runtime.json'
    runtime.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
    os.environ['STRATA_API_KEY'] = key
    os.chdir(cfg['cwd'])
    os.execv('/opt/strata/.venv/bin/python', [
        '/opt/strata/.venv/bin/python', '/opt/strata/serve/server.py',
        '--engine', 'strata', '--config', str(runtime),
        '--host', '0.0.0.0', '--port', '8080',
    ])


if __name__ == '__main__':
    main()
