"""Explicit online integration test; uses only generated disposable files.

Execute: python scripts/check_timelock.py
"""

import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cofre_temporal import vault


def main():
    with tempfile.TemporaryDirectory(prefix="cofre-teste-") as directory:
        work = Path(directory)
        source = work / "teste.txt"
        content = "Teste de liberação temporal — nenhum arquivo pessoal.\n" * 100
        source.write_text(content, encoding="utf-8")
        binary = work / "binário.dat"
        binary_content = os.urandom(2 * vault.CHUNK + 137)
        binary.write_bytes(binary_content)
        archive = work / "teste.zip.tlock"
        release = datetime.now(timezone.utc) + timedelta(seconds=18)
        vault.create_timed_archive([source, binary], archive, release)
        actual = vault.read_release_date(archive)
        assert actual >= release
        print("OK: cofre criado com liberação em", actual.isoformat(), flush=True)

        # Bypass the local date check to prove drand, not the GUI clock, blocks it.
        future_clock = actual.timestamp() + 3600
        with patch("cofre_temporal.vault.time.time", return_value=future_clock):
            try:
                vault.restore_archive(archive, work / "antes")
            except vault.VaultError:
                pass
            else:
                raise AssertionError("Abertura antecipada não deveria funcionar")
        assert not (work / "antes").exists()
        print(
            "OK: abertura antecipada bloqueada mesmo com relógio local adiantado",
            flush=True,
        )

        tampered = work / "alterado.tlock"
        number = vault.round_for_date(actual)
        tampered.write_bytes(
            archive.read_bytes().replace(
                f"-> tlock {number} ".encode(), f"-> tlock {number - 100} ".encode(), 1
            )
        )
        try:
            vault.restore_archive(tampered, work / "fraude")
        except vault.VaultError:
            pass
        else:
            raise AssertionError("Cabeçalho adulterado deveria ser recusado")
        assert not (work / "fraude").exists()
        print("OK: adulteração da data não permite abrir o arquivo", flush=True)

        remaining = max(0, actual.timestamp() - time.time() + 3)
        print(f"Aguardando {remaining:.1f}s pela publicação da chave…", flush=True)
        time.sleep(remaining)
        restored = vault.restore_archive(archive, work / "depois")
        assert (restored / source.name).read_text(encoding="utf-8") == content
        assert (restored / binary.name).read_bytes() == binary_content
        assert source.read_text(encoding="utf-8") == content
        assert not list(work.glob(".cofre-*"))
        print(
            "OK: arquivo restaurado após a liberação; original preservado", flush=True
        )

        damaged = work / "danificado.tlock"
        damaged.write_bytes(archive.read_bytes()[:-20])
        try:
            vault.restore_archive(damaged, work / "incompleto")
        except vault.VaultError:
            pass
        else:
            raise AssertionError("O conteúdo truncado deveria ser recusado")
        assert not (work / "incompleto").exists()
        assert not list(work.glob(".cofre-*"))
        print(
            "OK: conteúdo truncado recusado sem publicar arquivos parciais", flush=True
        )

        # Interoperability with upstream's CLI: our output is a standard tlock/age file.
        raw = subprocess.run(
            [str(vault.tle_path()), "-d", str(archive)], capture_output=True, timeout=30
        )
        assert raw.returncode == 0, raw.stderr.decode()
        assert raw.stdout.startswith(b"PK")
        print("OK: interoperabilidade com o tle oficial", flush=True)


if __name__ == "__main__":
    main()
