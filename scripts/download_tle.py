"""Baixa e confere o tle oficial para Windows x64."""

import hashlib
import io
import os
import platform
import sys
import tarfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "src" / "cofre_temporal" / "vendor"
URL = "https://github.com/drand/tlock/releases/download/v1.2.0/tlock_1.2.0_windows_amd64.tar.gz"
ARCHIVE_SHA256 = "c8117179edbd4fcebae56983e385a94b5f17fc90efeddd62b28304f96da91e84"
BINARY_SHA256 = "2fe440827f0e2290970ab852c92751a49242c90a8b57b19bece5281c85b56451"


def download_tle():
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Este pacote usa o tle para Windows x64.")

    target = VENDOR / "tle.exe"
    if (
        target.exists()
        and hashlib.sha256(target.read_bytes()).hexdigest() == BINARY_SHA256
    ):
        print("tle pronto (SHA-256 conferido).")
        return target

    request = Request(URL, headers={"User-Agent": "CofreTemporal/1.0"})
    with urlopen(request, timeout=60) as response:
        data = response.read(32 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("O download não corresponde ao SHA-256 esperado.")

    # Lê somente o binário esperado; não extrai caminhos fornecidos pelo tar.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        member = archive.getmember("tle.exe")
        if not member.isfile():
            raise RuntimeError("O pacote não contém um binário regular.")
        with archive.extractfile(member) as source:
            binary = source.read()
    if hashlib.sha256(binary).hexdigest() != BINARY_SHA256:
        raise RuntimeError("O binário não corresponde ao SHA-256 esperado.")

    VENDOR.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".download")
    try:
        temporary.write_bytes(binary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    print("tle instalado e verificado.")
    return target


if __name__ == "__main__":
    download_tle()
