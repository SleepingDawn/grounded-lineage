"""One-shot setup after the bootstrap (install.ps1 / install.sh) has built the venv.

Runs inside this repository's virtual environment. Every step checks first and skips what
is already done, so rerunning is safe; rerun it when a session expires. Steps that need a
person (SNU sign-in, ReadCube sign-in, OpenAlex key, ReadCube write verification) are only
offered in an interactive terminal. Passwords and keys are never printed or passed as
command-line arguments.

    python scripts/install_all.py [--root DIR] [--readcube | --no-readcube]
                                  [--non-interactive] [--update] [--no-register]
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"
QUARTO_VERSION = "1.11.9"
READCUBE_URL = "https://github.com/Zhilin0001/readcube-mcp.git"
# Reviewed revision of the unofficial ReadCube MCP; --update follows its default branch.
READCUBE_REF = "c8011208a2833836ba2a710b073c6edbbe2605e9"
PROBE_URL = "https://www.nature.com/articles/s43588-023-00561-9"
READCUBE_NEEDED = ("list_collections", "import_identifier", "create_list", "add_to_list")
STATUS: dict[str, str] = {}


# ------------------------------------------------------------------ output and processes
def step(title: str) -> None:
    print(f"\n== {title}", flush=True)


def ok(msg: str) -> None:
    print(f"  [OK] {msg}", flush=True)


def skip(msg: str) -> None:
    print(f"  [--] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  [!!] {msg}", flush=True)


def run(cmd, *, check: bool = True, cwd=None, capture: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run([str(c) for c in cmd], cwd=cwd, text=True, encoding="utf-8",
                            errors="replace", capture_output=capture)
    if check and result.returncode != 0:
        raise SystemExit(f"Command failed ({result.returncode}): {' '.join(map(str, cmd))}")
    return result


def quiet_ok(cmd, cwd=None) -> bool:
    try:
        return subprocess.run([str(c) for c in cmd], cwd=cwd, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def json_tail(text: str) -> dict:
    """Parse the JSON object at the end of a command's output (tools may log before it)."""
    start = text.find("{")
    return json.loads(text[start:]) if start >= 0 else {}


