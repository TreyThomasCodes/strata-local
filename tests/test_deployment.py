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

    def test_empty_key_refused(self):
        entry = load('entrypoint')
        with patch.object(entry.Path, 'read_text', return_value=' \n'):
            with self.assertRaisesRegex(RuntimeError, 'nonempty API key'):
                entry.main()

    def test_entrypoint_orders_gpus_and_keeps_key_out_of_config(self):
        entry = load('entrypoint')
        real_path = Path
        with tempfile.TemporaryDirectory() as tmp:
            state = real_path(tmp)
            cfg = (ROOT / 'config/strata-iq3_s.json').read_text()

            def path(value):
                if value == '/var/lib/strata':
                    return state
                return real_path(value)

            def read_text(p, **kwargs):
                if str(p) == '/run/secrets/strata_api_key':
                    return 'test-only-key'
                if str(p) == '/config/strata-iq3_s.json':
                    return cfg
                raise AssertionError(str(p))

            with patch.dict(os.environ, {'PRIMARY_GPU_UUID': 'GPU-primary', 'PEER_GPU_UUID': 'GPU-peer'}), \
                    patch.object(entry, 'Path', side_effect=path), \
                    patch.object(real_path, 'read_text', read_text), \
                    patch.object(real_path, 'exists', return_value=True), \
                    patch.object(entry.os, 'chdir'), patch.object(entry.os, 'execv') as execv:
                entry.main()
                execv.assert_called_once()
                self.assertEqual(os.environ['STRATA_API_KEY'], 'test-only-key')
            runtime = json.loads((state / 'runtime.json').read_text())
            self.assertEqual(runtime['env']['CUDA_VISIBLE_DEVICES'], 'GPU-primary,GPU-peer')
            self.assertEqual(runtime['parallel'], 2)
            self.assertIn('--batch-mtp', runtime['args'])
            self.assertNotIn('test-only-key', json.dumps(runtime))

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
