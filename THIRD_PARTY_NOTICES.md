# Componentes de terceiros

- **drand/tlock 1.2.0** — Apache-2.0 e MIT. Os avisos originais estão em `src/cofre_temporal/vendor/LICENSE-APACHE` e `LICENSE-MIT`.
- **pyzipper 0.4.0** — MIT, com partes derivadas da biblioteca padrão do Python.
- **PyCryptodome / pycryptodomex 3.24.0** — BSD e domínio público, conforme a distribuição.
- **Python e Tcl/Tk** — licenças próprias. O aviso do Tcl está em `src/cofre_temporal/vendor/Tcl-license.terms`.
- **PyInstaller 6.22.3** — GPL com exceção para os aplicativos produzidos pelo bootloader.

Os caminhos acima se referem ao código-fonte. No pacote portátil, o script de build reúne esses avisos e as licenças das dependências na pasta `licenses/`, ao lado do executável. O binário `tle.exe` vem da release oficial, é verificado por SHA-256 e não é versionado neste repositório.
