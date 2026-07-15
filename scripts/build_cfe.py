#!/usr/bin/env python3
import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_v8_exe(v8_path: str) -> Path:
    candidate = Path(v8_path)
    if candidate.is_file():
        return candidate.resolve()

    candidate = candidate / "1cv8.exe"
    if candidate.is_file():
        return candidate.resolve()

    roots = sorted(Path(r"C:\Program Files\1cv8").glob(r"*\bin\1cv8.exe"), reverse=True)
    if roots:
        return roots[0].resolve()

    raise FileNotFoundError("1cv8.exe not found. Pass it with --v8-path.")


def extension_name(source_dir: Path) -> str:
    config_xml = source_dir / "Configuration.xml"
    text = config_xml.read_text(encoding="utf-8-sig")
    match = re.search(r"<Name>([^<]+)</Name>", text)
    if not match:
        raise ValueError(f"Extension name not found in {config_xml}")
    return match.group(1)


def read_log(path: Path) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1251", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def run_designer(v8_exe: Path, args: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    cmd = [str(v8_exe), *args, "/Out", str(log_path), "/DisableStartupDialogs"]
    print(">", " ".join(f'"{part}"' if " " in part else part for part in cmd))

    result = subprocess.run(cmd, cwd=repo_root())
    log_text = read_log(log_path).strip()
    if log_text:
        print(log_text)

    if result.returncode != 0:
        raise RuntimeError(f"1cv8.exe failed with exit code {result.returncode}. Log: {log_path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build CFE from XML extension sources.")
    parser.add_argument("--v8-path", default=os.environ.get("ONEC_V8_PATH", r"C:\Program Files\1cv8\8.5.1.1150\bin"))
    parser.add_argument("--file", default=os.environ.get("ONEC_FILE", ""))
    parser.add_argument("--server", default=os.environ.get("ONEC_SERVER", ""))
    parser.add_argument("--ref", default=os.environ.get("ONEC_REF", ""))
    parser.add_argument("--user", default=os.environ.get("ONEC_USER", ""))
    parser.add_argument("--password", default=os.environ.get("ONEC_PASSWORD", ""))
    parser.add_argument("--extension", default="")
    parser.add_argument("--src", default="src")
    parser.add_argument("--out", default="")
    parser.add_argument("--skip-load", action="store_true", help="Only dump CFE from the current extension in the infobase.")
    args = parser.parse_args()

    root = repo_root()
    v8_exe = resolve_v8_exe(args.v8_path)
    source_dir = (root / args.src).resolve()
    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    extension = args.extension or extension_name(source_dir)
    out_file = Path(args.out or (Path("dist") / f"{extension}.cfe"))
    if not out_file.is_absolute():
        out_file = root / out_file
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if args.file and (args.server or args.ref):
        raise ValueError("Use either --file or --server/--ref, not both.")
    if not args.file and (not args.server or not args.ref):
        raise ValueError(
            "Set infobase with --file or --server/--ref, or environment variables ONEC_FILE/ONEC_SERVER/ONEC_REF."
        )

    runtime_dir = root / ".runtime" / "build-cfe"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    if args.file:
        connection = args.file
        base_args = ["DESIGNER", "/F", connection]
    else:
        connection = f"{args.server}/{args.ref}"
        base_args = ["DESIGNER", "/S", connection]
    if args.user:
        base_args.extend(["/N", args.user])
    if args.password:
        base_args.extend(["/P", args.password])

    print(f"1C: {v8_exe}")
    print(f"Infobase: {connection}")
    print(f"Extension: {extension}")
    print(f"Sources: {source_dir}")
    print(f"Output: {out_file}")

    if not args.skip_load:
        print("Loading XML sources...")
        load_args = [
            *base_args,
            "/LoadConfigFromFiles",
            str(source_dir),
            "-Format",
            "Hierarchical",
            "-updateConfigDumpInfo",
            "-Extension",
            extension,
            "/UpdateDBCfg",
        ]
        run_designer(v8_exe, load_args, runtime_dir / "load.log")

    print("Dumping CFE...")
    if out_file.exists():
        out_file.unlink()

    dump_args = [
        *base_args,
        "/DumpCfg",
        str(out_file),
        "-Extension",
        extension,
    ]
    run_designer(v8_exe, dump_args, runtime_dir / "dump.log")

    if not out_file.exists():
        raise FileNotFoundError(f"CFE was not created: {out_file}")

    print(f"Built: {out_file}")
    print(f"Size: {out_file.stat().st_size} bytes")
    print(f"SHA256: {sha256(out_file)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
