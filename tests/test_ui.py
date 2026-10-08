"""Workflow tests: real Tk callbacks and local encryption, no personal files."""

import time
from tkinter import ttk

import pytest

from cofre_temporal import ui
from cofre_temporal.vault import create_password_archive


@pytest.fixture(scope="module")
def gui_app():
    # Match the desktop lifecycle: one Tcl interpreter, multiple operations.
    # Repeated root setup is unreliable in this Windows pytest process.
    app = ui.CofreApp()
    app.withdraw()
    yield app
    deadline = time.monotonic() + 5
    while app.busy and time.monotonic() < deadline:
        app.cancel.set()
        app.update()
        time.sleep(0.01)
    for timer in app.tk.call("after", "info"):
        app.after_cancel(timer)
    app.destroy()


@pytest.fixture
def window(gui_app, monkeypatch):
    app = gui_app
    dialogs = []
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **kw: dialogs.append(a))
    monkeypatch.setattr(ui.messagebox, "showerror", lambda *a, **kw: dialogs.append(a))
    app.items.selection_set(app.items.get_children())
    app.remove()
    for variable in (
        app.password,
        app.confirm,
        app.output,
        app.archive,
        app.restore_parent,
        app.restore_password,
    ):
        variable.set("")
    app.mode.set("tempo")
    app._switch_mode()
    app.last_result = None
    app.restore_secret.pack_forget()
    app._notify("Pronto.")
    yield app, dialogs


def wait_for_work(app):
    deadline = time.monotonic() + 5
    while app.busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)
    assert not app.busy, "A interface não encerrou a operação"


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def in_layout(widget, root):
    while widget is not root:
        if not widget.winfo_manager():
            return False
        widget = widget.master
    return True


def test_invalid_password_reported_before_save_dialog(window, tmp_path, monkeypatch):
    app, dialogs = window
    source = tmp_path / "teste.txt"
    source.write_text("conteúdo", encoding="utf-8")
    app._add([str(source)])
    app.mode.set("senha")
    app._switch_mode()
    app.password.set("curta")
    app.confirm.set("curta")
    saves = []
    monkeypatch.setattr(
        ui.filedialog, "asksaveasfilename", lambda **kw: saves.append(kw) or ""
    )
    app.protect()
    assert not saves, "O usuário não deve escolher destino antes de corrigir a senha"
    assert "senha" in app.status.get().lower()
    assert not dialogs


def test_success_is_inline_and_produced_archive_can_be_restored(window, tmp_path):
    app, dialogs = window
    source = tmp_path / "teste.txt"
    source.write_text("Arquivo do teste", encoding="utf-8")
    app._add([str(source)])
    app.mode.set("senha")
    app._switch_mode()
    app.password.set("uma senha bem longa")
    app.confirm.set("uma senha bem longa")
    output = tmp_path / "cofre.zip"
    app.output.set(str(output))
    app.protect()
    wait_for_work(app)
    assert output.exists()
    assert app.last_result == output
    assert not app.password.get()
    assert not dialogs, "Concluir a operação não deve interromper com um popup"
    app.archive.set(str(output))
    app.restore_parent.set(str(tmp_path))
    app.restore_password.set("uma senha bem longa")
    app.restore()
    wait_for_work(app)
    assert (tmp_path / "cofre_restaurado" / "teste.txt").read_text(
        encoding="utf-8"
    ) == "Arquivo do teste"
    assert not dialogs


def test_timed_selection_hides_irrelevant_password_field(window, tmp_path, monkeypatch):
    app, _ = window
    source = tmp_path / "futuro.tlock"
    source.write_bytes(
        b"age-encryption.org/v1\n-> tlock 40000000 "
        b"52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971\n"
    )
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **kw: str(source))
    app.choose_archive()
    field = next(
        w
        for w in descendants(app.tabs)
        if isinstance(w, ttk.Entry)
        and str(w.cget("textvariable")) == str(app.restore_password)
    )
    assert not in_layout(field, app.tabs)
    assert "2027" in app.release_info.get()


def test_wrong_password_is_inline_and_keeps_original(window, tmp_path):
    app, dialogs = window
    source = tmp_path / "teste.txt"
    source.write_bytes(b"preservar")
    archive = tmp_path / "teste.zip"
    create_password_archive([source], archive, "uma senha bem longa")
    app.archive.set(str(archive))
    app.restore_parent.set(str(tmp_path))
    app.restore_password.set("senha incorreta")
    app.restore()
    wait_for_work(app)
    assert "senha" in app.status.get().lower()
    assert source.read_bytes() == b"preservar"
    assert not (tmp_path / "teste_restaurado").exists()
    assert not dialogs


def test_rejected_temporal_header_cannot_start_restore(window, tmp_path, monkeypatch):
    app, dialogs = window
    source = tmp_path / "invalido.tlock"
    source.write_bytes(b"age-encryption.org/v1\n-> tlock broken\n")
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **kw: str(source))
    app.choose_archive()
    assert not app.archive.get()
    app.restore()
    assert not app.busy
    assert not dialogs
