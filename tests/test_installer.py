import tempfile
import unittest
from pathlib import Path
from scholarly_access_agent.installer import install
class InstallTests(unittest.TestCase):
    def test_installs_references_and_local_hint(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'skill'
            install(target,Path('/opt/test/bin/scholarly-access-agent'))
            self.assertTrue((target/'SKILL.md').is_file())
            self.assertTrue((target/'references/dft-mlip.md').is_file())
            self.assertIn('/opt/test/bin/',(target/'references/local-runtime.md').read_text())
            self.assertEqual(len(list(target.rglob('*.md'))),6)
