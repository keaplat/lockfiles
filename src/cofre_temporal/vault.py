"""Criação e restauração de cofres com senha ou data de abertura."""

from __future__ import annotations

import contextlib
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pyzipper
from pyzipper.zipfile_aes import AESZipInfo

CHAIN = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
GENESIS = 1692803367
PERIOD = 3
RELAYS = ("https://api.drand.sh/", "https://api2.drand.sh/")
CHUNK = 1024 * 1024
MAX_ENTRIES = 200_000
Progress = Callable[[float | None, str], None]


class VaultError(Exception):
    """An error suitable for display to the user."""


class Cancelled(VaultError):
    pass


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled("Operação cancelada. Os originais foram preservados.")


def _report(progress: Progress | None, value: float | None, message: str) -> None:
    if progress:
        progress(value, message)


def round_for_date(value: datetime) -> int:
    if value.tzinfo is None:
        raise VaultError("A data precisa incluir o fuso horário.")
    # Ceiling is essential: floor would unlock up to three seconds early.
    return max(1, math.ceil((value.timestamp() - GENESIS) / PERIOD) + 1)


def date_for_round(round_number: int) -> datetime:
    return datetime.fromtimestamp(GENESIS + (round_number - 1) * PERIOD, timezone.utc)


def read_release_date(archive: Path) -> datetime | None:
    """Display-only metadata; tle authenticates the header during decryption."""
    with Path(archive).open("rb") as source:
        header = source.read(2048)
    if not header.startswith(b"age-encryption.org/v1\n"):
        return None
    match = re.match(
        rb"age-encryption.org/v1\n-> tlock ([0-9]{1,12}) ([0-9a-f]{64})\n", header
    )
    if not match or match[2].decode() != CHAIN:
        raise VaultError("Este cofre não usa o formato temporal quicknet compatível.")
    try:
        number = int(match[1])
        if number < 1:
            raise ValueError()
        return date_for_round(number)
    except (ValueError, OverflowError, OSError) as exc:
        raise VaultError("A data de liberação do arquivo é inválida.") from exc


def _linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _normal_path(path: Path) -> Path:
    # Reject symlinks in the supplied path, including its ancestors.
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if _linked(item):
            raise VaultError(
                f"Selecione um caminho direto, sem links ou junções: {path}"
            )
    return path


@dataclass(frozen=True)
class Entry:
    path: Path
    name: str
    size: int
    modified: int
    directory: bool


def collect_entries(sources: list[Path], output: Path, cancel=None) -> list[Entry]:
    if not sources:
        raise VaultError("Adicione pelo menos um arquivo ou uma pasta.")
    roots = list(dict.fromkeys(_normal_path(p) for p in sources))
    roots = [p for p in roots if not any(p != q and p.is_relative_to(q) for q in roots)]
    root_names: set[str] = set()
    result: list[Entry] = []
    for root in roots:
        _check_cancel(cancel)
        if not root.name or not root.exists():
            raise VaultError(f"O item não está disponível: {root}")
        if output == root or (root.is_dir() and output.is_relative_to(root)):
            raise VaultError("Salve o cofre fora das pastas que serão protegidas.")
        if root.name.casefold() in root_names:
            raise VaultError(
                "Há itens com o mesmo nome. Selecione a pasta que os contém ou renomeie-os."
            )
        root_names.add(root.name.casefold())
        pending = [root]
        while pending:
            _check_cancel(cancel)
            path = pending.pop()
            if _linked(path):
                raise VaultError(f"A pasta contém um link ou junção: {path}")
            info = path.stat()
            directory = stat.S_ISDIR(info.st_mode)
            if not directory and not stat.S_ISREG(info.st_mode):
                raise VaultError(f"Tipo de arquivo não suportado: {path}")
            name = path.relative_to(root.parent).as_posix() + ("/" if directory else "")
            _safe_parts(name)
            result.append(
                Entry(
                    path,
                    name,
                    0 if directory else info.st_size,
                    info.st_mtime_ns,
                    directory,
                )
            )
            if len(result) > MAX_ENTRIES:
                raise VaultError(f"O limite é de {MAX_ENTRIES:,} itens por cofre.")
            if directory:
                pending.extend(sorted(path.iterdir(), reverse=True))
    return result


