"""Install only skill instructions; never package sessions or downloaded PDFs."""
from pathlib import Path
import shutil
import zipfile
import sys

import sysconfig

SKILLS = ("snu-library-scholarly-access", "research-lineage", "research-topic-scout", "research-pilot")
ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "skills"
if not (SKILLS_DIR / SKILLS[0]).is_dir():
    SKILLS_DIR = Path(sysconfig.get_path("data")) / "share/snu-research-agent"
    ROOT = Path.cwd()
SOURCE = SKILLS_DIR / SKILLS[0]  # kept for callers that expect the main skill path


def install(destination: Path, executable: Path, source: Path = SOURCE):
    shutil.copytree(source, destination, dirs_exist_ok=True)
    (destination / "references").mkdir(exist_ok=True)
    (destination / "references/local-runtime.md").write_text(
        "# Local CLI fallback\n\nExecutable: `" + str(executable) + "`\n", encoding="utf-8")


def main():
    executable = Path(sys.executable).parent / "scholarly-access-agent"
    for name in SKILLS:
        source = SKILLS_DIR / name
        if not source.is_dir():
            continue
        for client in (".codex", ".claude"):
            install(Path.home() / client / "skills" / name, executable, source)
        output = ROOT / "dist" / (name + ".zip")
        output.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_file() and path.name != "local-runtime.md":
                    archive.write(path, path.relative_to(source.parent))
        print(f"Installed {name} for Codex and Claude Code; Claude upload:", output)
