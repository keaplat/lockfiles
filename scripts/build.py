"""Gera o executável e um ZIP portátil com documentação e licenças."""

import hashlib
import shutil
import subprocess
import sys
import zipfile
from importlib import metadata
from pathlib import Path

from download_tle import ROOT, VENDOR, download_tle


def copy_licenses(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("pyzipper", "pycryptodomex", "pyinstaller"):
        distribution = metadata.distribution(name)
        folder = destination / name
        folder.mkdir(exist_ok=True)
        for member in distribution.files or []:
            if any(
                word in str(member).lower()
                for word in ("license", "copying", "copyright")
            ):
                source = Path(distribution.locate_file(member))
                if source.is_file():
                    shutil.copy2(source, folder / source.name)
    shutil.copy2(
        Path(sys.base_prefix) / "LICENSE.txt", destination / "Python-LICENSE.txt"
    )
    for subdir in ("tcl8.6", "tk8.6"):
        license_file = Path(sys.base_prefix) / "tcl" / subdir / "license.terms"
        if license_file.is_file():
            shutil.copy2(license_file, destination / f"{subdir}-license.terms")
    for name in ("LICENSE-MIT", "LICENSE-APACHE", "Tcl-license.terms"):
        shutil.copy2(VENDOR / name, destination / name)


def main():
    binary = download_tle()
    dist = ROOT / "dist"
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "CofreTemporal",
            "--paths",
            str(ROOT / "src"),
            "--distpath",
            str(dist),
            "--workpath",
            str(build / "pyinstaller"),
            "--specpath",
            str(build),
            "--add-binary",
            f"{binary};vendor",
            "--add-data",
            f"{VENDOR / 'LICENSE-APACHE'};vendor",
            "--add-data",
            f"{VENDOR / 'LICENSE-MIT'};vendor",
            str(ROOT / "scripts" / "desktop_entry.py"),
        ],
        cwd=ROOT,
        check=True,
    )

    copy_licenses(dist / "licenses")
    for name in ("README.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, dist / name)
    shutil.copytree(ROOT / "docs", dist / "docs", dirs_exist_ok=True)
    executable = dist / "CofreTemporal.exe"
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    (dist / "SHA256.txt").write_text(f"{digest}  CofreTemporal.exe\n", encoding="utf-8")
    files = [
        executable,
        dist / "SHA256.txt",
        dist / "README.md",
        dist / "THIRD_PARTY_NOTICES.md",
    ]
    files += sorted((dist / "licenses").rglob("*")) + sorted((dist / "docs").rglob("*"))
    output = dist / "CofreTemporal-Windows.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_file():
                archive.write(path, Path("CofreTemporal") / path.relative_to(dist))
    print(f"Executável: {executable}")
    print(f"Pacote: {output}")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
