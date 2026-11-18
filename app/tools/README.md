# tools

`demo-analysis.exe` is Nocrex's open-source TF2 cheat checker
([github.com/Nocrex/demo-analysis](https://github.com/Nocrex/demo-analysis), GPL-3.0). The scanner's live cheat
check (`demo_check.py`) runs it on the demo TF2 is recording. It's not in git (it's a built program).

`1 - Install.bat` downloads it for you: `cli.exe` from the official v3 release, checked against the SHA-256 that GitHub
publishes for it (in `tf2_setup.py`). To build it yourself instead:

```
git clone --branch v3 https://github.com/Nocrex/demo-analysis.git
cd demo-analysis
cargo build --release --bin cli
copy target\release\cli.exe ..\tools\demo-analysis.exe
```

With the GNU Rust toolchain on Windows, a MinGW-w64 `bin` folder (for `dlltool`) has to be on PATH.
Its results are the same as the release's `gui.exe` (checked on a real demo: all 56 detections identical).
