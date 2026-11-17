"""Install only skill instructions; never package sessions or downloaded PDFs."""
from pathlib import Path
import shutil
import zipfile
import sys

import sysconfig
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "skills/snu-library-scholarly-access"
if not SOURCE.is_dir():
    SOURCE = Path(sysconfig.get_path("data")) / "share/snu-research-agent/snu-library-scholarly-access"
    ROOT = Path.cwd()

def install(destination: Path, executable: Path):
    shutil.copytree(SOURCE, destination, dirs_exist_ok=True)
    (destination / "references/local-runtime.md").write_text(
        "# Local CLI fallback\n\nExecutable: `" + str(executable) + "`\n", encoding="utf-8")

def main():
    executable = Path(sys.executable).parent / "scholarly-access-agent"
    for client in (".codex", ".claude"):
        install(Path.home() / client / "skills" / SOURCE.name, executable)
    output = ROOT / "dist" / (SOURCE.name + ".zip")
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SOURCE.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(SOURCE.parent))
    print("Installed Codex and Claude Code skills; Claude upload:", output)