def ask(question: str, args) -> bool:
    if args.non_interactive:
        return False
    try:
        return input(f"  {question} [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def venv_bin(venv: Path, name: str) -> Path:
    return venv / ("Scripts" if WINDOWS else "bin") / (name + (".exe" if WINDOWS else ""))


def find_uv(explicit: str | None) -> str:
    for candidate in (explicit, shutil.which("uv"),
                      str(Path.home() / ".local/bin" / ("uv.exe" if WINDOWS else "uv")),
                      str(Path.home() / ".cargo/bin" / ("uv.exe" if WINDOWS else "uv"))):
        if candidate and Path(candidate).is_file():
            return candidate
    raise SystemExit("uv not found; run install.ps1 / install.sh, which installs it.")


# ------------------------------------------------------------------ persistent settings
def user_env_get(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    if WINDOWS:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                return winreg.QueryValueEx(key, name)[0] or None
        except OSError:
            return None
    return None


def user_env_set_windows(name: str, value: str) -> None:
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    # Tell running programs (Explorer, new terminals) that the environment changed.
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)


def shell_rc() -> Path:
    shell = os.environ.get("SHELL", "")
    return Path.home() / (".zshrc" if shell.endswith("zsh") or sys.platform == "darwin" else ".bashrc")


# ------------------------------------------------------------------ steps
def setup_browser_and_skills(args) -> None:
    step("1/7 Browser engine and skills")
    run([sys.executable, "-m", "playwright", "install", "chromium"])
    probe = ("from playwright.sync_api import sync_playwright\n"
             "with sync_playwright() as p: p.chromium.launch(headless=True).close()")
    if quiet_ok([sys.executable, "-c", probe]):
        ok("Headless Chromium starts")
    else:
        warn("Headless Chromium does not start."
             + (" On Linux run: sudo " + sys.executable + " -m playwright install-deps chromium"
                if sys.platform.startswith("linux") else ""))
    if args.no_register:
        skip("Skill installation skipped (--no-register)")
    else:
        from scholarly_access_agent.installer import main as install_skills

        install_skills()
    STATUS["skills"] = "OK"


def quarto_asset_name() -> str:
    if WINDOWS:
        return f"quarto-{QUARTO_VERSION}-win.zip"
    if sys.platform == "darwin":
        return f"quarto-{QUARTO_VERSION}-macos.tar.gz"
    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "amd64"
    return f"quarto-{QUARTO_VERSION}-linux-{arch}.tar.gz"


def find_quarto(root: Path) -> str | None:
    from scholarly_access_agent.runtime.quarto_report import find_quarto as package_find

    own = root / "quarto" / "bin" / ("quarto.exe" if WINDOWS else "quarto")
    for candidate in (user_env_get("QUARTO_PATH"), package_find(), str(own)):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def setup_quarto(args) -> str | None:
    step("2/7 Quarto (HTML reports)")
    quarto = find_quarto(args.root)
    if quarto:
        skip(f"Found: {quarto}")
    else:
        name = quarto_asset_name()
        api = f"https://api.github.com/repos/quarto-dev/quarto-cli/releases/tags/v{QUARTO_VERSION}"
        request = urllib.request.Request(api, headers={"User-Agent": "grounded-lineage-installer"})
        with urllib.request.urlopen(request, timeout=60) as response:
            release = json.load(response)
        asset = next((a for a in release.get("assets", []) if a["name"] == name), None)
        if not asset:
            warn(f"{name} not found; reports will fall back to PDF.")
            STATUS["quarto"] = "missing"
            return None
        print(f"  Downloading {name} ({asset['size'] // 2**20} MB)", flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / name
            with urllib.request.urlopen(asset["browser_download_url"], timeout=600) as response, \
                    open(archive, "wb") as out:
                shutil.copyfileobj(response, out)
            want = (asset.get("digest") or "").removeprefix("sha256:").lower()
            got = hashlib.sha256(archive.read_bytes()).hexdigest()
            if want and want != got:
                raise SystemExit("Quarto archive hash does not match the release; stopped.")
            unpacked = Path(tmp) / "unpacked"
            if name.endswith(".zip"):
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(unpacked)
            else:
                with tarfile.open(archive) as tf:
                    if sys.version_info >= (3, 12):
                        tf.extractall(unpacked, filter="data")
                    else:
                        tf.extractall(unpacked)
            exe = "quarto.exe" if WINDOWS else "quarto"
            home = next(p.parent.parent for p in unpacked.rglob(exe) if p.parent.name == "bin")
            target = args.root / "quarto"
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(home), str(target))
        quarto = str(target / "bin" / exe)
        ok(f"Quarto {QUARTO_VERSION} installed (hash checked)")
    if not quiet_ok([quarto, "--version"]):
        warn(f"{quarto} does not run; reports will fall back to PDF.")
        STATUS["quarto"] = "blocked"
        return None
    if WINDOWS and user_env_get("QUARTO_PATH") != quarto:
        user_env_set_windows("QUARTO_PATH", quarto)
        ok("QUARTO_PATH saved as a user environment variable")
    os.environ["QUARTO_PATH"] = quarto
    STATUS["quarto"] = "OK"
    return quarto


def setup_readcube(args, uv: str) -> Path | None:
    step("3/7 ReadCube filing (optional, unofficial readcube-mcp)")
    rc = args.root / "readcube-mcp"
    wanted = args.readcube
    if wanted is None:
        wanted = rc.exists() or ask(
            "File papers in ReadCube? Installs the unofficial Zhilin0001/readcube-mcp "
            "and needs a ReadCube email+password account (no SSO/MFA).", args)
    if not wanted:
        skip("Not set up (rerun with --readcube to add it)")
        STATUS["readcube"] = "not set up"
        return None
    changed = False
    if not (rc / ".git").exists():
        run(["git", "clone", READCUBE_URL, rc])
        run(["git", "-c", "advice.detachedHead=false", "checkout", READCUBE_REF], cwd=rc)
        changed = True
        ok(f"Cloned readcube-mcp at {READCUBE_REF[:7]}")
    elif args.update:
        run(["git", "fetch", "origin"], cwd=rc)
        run(["git", "-c", "advice.detachedHead=false", "checkout", "origin/HEAD"], cwd=rc)
        changed = True
    else:
        skip(f"Found: {rc}")
    py = venv_bin(rc / ".venv", "python")
    if not py.exists():
        run([uv, "venv", "--python", "3.12", rc / ".venv"])
        changed = True
    if changed or not quiet_ok([py, "-c", "import readcube_mcp.server"]):
        run([uv, "pip", "install", "--python", py, "-e", ".[mcp,realtime]"], cwd=rc)
    toml = rc / "readcube.local.toml"
    if not toml.exists():
        text = (rc / "readcube.example.toml").read_text(encoding="utf-8")
        toml.write_text(text.replace("dry_run = true", "dry_run = false"), encoding="utf-8")
        ok("readcube.local.toml created (dry_run = false so filing really writes)")
    return rc


def register_mcp(args, agent: Path, quarto: str | None, rc: Path | None) -> None:
    step("4/7 Register MCP servers")
    if args.no_register:
        skip("Skipped (--no-register)")
        return
    env = {"PYTHONUTF8": "1", **({"QUARTO_PATH": quarto} if quarto else {})}
    servers = {"snu-library": {"type": "stdio", "command": str(agent), "args": ["mcp-server"],
                               "env": env}}
    if rc:
        servers["readcube"] = {
            "type": "stdio", "command": str(venv_bin(rc / ".venv", "python")),
            "args": ["-m", "readcube_mcp", "--config", str(rc / "readcube.local.toml")],
            "cwd": str(rc), "env": {"PYTHONUTF8": "1"}}

    config = Path.home() / ".claude.json"
    data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
    current = data.setdefault("mcpServers", {})
    changed = [name for name, entry in servers.items() if current.get(name) != entry]
    if changed:
        if config.exists():
            shutil.copy2(config, config.with_name(config.name + time.strftime(".bak-%Y%m%d-%H%M%S")))
        current.update(servers)
        config.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        ok(f"Claude Code (~/.claude.json): {', '.join(changed)}")
    else:
        skip("Claude Code: already registered")

    codex = Path.home() / ".codex"
    if codex.is_dir():
        path = codex / "config.toml"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        blocks = []
        if "[mcp_servers.snu-library]" not in text:
            blocks.append(
                "[mcp_servers.snu-library]\n"
                f"command = '{agent}'\nargs = [\"mcp-server\"]\nstartup_timeout_sec = 30\n"
                "tool_timeout_sec = 300\ndefault_tools_approval_mode = \"approve\"\n"
                + (f"env = {{ PYTHONUTF8 = \"1\", QUARTO_PATH = '{quarto}' }}\n" if quarto
                   else "env = { PYTHONUTF8 = \"1\" }\n")
                + "\n[mcp_servers.snu-library.tools.add_domain]\napproval_mode = \"prompt\"\n")
        if rc and "[mcp_servers.readcube]" not in text:
            blocks.append(
                "[mcp_servers.readcube]\n"
                f"command = '{venv_bin(rc / '.venv', 'python')}'\n"
                f"args = [\"-m\", \"readcube_mcp\", \"--config\", '{rc / 'readcube.local.toml'}']\n"
                "env = { PYTHONUTF8 = \"1\" }\ntool_timeout_sec = 300\n")
        if blocks:
            if path.exists():
                shutil.copy2(path, path.with_name(path.name + time.strftime(".bak-%Y%m%d-%H%M%S")))
            with open(path, "a", encoding="utf-8") as out:
                out.write("\n" + "\n".join(blocks))
            ok("Codex (~/.codex/config.toml): added")
        else:
            skip("Codex: already registered")


def setup_openalex(args) -> None:
    step("5/7 OpenAlex API key (optional: lineage quota 1,000 -> 10,000 credits/day)")
    if user_env_get("OPENALEX_API_KEY"):
        skip("Already set")
        STATUS["openalex"] = "OK"
        return
    if args.non_interactive:
        warn("Not set")
        STATUS["openalex"] = "none"
        return
    try:
        key = getpass.getpass("  OpenAlex API key (hidden; Enter to skip): ").strip()
    except EOFError:
        key = ""
    if not key:
        skip("Skipped")
        STATUS["openalex"] = "none"
        return
    if WINDOWS:
        user_env_set_windows("OPENALEX_API_KEY", key)
        ok("Saved as a user environment variable")
    else:
        rc = shell_rc()
        if ask(f"Append 'export OPENALEX_API_KEY=...' to {rc}?", args):
            with open(rc, "a", encoding="utf-8") as out:
                out.write(f"\nexport OPENALEX_API_KEY='{key}'\n")
            ok(f"Added to {rc} (new terminals)")
        else:
            warn("Not saved; export OPENALEX_API_KEY yourself")
    os.environ["OPENALEX_API_KEY"] = key
    STATUS["openalex"] = "OK"


def browser_channels() -> list[str | None]:
    """Order to try for the visible sign-in window. On Windows the bundled Chromium can be
    blocked by application control, so an installed Chrome/Edge goes first there."""
    installed = []
    if WINDOWS:
        roots = [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                 os.environ.get("LOCALAPPDATA", "")]
        if any(Path(r, "Google/Chrome/Application/chrome.exe").is_file() for r in roots if r):
            installed.append("chrome")
        if any(Path(r, "Microsoft/Edge/Application/msedge.exe").is_file() for r in roots if r):
            installed.append("msedge")
        return installed + [None]
    if sys.platform == "darwin" and Path("/Applications/Google Chrome.app").exists():
        installed.append("chrome")
    return [None] + installed


def setup_snu_session(args, agent: Path) -> None:
    step("6/7 SNU library off-campus session")
    doctor = json_tail(run([agent, "doctor"], capture=True).stdout)
    if not doctor.get("session_present"):
        headless_linux = sys.platform.startswith("linux") and not os.environ.get("DISPLAY") \
            and not os.environ.get("WAYLAND_DISPLAY")
        if headless_linux:
            warn("No display: sign in on a desktop machine (the session is per machine).")
        elif ask("Open the SNU sign-in window? Sign in in the browser, then press Enter here.", args):
            for channel in browser_channels():
                cmd = [agent, "open-url", PROBE_URL, "--wait-for-login", "--headless", "false",
                       "--timeout-ms", "60000"] + (["--browser-channel", channel] if channel else [])
                result = run(cmd, check=False, capture=True)
                print(result.stdout.strip()[-400:])
                if json_tail(result.stdout).get("ok"):
                    break
                warn(f"Sign-in window failed with browser {channel or 'bundled Chromium'}")
            doctor = json_tail(run([agent, "doctor"], capture=True).stdout)
    if not doctor.get("session_present"):
        warn("No session: only open-access papers can be read.")
        STATUS["snu"] = "none"
        return
    if args.non_interactive:
        ok("Session present (validity not probed)")
        STATUS["snu"] = "present"
        return
    probe = json_tail(run([agent, "doctor", "--probe", PROBE_URL], capture=True, check=False).stdout)
    if probe.get("session_validity") == "valid":
        ok("Subscription PDF download works")
        STATUS["snu"] = "valid"
    else:
        warn(f"Session not valid ({probe.get('session_validity')}); rerun to sign in again.")
        STATUS["snu"] = "expired"


RC_SESSION = """
import json, sys
from pathlib import Path
from readcube_client.auth import validate_saved_session
p = Path.home() / ".config/readcube-client/session.json"
if not p.exists(): sys.exit(1)
try: r = validate_saved_session(p, persist_cookies=False)  # saving rotated cookies voids verification
except Exception: sys.exit(1)
print(json.dumps({"collections": r.get("collection_count")}))
"""
RC_CAPS = """
import json, sys
from readcube_client import ReadCubeClient, Settings
with ReadCubeClient(Settings.from_toml("readcube.local.toml")) as c: caps = c.capabilities()
print(json.dumps({op: (caps.get(op) or {}).get("verification", "UNKNOWN") for op in sys.argv[1:]}))
"""
RC_CLEANUP = """
import json, sys
from pathlib import Path
from readcube_client import Settings, WriteAuthorization
from readcube_client.research import ResearchClient
name = sys.argv[1]
target = json.loads(Path("research/private/test-target.json").read_text(encoding="utf-8"))
if target.get("name") != name: sys.exit("test-target.json names another collection; nothing deleted")
cid = target["collection_id"]
with ResearchClient(Settings.from_toml("readcube.local.toml"), acknowledge_unverified=True) as c:
    live = [x for x in c.list_collections() if x["id"] == cid]
    if not live or live[0].get("name") != name: sys.exit("collection name mismatch; nothing deleted")
    failed = []
    for delete, rows in ((c.delete_list, sorted(c.list_lists(cid), key=lambda x: 0 if x.get("parent_id") else 1)),
                         (c.delete_item, c.list_items(cid))):
        for row in rows:
            auth = WriteAuthorization(collection_id=cid, authorized=True, confirmation="DELETE " + row["id"])
            try: delete(cid, row["id"], authorization=auth, dry_run=False)
            except Exception as e: failed.append([row["id"], type(e).__name__])
    print(json.dumps({"failed": failed, "items_left": len(c.list_items(cid)), "lists_left": len(c.list_lists(cid))}))
"""


def setup_readcube_session(args, rc: Path | None) -> None:
    step("7/7 ReadCube sign-in and write verification")
    if not rc:
        skip("ReadCube not set up")
        return
    py = venv_bin(rc / ".venv", "python")
    if not quiet_ok([py, "-c", RC_SESSION], cwd=rc):
        if ask("Sign in to ReadCube now? (prompts are in Chinese: 邮箱 = email, 密码 = password)",
               args):
            run([py, "scripts/login_local.py"], cwd=rc, check=False)
    if not quiet_ok([py, "-c", RC_SESSION], cwd=rc):
        warn("No ReadCube session: filing will be skipped.")
        STATUS["readcube"] = "no session"
        return
    ok("ReadCube session works")

    def unverified() -> list[str]:
        caps = json_tail(run([py, "-c", RC_CAPS, *READCUBE_NEEDED], cwd=rc, capture=True).stdout)
        return [op for op in READCUBE_NEEDED if caps.get(op) != "VERIFIED"]

    missing = unverified()
    if missing and ask(
            f"Verify writes ({', '.join(missing)}) in a private test collection, then empty it?",
            args):
        name = "grounded-lineage verify " + time.strftime("%Y-%m-%d")
        # verify_api.py can stop on a later, unneeded check; the capabilities decide.
        run([py, "scripts/verify_api.py", "--config", "readcube.local.toml", "--execute",
             "--test-collection", name, "--authorized-test-collection", name], cwd=rc, check=False)
        run([py, "-c", RC_CLEANUP, name], cwd=rc, check=False)
        warn(f"The emptied collection '{name}' cannot be deleted through the API; "
             "delete it in the ReadCube app.")
        missing = unverified()
    if missing:
        warn(f"Unverified: {', '.join(missing)}; ReadCube filing will be skipped.")
        STATUS["readcube"] = "unverified"
    else:
        ok("Writes verified (create list, add to list, import DOI)")
        STATUS["readcube"] = "OK"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=REPO.parent,
                        help="Folder holding grounded-lineage, quarto/ and readcube-mcp/")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--readcube", dest="readcube", action="store_true", default=None)
    group.add_argument("--no-readcube", dest="readcube", action="store_false")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Never prompt: install and check only")
    parser.add_argument("--update", action="store_true", help="Also update readcube-mcp")
    parser.add_argument("--no-register", action="store_true",
                        help="Do not install skills or touch Claude/Codex configuration")
    parser.add_argument("--uv", help="Path to uv (set by the bootstrap)")
    args = parser.parse_args()
    args.root = args.root.expanduser().resolve()
    if not sys.stdin.isatty():
        args.non_interactive = True
    uv = find_uv(args.uv)
    agent = venv_bin(REPO / ".venv", "scholarly-access-agent")

    setup_browser_and_skills(args)
    quarto = setup_quarto(args)
    rc = setup_readcube(args, uv)
    register_mcp(args, agent, quarto, rc)
    setup_openalex(args)
    setup_snu_session(args, agent)
    setup_readcube_session(args, rc)

    step("Summary")
    for key, value in STATUS.items():
        print(f"  {key:<10} {value}")
    print("\n  Restart Claude Code / Codex so the MCP servers connect.")


if __name__ == "__main__":
    main()