def _write_zip(archive, entries: list[Entry], progress=None, cancel=None) -> None:
    total = max(1, sum(item.size for item in entries))
    done = 0
    last_report = 0.0
    for item in entries:
        _check_cancel(cancel)
        if _linked(item.path):
            raise VaultError("Um item foi substituído por um link durante a leitura.")
        before = item.path.stat()
        if (before.st_mtime_ns, 0 if item.directory else before.st_size) != (
            item.modified,
            item.size,
        ):
            raise VaultError(
                f"O item mudou durante a operação. Tente novamente: {item.path.name}"
            )
        info_class = (
            AESZipInfo if isinstance(archive, pyzipper.AESZipFile) else zipfile.ZipInfo
        )
        info = info_class.from_file(str(item.path), item.name, strict_timestamps=False)
        info.compress_type = zipfile.ZIP_DEFLATED
        if item.directory:
            archive.writestr(info, b"")
            continue
        with (
            item.path.open("rb") as source,
            archive.open(info, "w", force_zip64=True) as target,
        ):
            while block := source.read(CHUNK):
                _check_cancel(cancel)
                target.write(block)
                done += len(block)
                if time.monotonic() - last_report > 0.1:
                    _report(
                        progress, done / total * 0.9, f"Protegendo: {item.path.name}"
                    )
                    last_report = time.monotonic()
        after = item.path.stat()
        if (before.st_mtime_ns, before.st_size, before.st_ino) != (
            after.st_mtime_ns,
            after.st_size,
            after.st_ino,
        ):
            raise VaultError(
                f"O arquivo mudou durante a leitura: {item.path.name}. Tente novamente."
            )


