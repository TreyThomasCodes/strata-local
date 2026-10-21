import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.compose = (ROOT / 'compose.monitoring.yaml').read_text()

    def test_only_grafana_publishes_a_port_on_loopback_by_default(self):
        self.assertEqual(self.compose.count('ports:'), 1)
        self.assertIn('${GRAFANA_BIND_HOST:-127.0.0.1}', self.compose)

    def test_no_privilege_or_model_access(self):
        self.assertNotIn('cap_add', self.compose)
        self.assertNotIn('STRATA_DATA_DIR', self.compose)
        self.assertNotIn('privileged', self.compose)

    def test_grafana_password_comes_from_a_secret_file(self):
        tmpl = (ROOT / 'monitoring/prometheus.yml.tmpl').read_text()
        self.assertNotIn('authorization', tmpl)  # Strata serves the trusted LAN without a key.
        self.assertIn('GF_SECURITY_ADMIN_PASSWORD__FILE', self.compose)
        self.assertNotRegex(self.compose, r'GF_SECURITY_ADMIN_PASSWORD:')

    def test_images_are_pinned(self):
        for image in re.findall(r'image: (\S+)', self.compose):
            self.assertNotIn(image.rsplit(':', 1)[-1], ('latest', image))

    def test_gpu_roles_are_uuid_bound(self):
        tmpl = (ROOT / 'monitoring/prometheus.yml.tmpl').read_text()
        self.assertIn('@PRIMARY_GPU_UUID@', tmpl)
        self.assertIn('@PEER_GPU_UUID@', tmpl)
        self.assertIn('action: labeldrop', tmpl)
        self.assertIn('PRIMARY_GPU_UUID', self.compose)
        self.assertIn('PEER_GPU_UUID', self.compose)

    def test_dashboards_use_the_provisioned_datasource(self):
        dash = json.loads((ROOT / 'monitoring/grafana/dashboards/rig-health.json').read_text())
        uids = {t['datasource']['uid'] for p in dash['panels'] if 'targets' in p for t in p['targets']}
        self.assertEqual(uids, {'strata-prometheus'})
        ds = (ROOT / 'monitoring/grafana/provisioning/datasources/prometheus.yaml').read_text()
        self.assertIn('uid: strata-prometheus', ds)


if __name__ == '__main__':
    unittest.main()


class NvlinkExporterTests(unittest.TestCase):
    def load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('nvlink_exporter', ROOT / 'docker' / 'nvlink-exporter.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_parse_and_render_label_roles_and_drop_unknown_gpus(self):
        mod = self.load()
        text = ('GPU 0: NVIDIA GeForce RTX 3090 (UUID: GPU-aaa)\n'
                '\t Link 0: Data Tx: 10 KiB\n\t Link 0: Data Rx: 4 KiB\n'
                'GPU 1: NVIDIA GeForce RTX 3090 (UUID: GPU-bbb)\n'
                '\t Link 0: Data Tx: 4 KiB\n'
                'GPU 2: NVIDIA GeForce RTX 3090 (UUID: GPU-ccc)\n'
                '\t Link 0: Data Tx: 1 KiB\n')
        out = mod.render(mod.parse(text), {'GPU-aaa': 'primary', 'GPU-bbb': 'peer'})
        self.assertIn('nvlink_data_bytes_total{role="primary",link="0",direction="tx"} 10240', out)
        self.assertIn('nvlink_data_bytes_total{role="primary",link="0",direction="rx"} 4096', out)
        self.assertIn('role="peer"', out)
        self.assertNotIn('GPU-', out)
        self.assertEqual(out.count('role='), 3)


class MemtempExporterTests(unittest.TestCase):
    def load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('memtemp_exporter', ROOT / 'docker' / 'memtemp-exporter.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fake_bar(self, tmp, raw):
        import struct
        path = Path(tmp) / 'resource0'
        data = bytearray(0xE000 + 4096)
        struct.pack_into('<I', data, 0xE000 + 0x2A8, raw)
        path.write_bytes(bytes(data))
        return str(path)

    def test_decodes_plausible_value(self):
        import tempfile
        mod = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(mod.read_temp(self.fake_bar(tmp, 0x5A0 | 0xF000)), 45.0)

    def test_rejects_implausible_values(self):
        import tempfile
        mod = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(mod.read_temp(self.fake_bar(tmp, 0)))
            self.assertIsNone(mod.read_temp(self.fake_bar(tmp, 0xFFF)))

    def test_failed_read_has_no_sample(self):
        out = self.load().render({'primary': 61.5, 'peer': None})
        self.assertIn('gpu_memory_junction_celsius{role="primary"} 61.5', out)
        self.assertNotIn('gpu_memory_junction_celsius{role="peer"}', out)
        self.assertIn('gpu_memory_junction_read_ok{role="peer"} 0', out)

    def test_service_is_read_only_and_opt_in(self):
        compose = (ROOT / 'compose.monitoring.yaml').read_text()
        block = compose.split('  memtemp-exporter:')[1].split('\n  node-exporter:')[0]
        self.assertIn('profiles: [memtemp]', block)
        self.assertNotIn('cap_add', block)
        self.assertNotIn('ports:', block)
        self.assertEqual(block.count('read_only: true'), 3)
