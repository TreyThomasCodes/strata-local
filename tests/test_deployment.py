import importlib.util
import json
import os
from pathlib import Path
import tempfile
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

    def test_empty_key_refused(self):
        entry = load('entrypoint')
        with patch.object(entry.Path, 'read_text', return_value=' \n'):
            with self.assertRaisesRegex(RuntimeError, 'nonempty API key'):
                entry.main()

    def run_entrypoint(self, config_name, mounted='/config/strata.json'):
        entry = load('entrypoint')
        real_path = Path
        with tempfile.TemporaryDirectory() as tmp:
            state = real_path(tmp)
            cfg = (ROOT / 'config' / config_name).read_text()

            def path(value):
                if value == '/var/lib/strata':
                    return state
                return real_path(value)

            def read_text(p, **kwargs):
                if str(p) == '/run/secrets/strata_api_key':
                    return 'test-only-key'
                if str(p) == mounted:
                    return cfg
                raise AssertionError(str(p))

            def exists(p):
                return not str(p).startswith('/config/') or str(p) == mounted

            with patch.dict(os.environ, {'PRIMARY_GPU_UUID': 'GPU-primary', 'PEER_GPU_UUID': 'GPU-peer'}), \
                    patch.object(entry, 'Path', side_effect=path), \
                    patch.object(real_path, 'read_text', read_text), \
                    patch.object(real_path, 'exists', exists), \
                    patch.object(entry.os, 'chdir'), patch.object(entry.os, 'execv') as execv:
                entry.main()
                execv.assert_called_once()
                self.assertEqual(os.environ['STRATA_API_KEY'], 'test-only-key')
            return json.loads((state / 'runtime.json').read_text())

    def test_entrypoint_orders_gpus_and_keeps_key_out_of_config(self):
        for name in ['strata-iq3_s.json', 'strata-orca-iq3_xxs.json']:
            with self.subTest(name):
                runtime = self.run_entrypoint(name)
                saved = json.loads((ROOT / 'config' / name).read_text())
                self.assertEqual(runtime['env']['CUDA_VISIBLE_DEVICES'], 'GPU-primary,GPU-peer')
                self.assertEqual(runtime['model_name'], saved['model_name'])
                self.assertEqual(runtime['args'], saved['args'])
                self.assertEqual(runtime['parallel'], 2)
                self.assertIn('--batch-mtp', runtime['args'])
                self.assertNotIn('test-only-key', json.dumps(runtime))

    def test_entrypoint_reads_pre_profile_mount(self):
        runtime = self.run_entrypoint('strata-iq3_s.json', mounted='/config/strata-iq3_s.json')
        self.assertEqual(runtime['model_name'], 'qwen3.8-flash-next-iq3_s')

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
