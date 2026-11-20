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
            self.assertEqual(len(list(target.rglob('*.md'))),8)  # SKILL + 6 references + local-runtime

    def test_installs_research_lineage_skill(self):
        from scholarly_access_agent.installer import SKILLS_DIR
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'research-lineage'
            install(target, Path('/opt/test/bin/scholarly-access-agent'), SKILLS_DIR / 'research-lineage')
            self.assertTrue((target / 'SKILL.md').is_file())
            self.assertTrue((target / 'references/lineage-json.md').is_file())
            self.assertTrue((target / 'examples/les/lineage.json').is_file())
            self.assertIn(str(Path('/opt/test/bin/scholarly-access-agent')), (target / 'references/local-runtime.md').read_text())