@contextlib.contextmanager
def _staged_file(output: Path):
    if output.exists():
        raise VaultError("Já existe um arquivo nesse destino. Escolha outro nome.")
    if not output.parent.is_dir():
        raise VaultError("A pasta de destino não existe.")
    descriptor, name = tempfile.mkstemp(
        prefix=".cofre-", suffix=".parcial", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        # Windows rename is atomic and refuses an existing destination.
        # POSIX link provides the same no-overwrite guarantee for a file.
        if os.name == "nt":
            os.rename(temporary, output)
        else:
            os.link(temporary, output)
            temporary.unlink()
    except FileExistsError as exc:
        raise VaultError("O destino já existe. Nada foi substituído.") from exc
    finally:
        temporary.unlink(missing_ok=True)


def create_password_archive(
    sources, output, password, progress=None, cancel=None
) -> Path:
    if len(password) < 12:
        raise VaultError("Use uma senha de pelo menos 12 caracteres.")
    output = _normal_path(Path(output))
    entries = collect_entries(sources, output, cancel)
    with _staged_file(output) as temporary:
        with pyzipper.AESZipFile(
            str(temporary),
            "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
            allowZip64=True,
        ) as archive:
            archive.setpassword(password.encode("utf-8"))
            archive.setencryption(pyzipper.WZ_AES, nbits=256)
            _write_zip(archive, entries, progress, cancel)
        _check_cancel(cancel)
    _report(progress, 1, "ZIP protegido criado. Os originais continuam no lugar.")
    return output


def tle_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    binary = base / "vendor" / ("tle.exe" if os.name == "nt" else "tle")
    if not binary.is_file():
        raise VaultError(
            "O componente temporal tle não foi encontrado. Reinstale o programa."
        )
    return binary


class _TleProcess:
    """Keep the UI cancellable even if tle is waiting for its network or pipes."""

    def __init__(self, args, output: Path, cancel):
        self.cancel = cancel
        self.output = output
        self.last_activity = time.monotonic()
        self.timed_out = False
        self.finished = threading.Event()
        self.error_file = tempfile.TemporaryFile()
        # Ignore TLE_* overrides: users' environment must not change our format.
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("TLE_")}
        try:
            self.process = subprocess.Popen(
                [str(tle_path()), *args, "-o", str(output)],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self.error_file,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except BaseException:
            self.error_file.close()
            raise
        self.monitor = threading.Thread(target=self._watch, daemon=True)
        self.monitor.start()

    def _watch(self):
        last_size = -1
        while not self.finished.wait(0.2):
            if self.process.poll() is not None:
                return
            try:
                size = self.output.stat().st_size
            except OSError:
                size = 0
            if size != last_size:
                last_size = size
                self.last_activity = time.monotonic()
            if self.cancel is not None and self.cancel.is_set():
                self.process.kill()
                return
            if time.monotonic() - self.last_activity > 40:
                self.timed_out = True
                self.process.kill()
                return

    def write(self, data):
        _check_cancel(self.cancel)
        count = self.process.stdin.write(data)
        self.last_activity = time.monotonic()
        return count

    def flush(self):
        self.process.stdin.flush()

    def finish(self):
        with contextlib.suppress(BrokenPipeError, OSError):
            self.process.stdin.close()
        result = self.process.wait()
        _check_cancel(self.cancel)
        self.error_file.seek(0)
        error = self.error_file.read(8192).decode("utf-8", errors="replace")
        if self.timed_out:
            raise VaultError(
                "A rede demorou para responder. Verifique a internet e tente novamente."
            )
        if result:
            if "too early" in error.lower() or "expected round" in error.lower():
                raise VaultError("Ainda não chegou a data de liberação deste cofre.")
            raise VaultError(
                "Não foi possível processar o cofre temporal. A rede pode estar indisponível, "
                "a data ainda não chegou ou o arquivo está danificado.\n\n"
                + error[-700:]
            )

    def close(self):
        self.finished.set()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        self.monitor.join(timeout=1)
        with contextlib.suppress(OSError):
            self.process.stdin.close()
        self.error_file.close()


def create_timed_archive(
    sources, output, release_date, progress=None, cancel=None
) -> Path:
    if release_date.tzinfo is None or release_date.timestamp() <= time.time() + 5:
        raise VaultError(
            "Escolha uma data futura, com pelo menos alguns segundos de antecedência."
        )
    output = _normal_path(Path(output))
    entries = collect_entries(sources, output, cancel)
    round_number = round_for_date(release_date)
    with _staged_file(output) as temporary:
        for index, relay in enumerate(RELAYS):
            _check_cancel(cancel)
            _report(progress, None, "Consultando a rede de liberação temporal…")
            runner = _TleProcess(
                ["-e", "-r", str(round_number), "-n", relay, "-c", CHAIN],
                temporary,
                cancel,
            )
            try:
                try:
                    with zipfile.ZipFile(
                        runner, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
                    ) as archive:
                        _write_zip(archive, entries, progress, cancel)
                except (BrokenPipeError, OSError):
                    runner.finish()
                    raise
                runner.finish()
                break
            except Cancelled:
                raise
            except VaultError:
                if index == len(RELAYS) - 1:
                    raise
            finally:
                runner.close()
        _check_cancel(cancel)
        if read_release_date(temporary) != date_for_round(round_number):
            raise VaultError(
                "A data gravada no cofre não corresponde à data escolhida."
            )
        if date_for_round(round_number).timestamp() <= time.time():
            raise VaultError(
                "A data de liberação passou durante a criação. Escolha uma data mais distante."
            )
    _report(progress, 1, "Cofre temporal criado. Os originais continuam no lugar.")
    return output


def _decrypt_timed(source: Path, output: Path, progress, cancel):
    release = read_release_date(source)
    if release is None:
        raise VaultError("Este arquivo não é um cofre temporal.")
    # This date check is only UX. Cryptographic enforcement is performed by tle
    # against drand signatures, regardless of the computer's clock.
    if release.timestamp() > time.time():
        raise VaultError(
            "Liberação prevista para "
            + release.astimezone().strftime("%d/%m/%Y às %H:%M:%S %Z")
            + "."
        )
    for index, relay in enumerate(RELAYS):
        _report(progress, None, "Consultando a chave pública de liberação…")
        runner = _TleProcess(["-d", "-n", relay, "-c", CHAIN], output, cancel)
        try:
            with source.open("rb") as encrypted:
                while block := encrypted.read(CHUNK):
                    runner.write(block)
            runner.finish()
            return
        except Cancelled:
            raise
        except (VaultError, BrokenPipeError, OSError):
            _check_cancel(cancel)
            if index == len(RELAYS) - 1:
                raise VaultError(
                    "Não foi possível liberar o cofre. Verifique a internet, a data "
                    "de liberação e se o arquivo está íntegro."
                )
        finally:
            runner.close()


_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)


def _safe_parts(name: str) -> tuple[str, ...]:
    if not name or name.startswith(("/", "\\")) or "\\" in name:
        raise VaultError("O ZIP contém um caminho inseguro.")
    parts = tuple(name.rstrip("/").split("/"))
    for part in parts:
        if (
            not part
            or part in (".", "..")
            or part.endswith((" ", "."))
            or _RESERVED.match(part)
            or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
        ):
            raise VaultError("O ZIP contém nomes incompatíveis ou um caminho inseguro.")
    return parts


