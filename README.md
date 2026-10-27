# dlm — download manager (ala IDM)

[![build](https://github.com/workxart-hash/dlm-download-manager/actions/workflows/build.yml/badge.svg)](https://github.com/workxart-hash/dlm-download-manager/actions/workflows/build.yml)
[![latest release](https://img.shields.io/github/v/release/workxart-hash/dlm-download-manager)](https://github.com/workxart-hash/dlm-download-manager/releases/latest)

Clean-room, multi-segment download manager.
**Fasa 1 (engine + CLI), Fasa 2 (GUI PySide6), Fasa 3 (extension Chrome + native messaging) — semua siap.**
Tiada kod diambil atau di-decompile daripada mana-mana software sedia ada.

## Pasang (dev)

```bash
python -m venv .venv
.venv\Scripts\python -m pip install requests pytest
.venv\Scripts\python -m pip install PySide6-Essentials    # untuk GUI (Fasa 2)
```

## Guna

```bash
# Muat turun dengan 16 segmen
python -m dlm get https://example.com/big.iso -o big.iso --segments 16

# Sambung semula lepas crash / putus internet
python -m dlm resume big.iso.dlm.json

# Sahkan dengan checksum
python -m dlm get https://example.com/big.iso -o big.iso --sha256 <hex>

# Lancar GUI
python -m dlm gui
```

Pilihan `get`: `-o/--output`, `-s/--segments` (default 8, maks 32),
`--max-retries`, `--no-dynamic`, `--sha256`, `-q/--quiet`.

## GUI (Fasa 2)

- Jadual muat turun: nama, saiz, **progress %**, **speed**, **ETA**, status.
- **Pause / Resume / Cancel** setiap muat turun (resume guna state `.dlm.json`).
- **Queue** dengan had muat turun serentak (spinbox *Max concurrent*).
- **Speed limiter** global (KB/s; 0 = tanpa had) — dikongsi semua muat turun.
- Panel **bar progress per-segmen** untuk baris terpilih (ikut dynamic split).
- Engine jalan dalam `QThread`; UI dikemas kini melalui Qt signal.

## Browser integration (Fasa 3)

Extension Chrome (Manifest V3) menangkap muat turun pelayar dan menyerahkannya
ke dlm melalui **native messaging**.

Pasang:

```bash
# 1. Load extension: chrome://extensions > Developer mode > Load unpacked > pilih folder extension\
# 2. Salin ID extension yang terpapar, kemudian daftar native host:
python -m dlm install-host <extension-id>
# (buang kemudian: python -m dlm uninstall-host)
```

Dijalankan dari sumber (bukan exe beku), `install-host` menulis `.bat` yang
memanggil **python** (`<venv>\python.exe -m dlm.native.host`) dengan PYTHONPATH
diset — jadi ia berfungsi walaupun **Smart App Control menyekat `dlm.exe`**.
Untuk dev dan test, guna `python -m dlm ...` sepanjang masa; binari beku hanya
untuk edaran yang ditandatangani.

Cara kerja: `background.js` dengar `chrome.downloads.onCreated`, batalkan muat
turun pelayar, dan hantar `{type:"download", url, filename}` ke host
`com.dlm.native`. Host (`python -m dlm native-host`) membaca bingkai stdio
(4-bait panjang + JSON) dan melancarkan `dlm get` sebagai proses terpisah.
Popup extension ada suis on/off dan butang "Test host" (hantar `ping`).

## Keputusan design (Fasa 1)

- **Probe `HEAD`** untuk `Content-Length` + `Accept-Ranges`.
- **Multi-segment** `Range: bytes=start-end`, satu thread per segmen.
- **Dynamic segmentation** — bila satu worker habis dan jumlah segmen < 32, ia
  memecah baki segmen paling besar (≥ 1 MiB) kepada dua. Tulisan di-*cap* pada
  `end` semasa jadi tiada bertindih / lompang.
- **Resume** — kemajuan setiap segmen = saiz fail `.dlmpart_<start>`; sidecar
  `.dlm.json` simpan jadual segmen + `ETag`/saiz untuk tolak data basi.
- **Retry** — urllib3 `Retry` untuk ralat sambungan + gelung per-segmen untuk
  drop pertengahan stream (exponential backoff). Baca terus dari `r.raw` dengan
  `enforce_content_length=False` supaya bait yang diterima kekal walau putus.
- **Fallback** — kalau server balas `200` (bukan `206`), guna satu sambungan.
- **Verify** — saiz akhir wajib padan; SHA-256 pilihan.

## Seni bina

| Modul | Tanggungjawab |
|-------|---------------|
| `dlm/segmentation.py` | Logik tulen: rancang segmen, titik pecah (tiada I/O) |
| `dlm/state.py` | Simpan/muat state `.json`, semak keserasian resume |
| `dlm/engine.py` | Orkestra thread, Range, retry, fallback, dynamic split, pause/cancel/snapshot |
| `dlm/ratelimit.py` | Speed limiter token-bucket, thread-safe, boleh tukar masa jalan |
| `dlm/queue.py` | Polisi concurrency queue (tulen, tiada Qt) |
| `dlm/cli.py` | `get` / `resume` / `gui`, papar progress (speed + ETA) |
| `dlm/gui/worker.py` | `QThread` bungkus engine → Qt signal |
| `dlm/gui/app.py` | Tetingkap utama: jadual, segmen, queue, had laju |
| `dlm/native/protocol.py` | Codec bingkai native-messaging (tulen) |
| `dlm/native/host.py` | Gelung host stdio + penghantar mesej |
| `dlm/native/install.py` | Jana manifest host + daftar registry Chrome |
| `extension/` | Extension MV3: manifest, service worker, popup |

## Ujian

```bash
.venv\Scripts\python -m pytest -q
```

68 ujian. Logik tulen (segmentation, resume, speed limiter, queue, native
framing) diuji berasingan daripada network. Ujian network guna `http.server`
tempatan sebenar yang: sokong Range (206), boleh paksa `200`, boleh putus
separuh jalan, dan boleh lambatkan segmen untuk cetus dynamic split. GUI diuji
*headless* (`QT_QPA_PLATFORM=offscreen`) merentas keseluruhan stack. Native host
diuji pada peringkat mesej + bingkai; extension disahkan secara statik (manifest
MV3 sah, service worker wired betul). Setiap muat turun dibanding SHA-256 dengan
fail asal.

## Packaging (.exe)

Satu binari `dlm` membawa semuanya — `get`, `resume`, `gui`, dan `native-host`.

**Disyorkan — `--onedir`** (host mula pantas; Chrome melancarkan host setiap
mesej, jadi kita mahu elak ekstrak temp):

```bash
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller --onedir --name dlm --console ^
    --icon assets\dlm.ico --version-file assets\version_info.txt run_dlm.py
# hasil: dist\dlm\dlm.exe (+ folder dependency di sebelahnya)
```

Ikon (`assets\dlm.ico`) dijana oleh `assets\make_icon.py` (pure Python, tiada
dependency). Version-info (`assets\version_info.txt`) menetapkan ProductName/
FileVersion yang muncul dalam properties exe dan Add/Remove Programs.

**Alternatif — `--onefile`** (satu fail mudah diedar, tapi ekstrak ke temp
setiap lancar → native host ada lag mula):

```bash
.venv\Scripts\python -m PyInstaller --onefile --name dlm --console ^
    --icon assets\dlm.ico --version-file assets\version_info.txt run_dlm.py
# hasil: dist\dlm.exe
```

Guna (onedir):

```bash
dist\dlm\dlm.exe get https://example.com/big.iso -o big.iso --segments 16
dist\dlm\dlm.exe gui
dist\dlm\dlm.exe install-host <extension-id>   # daftar native host guna exe ini
```

`install-host` mengesan bila ia dijalankan sebagai exe beku (`sys.frozen`) dan
menulis wrapper `.bat` yang memanggil exe itu dengan `native-host` (bukan
`python -m`), jadi Chrome melancarkan terus binari beku.

### Installer (setup.exe)

`installer\dlm.iss` ialah skrip Inno Setup yang membungkus build `--onedir`
menjadi satu `setup.exe`. Ia **per-user** (tiada UAC) supaya native host didaftar
di bawah HKCU pengguna sebenar. Wizardnya minta Extension ID (boleh kosong) dan,
kalau diisi, terus daftar host `com.dlm.native`. Uninstaller buang shortcut,
entri PATH, fail host, dan kunci registri.

```bash
# 1. bina onedir dulu:
.venv\Scripts\python -m PyInstaller --onedir --name dlm --console run_dlm.py
# 2. compile installer (perlu Inno Setup 6):
ISCC.exe installer\dlm.iss
# hasil: installer\Output\dlm-setup-0.1.0.exe
```

Pasang Inno Setup: `winget install JRSoftware.InnoSetup`. ISCC.exe biasanya di
`C:\Program Files (x86)\Inno Setup 6\` (pasang admin) atau
`%LOCALAPPDATA%\Programs\Inno Setup 6\` (pasang winget per-user).

Nota: `setup.exe` tidak ditandatangani, jadi SmartScreen/Application Control
mungkin menyekatnya sehingga kau benarkan ia (atau tandatangani dengan sijil
code-signing).
