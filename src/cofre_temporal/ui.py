"""Interface do Cofre Temporal em Tkinter."""

import os
import queue
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .vault import (
    Cancelled,
    VaultError,
    create_password_archive,
    create_timed_archive,
    date_for_round,
    read_release_date,
    restore_archive,
    round_for_date,
)

BG, INK, MUTED, BLUE = "#f7f8fa", "#182335", "#647084", "#345de3"


class CofreApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cofre Temporal")
        self.geometry("740x660")
        self.minsize(700, 640)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.last_result = None
        self.error_detail = ""
        self.sources = []
        self.mode = tk.StringVar(self, "tempo")
        self.password = tk.StringVar(self)
        self.confirm = tk.StringVar(self)
        self.show_password = tk.BooleanVar(self)
        self.release = tk.StringVar(
            self, (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y %H:%M")
        )
        self.output = tk.StringVar(self)
        self.output_label = tk.StringVar(self, "Escolher ao criar")
        self.archive = tk.StringVar(self)
        self.archive_label = tk.StringVar(self, "Nenhum cofre selecionado")
        self.restore_parent = tk.StringVar(self)
        self.restore_password = tk.StringVar(self)
        self.status = tk.StringVar(self, "Pronto para começar.")
        self.count = tk.StringVar(self, "Nenhum item")
        self.release_info = tk.StringVar(self, "ZIP com senha ou arquivo .tlock")
        self._styles()
        self._build()
        self.output.trace_add("write", self._output_changed)
        self.after(100, self._poll)

    def _styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure(
            "TButton",
            padding=(12, 6),
            background="white",
            foreground=INK,
            bordercolor="#dde2eb",
        )
        style.map("TButton", background=[("active", "#eef1fa")])
        style.configure(
            "Primary.TButton",
            padding=(16, 11),
            background=BLUE,
            foreground="white",
            font=("Segoe UI", 11, "bold"),
            borderwidth=0,
        )
        style.map(
            "Primary.TButton",
            background=[("disabled", "#a5afc5"), ("active", "#234bc5")],
            foreground=[("disabled", "#ffffff")],
        )
        style.configure(
            "Link.TButton",
            background=BG,
            borderwidth=0,
            foreground=BLUE,
            padding=(8, 4),
        )
        style.configure("TRadiobutton", background=BG, foreground=INK, padding=(0, 4))
        style.configure("TCheckbutton", background=BG, foreground=INK)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab", padding=(26, 8), background=BG, foreground=MUTED
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "white")],
            foreground=[("selected", BLUE)],
        )
        style.configure(
            "Treeview",
            rowheight=27,
            background="white",
            fieldbackground="white",
            bordercolor="#dde2eb",
        )
        style.configure(
            "Treeview.Heading",
            background="#eef1f6",
            foreground=MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "TEntry", padding=7, fieldbackground="white", bordercolor="#dde2eb"
        )
        style.configure(
            "Horizontal.TProgressbar",
            background=BLUE,
            troughcolor="#e7ebf2",
            borderwidth=0,
            thickness=4,
        )

    def _build(self):
        outer = ttk.Frame(self, padding=(24, 16))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="Cofre Temporal", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Ajuda", style="Link.TButton", command=self.help).pack(
            side="right"
        )
        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        progress_track = ttk.Frame(footer, height=4)
        progress_track.pack(fill="x", pady=(0, 8))
        progress_track.pack_propagate(False)
        self.progress = ttk.Progressbar(progress_track, maximum=100)
        self.progress.pack(fill="both", expand=True)
        line = ttk.Frame(footer, height=42)
        line.pack(fill="x")
        line.pack_propagate(False)
        self.status_label = ttk.Label(
            line, textvariable=self.status, style="Muted.TLabel", wraplength=480
        )
        self.status_label.pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(line, text="Cancelar", command=self.cancel.set)
        self.open_button = ttk.Button(
            line, text="Abrir pasta", command=self.open_result
        )
        self.details_button = ttk.Button(
            line, text="Detalhes", style="Link.TButton", command=self.show_error
        )
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        protect = ttk.Frame(self.tabs, padding=(4, 16, 4, 0))
        restore = ttk.Frame(self.tabs, padding=(4, 20, 4, 0))
        self.tabs.add(protect, text="Proteger")
        self.tabs.add(restore, text="Abrir")
        self._protect_tab(protect)
        self._restore_tab(restore)

    def _protect_tab(self, parent):
        actions = ttk.Frame(parent)
        actions.pack(fill="x")
        ttk.Button(actions, text="+ Arquivos", command=self.add_files).pack(side="left")
        ttk.Button(actions, text="+ Pasta", command=self.add_folder).pack(
            side="left", padx=6
        )
        self.remove_button = ttk.Button(
            actions,
            text="Remover",
            style="Link.TButton",
            command=self.remove,
            state="disabled",
        )
        self.remove_button.pack(side="left")
        ttk.Label(actions, textvariable=self.count, style="Muted.TLabel").pack(
            side="right"
        )
        table = ttk.Frame(parent)
        table.pack(fill="both", expand=True, pady=(10, 12))
        self.items = ttk.Treeview(
            table, columns=("name", "path"), show="headings", height=3
        )
        self.items.heading("name", text="Nome")
        self.items.heading("path", text="Local")
        self.items.column("name", width=200, minwidth=120)
        self.items.column("path", width=410, minwidth=180)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.items.yview)
        self.items.configure(yscrollcommand=scrollbar.set)
        self.items.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.items.bind("<<TreeviewSelect>>", self._selection_changed)
        self.items.bind("<Delete>", lambda _: self.remove())
        modes = ttk.Frame(parent)
        modes.pack(fill="x", pady=(0, 10))
        ttk.Label(modes, text="Desbloquear", style="Section.TLabel").pack(
            side="left", padx=(0, 22)
        )
        ttk.Radiobutton(
            modes,
            text="Por data",
            variable=self.mode,
            value="tempo",
            command=self._switch_mode,
        ).pack(side="left")
        ttk.Radiobutton(
            modes,
            text="Por senha",
            variable=self.mode,
            value="senha",
            command=self._switch_mode,
        ).pack(side="left", padx=22)
        self.options = ttk.Frame(parent)
        self.options.pack(fill="x")
        self.time_options = ttk.Frame(self.options)
        date_row = ttk.Frame(self.time_options)
        date_row.pack(fill="x")
        ttk.Entry(date_row, textvariable=self.release, width=22).pack(side="left")
        for label, period in (
            ("1 hora", {"hours": 1}),
            ("1 dia", {"days": 1}),
            ("7 dias", {"days": 7}),
        ):
            ttk.Button(
                date_row, text=label, command=lambda p=period: self._preset(**p)
            ).pack(side="left", padx=(6, 0))
        ttk.Label(
            self.time_options,
            text="Dia/mês/ano e hora local · sem senha de emergência · requer internet",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(7, 0))
        self.password_options = ttk.Frame(self.options)
        fields = ttk.Frame(self.password_options)
        fields.pack(fill="x")
        fields.columnconfigure((0, 1), weight=1)
        ttk.Label(
            fields, text="Senha · mínimo 12 caracteres", style="Muted.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(fields, text="Repetir senha", style="Muted.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        self.password_entry = ttk.Entry(fields, textvariable=self.password, show="•")
        self.password_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.confirm_entry = ttk.Entry(fields, textvariable=self.confirm, show="•")
        self.confirm_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(4, 0))
        ttk.Checkbutton(
            self.password_options,
            text="Mostrar senha",
            variable=self.show_password,
            command=self._show_password,
        ).pack(anchor="w", pady=(7, 0))
        self._switch_mode()
        destination = ttk.Frame(parent)
        destination.pack(fill="x", pady=(13, 10))
        ttk.Label(destination, text="Salvar em", style="Muted.TLabel").pack(
            side="left", padx=(0, 10)
        )
        ttk.Label(
            destination, textvariable=self.output_label, width=44, anchor="w"
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            destination,
            text="Escolher…",
            style="Link.TButton",
            command=self.choose_output,
        ).pack(side="right")
        self.protect_button = ttk.Button(
            parent, text="Criar cofre", style="Primary.TButton", command=self.protect
        )
        self.protect_button.pack(fill="x")
        ttk.Label(
            parent,
            text="Cria uma cópia protegida. Os originais continuam acessíveis.",
            style="Muted.TLabel",
        ).pack(pady=(8, 0))

    def _restore_tab(self, parent):
        ttk.Label(
            parent, text="Qual cofre você quer abrir?", style="Section.TLabel"
        ).pack(anchor="w", pady=(0, 10))
        pick = ttk.Frame(parent)
        pick.pack(fill="x")
        ttk.Button(pick, text="Selecionar cofre…", command=self.choose_archive).pack(
            side="left"
        )
        ttk.Label(pick, textvariable=self.archive_label, width=40).pack(
            side="left", padx=12
        )
        ttk.Label(
            parent, textvariable=self.release_info, style="Muted.TLabel", wraplength=620
        ).pack(anchor="w", pady=(10, 18))
        self.restore_options = ttk.Frame(parent)
        self.restore_options.pack(fill="x")
        self.restore_secret = ttk.Frame(self.restore_options)
        ttk.Label(self.restore_secret, text="Senha", style="Section.TLabel").pack(
            anchor="w", pady=(0, 6)
        )
        ttk.Entry(
            self.restore_secret, textvariable=self.restore_password, show="•"
        ).pack(fill="x")
        ttk.Label(parent, text="Restaurar em", style="Section.TLabel").pack(
            anchor="w", pady=(20, 8)
        )
        destination = ttk.Frame(parent)
        destination.pack(fill="x")
        ttk.Entry(destination, textvariable=self.restore_parent).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(
            destination, text="Alterar…", command=self.choose_restore_parent
        ).pack(side="right", padx=(8, 0))
        ttk.Label(
            parent,
            text="Uma nova pasta será criada ao lado do cofre, ou no local que você escolher.",
            style="Muted.TLabel",
            wraplength=620,
        ).pack(anchor="w", pady=(8, 20))
        self.restore_button = ttk.Button(
            parent,
            text="Abrir e restaurar",
            style="Primary.TButton",
            command=self.restore,
        )
        self.restore_button.pack(fill="x")

    def _output_changed(self, *_):
        self.output_label.set(self.output.get() or "Escolher ao criar")

    def _selection_changed(self, *_):
        self.remove_button.state(
            ["!disabled"] if self.items.selection() and not self.busy else ["disabled"]
        )

    def _notify(self, message, error=False):
        self.error_detail = message if error else ""
        self.status_label.configure(foreground="#b13c39" if error else MUTED)
        short = message.splitlines()[0] if message else "Não foi possível concluir."
        self.status.set(short if len(short) <= 150 else short[:147] + "…")
        self.details_button.pack_forget()
        if error and (len(message) > 150 or "\n" in message):
            self.details_button.pack(side="right")

    def show_error(self):
        messagebox.showerror("Detalhes", self.error_detail, parent=self)

    def help(self):
        messagebox.showinfo(
            "Como funciona",
            "POR DATA\n"
            "Abre somente após a data escolhida, sem senha. Precisa de internet e da rede drand. "
            "Depois da data, qualquer pessoa com o cofre pode abri-lo. "
            "Se a rede encerrar antes de publicar a chave, a recuperação pode ser impossível.\n\n"
            "POR SENHA\nZIP com conteúdo criptografado. Os nomes dos arquivos ficam visíveis. "
            "Não existe recuperação de senha esquecida.\n\n"
            "SEUS ARQUIVOS\nOs originais continuam acessíveis. A proteção vale para a cópia criada. "
            "Ao abrir, o programa restaura em uma nova pasta, sem substituir arquivos existentes.",
            parent=self,
        )

    def _preset(self, **kwargs):
        self.release.set(
            (datetime.now() + timedelta(**kwargs)).strftime("%d/%m/%Y %H:%M")
        )

    def _switch_mode(self):
        self.time_options.pack_forget()
        self.password_options.pack_forget()
        (
            self.time_options if self.mode.get() == "tempo" else self.password_options
        ).pack(fill="both", expand=True)
        if self.output.get():
            old = self.output.get()
            for suffix in (".zip.tlock", ".tlock", ".zip"):
                if old.lower().endswith(suffix):
                    old = old[: -len(suffix)]
                    break
            self.output.set(
                old + (".zip.tlock" if self.mode.get() == "tempo" else ".zip")
            )

    def _show_password(self):
        for entry in (self.password_entry, self.confirm_entry):
            entry.configure(show="" if self.show_password.get() else "•")

    def add_files(self):
        self._add(
            filedialog.askopenfilenames(
                parent=self, title="Escolha arquivos para proteger"
            )
        )

    def add_folder(self):
        value = filedialog.askdirectory(
            parent=self, title="Escolha uma pasta para proteger"
        )
        if value:
            self._add([value])

    def _add(self, paths):
        if self.busy:
            return
        for item in paths:
            path = Path(item)
            if path not in self.sources:
                self.sources.append(path)
        self._refresh_items()

    def remove(self):
        if self.busy:
            return
        selected = {int(item) for item in self.items.selection()}
        self.sources = [p for i, p in enumerate(self.sources) if i not in selected]
        self._refresh_items()

    def _refresh_items(self):
        self.items.delete(*self.items.get_children())
        for index, path in enumerate(self.sources):
            self.items.insert(
                "", "end", iid=str(index), values=(path.name, str(path.parent))
            )
        count = len(self.sources)
        self.count.set(
            "Nenhum item"
            if not count
            else f"{count} " + ("item" if count == 1 else "itens")
        )
        self._selection_changed()

    def choose_output(self):
        suffix = ".zip.tlock" if self.mode.get() == "tempo" else ".zip"
        previous = Path(self.output.get()) if self.output.get() else None
        initial = (
            previous.name
            if previous
            else (self.sources[0].stem if len(self.sources) == 1 else "meu-cofre")
            + suffix
        )
        options = {
            "parent": self,
            "title": "Salvar cofre",
            "initialfile": initial,
            "defaultextension": suffix,
            "filetypes": [("Cofre protegido", "*" + suffix)],
        }
        if previous:
            options["initialdir"] = str(previous.parent)
        elif self.sources:
            options["initialdir"] = str(self.sources[0].parent)
        path = filedialog.asksaveasfilename(**options)
        if path:
            self.output.set(path)
        return bool(path)

    def choose_archive(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Abrir cofre",
            filetypes=[
                ("Cofres e ZIPs", "*.tlock *.zip"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if not path:
            return
        self.restore_secret.pack_forget()
        self.restore_password.set("")
        self.archive.set(path)
        self.archive_label.set(Path(path).name)
        self.restore_parent.set(str(Path(path).parent))
        try:
            date = read_release_date(Path(path))
            if date:
                self.release_info.set(
                    "Liberação: "
                    + date.astimezone().strftime("%d/%m/%Y às %H:%M:%S")
                    + " · sem senha"
                )
            else:
                self.release_info.set("ZIP com senha")
                self.restore_secret.pack(fill="x")
        except (VaultError, OSError) as exc:
            self.archive.set("")
            self.archive_label.set("Nenhum cofre selecionado")
            self.release_info.set("Não foi possível ler este cofre.")
            self._notify(str(exc), error=True)

    def choose_restore_parent(self):
        path = filedialog.askdirectory(parent=self, title="Escolha a pasta de destino")
        if path:
            self.restore_parent.set(path)

    def protect(self):
        if self.busy:
            return
        try:
            if not self.sources:
                raise VaultError("Adicione um arquivo ou uma pasta para começar.")
            password = self.password.get()
            release = None
            if self.mode.get() == "senha":
                if len(password) < 12:
                    raise VaultError("Use uma senha com pelo menos 12 caracteres.")
                if password != self.confirm.get():
                    raise VaultError("As senhas não coincidem.")
            else:
                for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
                    try:
                        release = datetime.strptime(
                            self.release.get().strip(), fmt
                        ).astimezone()
                        break
                    except ValueError:
                        pass
                if release is None:
                    raise VaultError("Digite a data como DD/MM/AAAA HH:MM.")
                if release <= datetime.now().astimezone() + timedelta(seconds=5):
                    raise VaultError("Escolha uma data futura.")
            if not self.output.get().strip() or Path(self.output.get()).exists():
                if not self.choose_output():
                    return
            sources, output = list(self.sources), Path(self.output.get().strip())
            if self.mode.get() == "senha":
                self._start(
                    lambda: create_password_archive(
                        sources, output, password, self._progress, self.cancel
                    )
                )
            else:
                actual = date_for_round(round_for_date(release)).astimezone()
                self._start(
                    lambda: create_timed_archive(
                        sources, output, actual, self._progress, self.cancel
                    )
                )
        except (VaultError, OSError) as exc:
            self._notify(str(exc), error=True)

    def restore(self):
        if self.busy:
            return
        if not self.archive.get() or not self.restore_parent.get().strip():
            self._notify("Selecione um cofre e o local de restauração.", error=True)
            return
        source = Path(self.archive.get())
        stem = source.name
        for suffix in (".zip.tlock", ".tlock", ".zip"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        parent = Path(self.restore_parent.get().strip())
        destination = parent / f"{stem}_restaurado"
        index = 2
        while destination.exists():
            destination = parent / f"{stem}_restaurado_{index}"
            index += 1
        password = self.restore_password.get()
        self._start(
            lambda: restore_archive(
                source, destination, password, self._progress, self.cancel
            )
        )

    def _interactive(self, parent):
        for child in parent.winfo_children():
            if isinstance(
                child,
                (ttk.Button, ttk.Entry, ttk.Radiobutton, ttk.Checkbutton, ttk.Treeview),
            ):
                yield child
            yield from self._interactive(child)

    def _start(self, work):
        self.busy = True
        self.cancel.clear()
        self.saved_states = [
            (widget, widget.state()) for widget in self._interactive(self.tabs)
        ]
        for widget, _ in self.saved_states:
            widget.state(["disabled"])
        self.open_button.pack_forget()
        self.cancel_button.pack(side="right")
        self._notify("Preparando arquivos…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def run():
            try:
                self.events.put(("success", work()))
            except Cancelled as exc:
                self.events.put(("cancelled", str(exc)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=run, daemon=False).start()

    def _progress(self, fraction, text):
        self.events.put(("progress", (fraction, text)))

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    fraction, text = value
                    self.status.set(text if len(text) <= 150 else text[:147] + "…")
                    if fraction is None:
                        if str(self.progress.cget("mode")) != "indeterminate":
                            self.progress.configure(mode="indeterminate")
                            self.progress.start(12)
                    else:
                        self.progress.stop()
                        self.progress.configure(
                            mode="determinate", value=min(100, fraction * 100)
                        )
                    continue
                self.busy = False
                self.progress.stop()
                self.progress.configure(
                    mode="determinate", value=100 if kind == "success" else 0
                )
                for widget, state in self.saved_states:
                    widget.state(["!disabled", *state])
                self._selection_changed()
                self.cancel_button.pack_forget()
                self.password.set("")
                self.confirm.set("")
                self.restore_password.set("")
                if kind == "success":
                    self.last_result = Path(value)
                    self.open_button.pack(side="right")
                    self._notify("Concluído · " + self.last_result.name)
                else:
                    self._notify(value, error=kind == "error")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def open_result(self):
        if self.last_result:
            folder = (
                self.last_result
                if self.last_result.is_dir()
                else self.last_result.parent
            )
            try:
                os.startfile(str(folder))
            except OSError as exc:
                self._notify(str(exc), error=True)

    def close(self):
        if self.busy:
            self.cancel.set()
            self.status.set(
                "Cancelando… Aguarde a limpeza dos arquivos temporários e feche novamente."
            )
        else:
            self.destroy()


def main():
    if os.name == "nt":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    CofreApp().mainloop()