def _extract_checked(source: Path, destination: Path, password, progress, cancel):
    with pyzipper.AESZipFile(str(source)) as archive:
        if password:
            archive.setpassword(password.encode("utf-8"))
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES:
            raise VaultError("O ZIP tem itens demais para ser extraído com segurança.")
        total = sum(i.file_size for i in entries)
        if total + 16 * CHUNK > shutil.disk_usage(destination).free:
            raise VaultError(
                "Não há espaço suficiente no destino para restaurar este cofre."
            )
        names: set[str] = set()
        files: set[str] = set()
        checked = []
        for item in entries:
            _check_cancel(cancel)
            _safe_parts(item.orig_filename)
            parts = _safe_parts(item.filename)
            key = "/".join(parts).casefold()
            kind = stat.S_IFMT(item.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise VaultError(
                    "O ZIP contém links ou tipos de arquivo não permitidos."
                )
            if key in names:
                raise VaultError("O ZIP contém nomes duplicados.")
            names.add(key)
            if not item.is_dir():
                files.add(key)
            checked.append((item, parts))
        for _, parts in checked:
            if any(
                "/".join(parts[:i]).casefold() in files for i in range(1, len(parts))
            ):
                raise VaultError("O ZIP contém caminhos em conflito.")
        done = 0
        last_report = 0.0
        for item, parts in checked:
            _check_cancel(cancel)
            target = destination.joinpath(*parts)
            if item.is_dir():
                # Read even empty encrypted members, to authenticate their data.
                with archive.open(item) as member:
                    if member.read(1):
                        raise VaultError("Pasta inválida no ZIP.")
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(item) as member, target.open("xb") as output:
                while block := member.read(CHUNK):
                    _check_cancel(cancel)
                    written += len(block)
                    if written > item.file_size:
                        raise VaultError("O ZIP informa um tamanho incorreto.")
                    output.write(block)
                    done += len(block)
                    if time.monotonic() - last_report > 0.1:
                        _report(
                            progress,
                            done / max(1, total) * 0.95,
                            f"Restaurando: {target.name}",
                        )
                        last_report = time.monotonic()
            if written != item.file_size:
                raise VaultError("O arquivo está incompleto.")
            with contextlib.suppress(ValueError, OverflowError, OSError):
                timestamp = datetime(*item.date_time).timestamp()
                os.utime(target, (timestamp, timestamp))


def restore_archive(
    source, destination, password="", progress=None, cancel=None
) -> Path:
    source = _normal_path(Path(source))
    destination = _normal_path(Path(destination))
    if destination.exists():
        raise VaultError("A pasta de restauração já existe. Escolha um novo nome.")
    if not destination.parent.is_dir():
        raise VaultError("A pasta de destino não existe.")
    _check_cancel(cancel)
    # All intermediate plaintext stays in a private staging directory, removed
    # on failure/cancellation. This cleanup is not a claim of secure erasure.
    with tempfile.TemporaryDirectory(
        prefix=".cofre-restaurar-", dir=destination.parent
    ) as directory:
        work = Path(directory)
        restored = work / "arquivos"
        restored.mkdir()
        try:
            release = read_release_date(source)
            payload = source
            if release:
                if source.stat().st_size + 32 * CHUNK > shutil.disk_usage(work).free:
                    raise VaultError(
                        "Não há espaço suficiente para abrir o cofre temporal."
                    )
                payload = work / "conteudo.zip"
                _decrypt_timed(source, payload, progress, cancel)
            _extract_checked(
                payload, restored, password if not release else "", progress, cancel
            )
            _check_cancel(cancel)
            if destination.exists():
                raise VaultError("A pasta de destino já existe. Nada foi substituído.")
            os.rename(restored, destination)
        except VaultError:
            raise
        except (
            zipfile.BadZipFile,
            pyzipper.BadZipFile,
            RuntimeError,
            EOFError,
            NotImplementedError,
            zlib.error,
        ) as exc:
            raise VaultError(
                "Senha incorreta, arquivo danificado ou formato ZIP incompatível."
            ) from exc
    _report(progress, 1, "Arquivos restaurados. O cofre original foi preservado.")
    return destination
