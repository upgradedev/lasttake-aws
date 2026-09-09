"""CI-only Chromium preparation without the runner's unrelated Chrome apt source."""
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path


COMMAND = ["npx", "playwright", "install", "--with-deps", "chromium"]
SOURCE_NAMES = ("google-chrome.list", "google-chrome.sources")
CHROME_URIS = {
    f"{scheme}://dl.google.com/linux/{product}/deb"
    for scheme in ("http", "https") for product in ("chrome", "chrome-stable")
}


def chrome_only(path):
    text = path.read_text(encoding="utf-8")
    lines = [line.split("#", 1)[0].strip() for line in text.splitlines()]
    if path.suffix == ".list":
        uris = []
        for line in filter(None, lines):
            match = re.fullmatch(r"deb(?:-src)?\s+(?:\[[^\]]*\]\s+)?(\S+)\s+.+", line)
            if not match:
                raise ValueError(f"Unexpected apt source syntax: {path.name}")
            uris.append(match[1])
    else:
        uris = []
        # Retain original bytes; parsing only decides whether the whole file is safe to move.
        for paragraph in re.split(r"\n\s*\n", text.strip()):
            fields = {}
            previous = None
            for line in paragraph.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                if line[0].isspace() and previous:
                    fields[previous] += " " + line.strip()
                    continue
                name, separator, value = line.partition(":")
                name = name.lower()
                if not separator or name in fields:
                    raise ValueError(f"Unexpected apt source syntax: {path.name}")
                fields[name] = value.strip()
                previous = name
            if not fields:
                continue
            if not fields.get("uris") or not fields.get("types") or not set(fields["types"].split()) <= {"deb", "deb-src"}:
                raise ValueError(f"Unexpected apt source fields: {path.name}")
            uris.extend(fields["uris"].split())
    if any(uri.rstrip("/") not in CHROME_URIS for uri in uris):
        raise ValueError(f"Refusing mixed or unrelated apt source: {path.name}")
    return bool(uris)


def snapshot(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Refusing non-regular apt source: {path.name}")
    return path.read_bytes(), stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid, info.st_mtime_ns


def move_source(source, destination):
    subprocess.run(["sudo", "--", "mv", "--", str(source), str(destination)], check=True)


def install(sources, temporary_root, *, move=move_source, run=subprocess.run):
    selected = []
    for name in SOURCE_NAMES:
        path = sources / name
        if path.exists() or path.is_symlink():
            original = snapshot(path)
            if chrome_only(path):
                selected.append((path, original))
    if not selected:
        return run(COMMAND, check=False).returncode
    saved = Path(tempfile.mkdtemp(prefix="lasttake-chrome-sources-", dir=temporary_root))
    moved = []
    try:
        for path, original in selected:
            backup = saved / path.name
            move(path, backup)
            moved.append((path, backup, original))
            if snapshot(backup) != original:
                raise RuntimeError(f"Apt source changed while moving: {path.name}")
        print("Temporarily excluded Chrome-only apt sources; apt verification is unchanged.", flush=True)
        return run(COMMAND, check=False).returncode
    finally:
        errors = []
        for path, backup, original in reversed(moved):
            try:
                if path.exists() or path.is_symlink():
                    raise RuntimeError(f"Refusing to overwrite a recreated apt source: {path.name}")
                move(backup, path)
                if snapshot(path) != original:
                    raise RuntimeError(f"Apt source restoration mismatch: {path.name}")
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError(f"Apt source restoration failed; retained recovery directory: {saved}") from errors[0]
        saved.rmdir()
        print("Restored Chrome apt source bytes, ownership, mode and modification time.", flush=True)


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux" or os.environ.get("GITHUB_REPOSITORY") != "upgradedev/lasttake-aws":
        raise RuntimeError("This helper is restricted to LastTake Linux CI.")
    return install(Path("/etc/apt/sources.list.d"), Path(os.environ["RUNNER_TEMP"]))


if __name__ == "__main__":
    code = main()
    raise SystemExit(128 - code if code < 0 else code)
