import os
import stat
import threading
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
import pyzipper

from cofre_temporal import vault

PASSWORD = "minha senha longa 123!"


@pytest.fixture
def files(tmp_path):
    root = tmp_path / "documentos"
    root.mkdir()
    (root / "vazia").mkdir()
    (root / "ação.txt").write_text("Olá, mundo!\n" * 1000, encoding="utf-8")
    (root / "binário.dat").write_bytes(os.urandom(2 * vault.CHUNK + 111))
    (root / "zero").touch()
    return root


def test_password_roundtrip_and_originals(tmp_path, files):
    output = tmp_path / "cofre.zip"
    original = (files / "binário.dat").read_bytes()
    vault.create_password_archive([files], output, PASSWORD)
    with pyzipper.AESZipFile(str(output)) as archive:
        assert all(item.flag_bits & 1 for item in archive.infolist())
        assert all(
            item.wz_aes_strength == 3 and item.wz_aes_version == 2
            for item in archive.infolist()
        )
    destination = tmp_path / "restaurados"
    vault.restore_archive(output, destination, PASSWORD)
    assert (destination / "documentos" / "binário.dat").read_bytes() == original
    assert (destination / "documentos" / "ação.txt").read_bytes() == (
        files / "ação.txt"
    ).read_bytes()
    assert (destination / "documentos" / "vazia").is_dir()
    assert (destination / "documentos" / "zero").stat().st_size == 0
    assert (files / "binário.dat").read_bytes() == original


def test_wrong_password_publishes_nothing(tmp_path, files):
    output = tmp_path / "cofre.zip"
    vault.create_password_archive([files], output, PASSWORD)
    with pytest.raises(vault.VaultError, match="Senha incorreta"):
        vault.restore_archive(output, tmp_path / "falha", "errada")
    assert not (tmp_path / "falha").exists()
    assert not list(tmp_path.glob(".cofre-*"))


def test_tampered_ciphertext_publishes_nothing(tmp_path):
    source = tmp_path / "texto.txt"
    source.write_bytes(os.urandom(4000))
    output = tmp_path / "cofre.zip"
    vault.create_password_archive([source], output, PASSWORD)
    with zipfile.ZipFile(output) as archive:
        item = archive.infolist()[0]
        offset = item.header_offset
    data = bytearray(output.read_bytes())
    name_len = int.from_bytes(data[offset + 26 : offset + 28], "little")
    extra_len = int.from_bytes(data[offset + 28 : offset + 30], "little")
    data[offset + 30 + name_len + extra_len + 50] ^= 1
    output.write_bytes(data)
    with pytest.raises(vault.VaultError):
        vault.restore_archive(output, tmp_path / "falha", PASSWORD)
    assert not (tmp_path / "falha").exists()
    assert source.exists()


def test_no_overwrite(tmp_path, files):
    output = tmp_path / "existente.zip"
    output.write_bytes(b"preservar")
    with pytest.raises(vault.VaultError):
        vault.create_password_archive([files], output, PASSWORD)
    assert output.read_bytes() == b"preservar"


def test_reject_output_inside_input_and_short_password(tmp_path, files):
    with pytest.raises(vault.VaultError):
        vault.create_password_archive([files], files / "recursivo.zip", PASSWORD)
    with pytest.raises(vault.VaultError):
        vault.create_password_archive([files], tmp_path / "curta.zip", "123")
    assert not (files / "recursivo.zip").exists()


def test_cancel_midway_cleans_partial(tmp_path, files):
    cancel = threading.Event()

    def progress(*args):
        cancel.set()

    with pytest.raises(vault.Cancelled):
        vault.create_password_archive(
            [files], tmp_path / "cancelado.zip", PASSWORD, progress, cancel
        )
    assert not (tmp_path / "cancelado.zip").exists()
    assert not list(tmp_path.glob(".cofre-*"))
    assert files.exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "/escape.txt",
        "C:/escape.txt",
        "folder/../../escape.txt",
        "folder\\escape.txt",
        "NUL.txt",
        "x./file.txt",
        "file:stream",
        "a//b",
    ],
)
def test_reject_unsafe_archives(tmp_path, name):
    output = tmp_path / "malicioso.zip"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, b"x")
    if "\\" in name:
        # The Windows ZIP writer normalizes backslashes. Put the hostile name
        # back in both headers to exercise the reader against a real archive.
        output.write_bytes(
            output.read_bytes().replace(name.replace("\\", "/").encode(), name.encode())
        )
    with pytest.raises(vault.VaultError):
        vault.restore_archive(output, tmp_path / "extraido")
    assert not (tmp_path / "extraido").exists()
    assert not (tmp_path / "escape.txt").exists()


def test_reject_zip_symlink(tmp_path):
    output = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(info, "../escape")
    with pytest.raises(vault.VaultError):
        vault.restore_archive(output, tmp_path / "extraido")


def test_reject_case_collisions(tmp_path):
    output = tmp_path / "colisao.zip"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("Nome.txt", b"first")
        archive.writestr("nome.txt", b"second")
    with pytest.raises(vault.VaultError):
        vault.restore_archive(output, tmp_path / "extraido")


def test_nested_selections_are_deduplicated(tmp_path, files):
    entries = vault.collect_entries(
        [files / "ação.txt", files, files], tmp_path / "cofre.zip"
    )
    assert len(entries) == 5


def test_round_never_releases_early():
    for remainder in (0, 0.01, 1, 2, 2.99):
        requested = datetime.fromtimestamp(
            vault.GENESIS + 300 + remainder, timezone.utc
        )
        actual = vault.date_for_round(vault.round_for_date(requested))
        assert actual >= requested
        assert (actual - requested).total_seconds() < 3


def test_temporal_rejects_past_and_naive_dates(tmp_path, files):
    for date in (datetime.now(), datetime.now(timezone.utc) - timedelta(days=1)):
        with pytest.raises(vault.VaultError):
            vault.create_timed_archive([files], tmp_path / "cofre.tlock", date)


def test_restore_existing_directory_is_untouched(tmp_path, files):
    output = tmp_path / "cofre.zip"
    vault.create_password_archive([files], output, PASSWORD)
    with pytest.raises(vault.VaultError):
        vault.restore_archive(output, files, PASSWORD)
    assert not (files / "documentos").exists()


def test_file_changed_during_read_fails(tmp_path, files):
    entries = vault.collect_entries([files], tmp_path / "cofre.zip")
    (files / "ação.txt").write_text("mudou", encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "temporario.zip", "w") as archive:
        with pytest.raises(vault.VaultError, match="mudou"):
            vault._write_zip(archive, entries)
