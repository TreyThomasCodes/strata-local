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

    def test_key_comes_from_secret_files_only(self):
        tmpl = (ROOT / 'monitoring/prometheus.yml.tmpl').read_text()
        self.assertIn('credentials_file: /run/secrets/strata_api_key', tmpl)
        self.assertNotRegex(tmpl, r'(?m)^\s*credentials:')
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
