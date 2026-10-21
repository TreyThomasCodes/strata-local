import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'docker' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeploymentTests(unittest.TestCase):
    def test_saved_settings(self):
        cfg = json.loads((ROOT / 'config/strata-iq3_s.json').read_text())
        args = cfg['args']
        for flag, value in {'--max-context': '262144', '--conversation-cache-mib': '16384',
                            '--conversation-cache-slots': '8', '--peer-device': '1'}.items():
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertNotIn('api_key', cfg)
        self.assertEqual(cfg['parallel'], 2)
        self.assertNotIn('--layer-split', args)
        self.assertIn('--batch-mtp', args)

    def test_orca_profile_matches_saved_settings(self):
        base = json.loads((ROOT / 'config/strata-iq3_s.json').read_text())
        orca = json.loads((ROOT / 'config/strata-orca-iq3_xxs.json').read_text())
        args = orca['args']
        shard1 = args[args.index('--native') + 1]
        self.assertTrue(shard1.endswith('-IQ3_XXS-00001-of-00002.gguf'))
        self.assertEqual(args[args.index('--ple-gguf') + 1], shard1)  # Orca's PLE table is in shard 1.
        pack = args[args.index('--pack') + 1]
        self.assertEqual(orca['tokenizer'], pack + '/tokenizer')
        self.assertNotEqual(orca['model_name'], base['model_name'])
        self.assertNotIn('api_key', orca)
        model_flags = {'--pack', '--native', '--ple-gguf'}

        def engine(cfg):
            a = cfg['args']
            pairs = [(a[i], a[i + 1] if i + 1 < len(a) and not a[i + 1].startswith('--') else None)
                     for i in range(len(a)) if a[i].startswith('--')]
            rest = {k: v for k, v in cfg.items() if k not in {'tokenizer', 'model_name', 'args'}}
            return rest, [p for p in pairs if p[0] not in model_flags]

        self.assertEqual(engine(orca), engine(base))

    def test_configs_use_the_packaged_engine_and_no_gpu_key(self):
        for name in ['strata-iq3_s.json', 'strata-orca-iq3_xxs.json']:
            with self.subTest(name):
                cfg = json.loads((ROOT / 'config' / name).read_text())
                self.assertEqual(cfg['exe'], 'component:strata-engine')
                self.assertNotIn('lib_dirs', cfg)
                self.assertNotIn('gpu', cfg)  # A "gpu" entry would replace the UUID order from compose.yaml.
                self.assertNotIn('gpu_roles', cfg)
                self.assertTrue(cfg['log'].startswith('/data/'))

    def test_compose_orders_gpus_by_uuid_and_serves_without_key(self):
        compose = (ROOT / 'compose.yaml').read_text()
        block = compose.split('\n  strata:\n')[1]
        self.assertIn('CUDA_VISIBLE_DEVICES: ${PRIMARY_GPU_UUID:?Set PRIMARY_GPU_UUID in .env},'
                      '${PEER_GPU_UUID:?Set PEER_GPU_UUID in .env}', block)
        self.assertIn('"--no-api-key"', block)
        self.assertIn('STRATA_ALLOWED_HOSTS: strata,', block)  # Prometheus scrapes by service name.
        self.assertIn('"--config", "/config/strata.json"', block)
        self.assertNotIn('secrets', compose)
        self.assertNotIn('STRATA_API_KEY', compose)
        self.assertIn('${STRATA_BIND_HOST:-127.0.0.1}', compose)
        self.assertRegex(compose, r'image: ghcr\.io/niko1221/strata:[^@\s]+@sha256:[0-9a-f]{64}')

    def test_model_mounts_are_read_only(self):
        compose = (ROOT / 'compose.yaml').read_text()
        mount = compose.split('target: /models-data')[1].split('bind:')[0]
        self.assertIn('read_only: true', mount)

    def test_power_policy_requires_distinct_gpus(self):
        policy = load('power-policy')
        with patch.dict(os.environ, {'PRIMARY_GPU_UUID': 'GPU-one', 'PEER_GPU_UUID': 'GPU-one'}):
            with self.assertRaises(ValueError):
                policy.policy()

    def test_power_policy_readback(self):
        policy = load('power-policy')
        caps = {'GPU-primary': 300, 'GPU-peer': 350}
        with patch.object(policy.subprocess, 'check_output', return_value='GPU-primary, 300\nGPU-peer, 350\n'):
            self.assertTrue(policy.check(caps))
        with patch.object(policy.subprocess, 'check_output', return_value='GPU-primary, 350\nGPU-peer, 350\n'):
            self.assertFalse(policy.check(caps))


if __name__ == '__main__':
    unittest.main()
