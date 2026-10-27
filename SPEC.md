# SPEC: Download Manager (ala IDM)

Bina download manager untuk Windows yang setanding dengan IDM dari segi fungsi.
Guna clean-room design. Jangan rujuk atau decompile mana-mana software sedia ada.

## Stack

- Python 3.12
- Engine: `requests` (guna `Session` untuk connection pooling) + `threading` / `ThreadPoolExecutor`
- GUI: PySide6 (Fasa 2)
- Test: `pytest` dengan local `http.server` sebenar sebagai fixture
- Packaging: PyInstaller jadi satu `.exe`

## Fasa 1: Engine (CLI)

- HEAD request untuk dapatkan `Content-Length` dan check `Accept-Ranges`
- Pecah file kepada N segment (default 8, maksimum 32)
- Download semua segment serentak guna header `Range: bytes=start-end`
- Dynamic segmentation: bila satu segment siap awal, split segment yang paling lambat kepada dua
- Simpan state dalam fail `.json` supaya boleh resume lepas crash atau putus internet
- Fallback ke single connection kalau server tak support Range (balas 200, bukan 206)
- Verify saiz akhir, dengan checksum SHA-256 sebagai pilihan
- Retry dengan exponential backoff

Contoh penggunaan CLI:

```
python -m dlm get <url> -o <output> --segments 16
python -m dlm resume <file.json>
```

## Fasa 2: GUI

- Senarai download dengan progress bar untuk setiap segment
- Speed, ETA, pause, resume, cancel
- Queue dan had download serentak
- Speed limiter
- Engine jalan dalam worker thread, update UI guna Qt signal

## Fasa 3: Browser integration

- Extension Chrome (Manifest V3) yang tangkap download
- Hantar URL ke app guna Native Messaging

## Testing

Guna pytest fixture yang start local `http.server`:

- Serve fail sementara dengan kandungan rawak
- Sokong header Range (balas 206)
- Boleh paksa server balas 200 walaupun diminta Range
- Boleh paksa connection putus separuh jalan
- Uji resume, segmentation, dynamic split dan fallback
- Setiap test mesti banding SHA-256 fail hasil dengan fail asal

## Peraturan kerja

- Buat satu fasa pada satu masa. Mula dengan Fasa 1 sahaja.
- Terangkan setiap keputusan design secara ringkas sebelum tulis code.
- Tulis unit test untuk logik segmentation dan resume sebelum logik network.
- Tanya kalau ada requirement yang tak jelas.
