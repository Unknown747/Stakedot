# 🎲 Stake.com Dice CLI — Panduan Setup & Penggunaan

---

## 📋 Daftar Isi
1. [Cara Mendapatkan API Key Stake.com](#1-cara-mendapatkan-api-key-stakecom)
2. [Setting Environment Variable](#2-setting-environment-variable)
3. [Instalasi Dependensi](#3-instalasi-dependensi)
4. [Cara Menjalankan Script](#4-cara-menjalankan-script)
5. [Panduan Menu](#5-panduan-menu)
6. [Strategy VIP (Rekomendasi)](#6-strategy-vip-rekomendasi)
7. [Audit & Test](#7-audit--test)
8. [Struktur File](#8-struktur-file)

---

## 1. Cara Mendapatkan API Key Stake.com

1. Login ke akun Stake.com kamu
2. Klik foto profil → **Settings**
3. Pilih tab **API**
4. Klik **Create API Key**
5. Beri nama key (contoh: `dice-cli`)
6. Salin key yang muncul — **simpan baik-baik, hanya tampil sekali**

> ⚠️ Jangan bagikan API Key ke siapapun. Key ini punya akses penuh ke akun kamu.

---

## 2. Setting Environment Variable

Ada **3 cara** tergantung kamu menjalankan script di mana:

---

### ✅ Cara A — Di Replit (Direkomendasikan)

Replit menyimpan API Key sebagai **Secret** (lebih aman dari .env biasa):

1. Di Replit, klik ikon **🔒 Secrets** di sidebar kiri
2. Klik **+ New Secret**
3. Isi:
   - **Key** : `STAKE_API_KEY`
   - **Value**: paste API Key Stake.com kamu
4. Klik **Save**
5. Jalankan script — key otomatis terbaca

> Secret Replit **tidak perlu** file `.env`. Langsung bisa dipakai.

---

### ✅ Cara B — Di Komputer Lokal (via file `.env`)

**Langkah 1** — Buat file `.env` di folder yang sama dengan `dice.py`:

```
STAKE_API_KEY=masukkan_api_key_kamu_disini
```

**Langkah 2** — Install library `python-dotenv`:

```bash
pip install python-dotenv requests
```

**Langkah 3** — Tambahkan baris ini di paling atas `dice.py` (setelah `import os`):

```python
from dotenv import load_dotenv
load_dotenv()
```

---

### ✅ Cara C — Export langsung di Terminal

**Linux / macOS / Replit Shell:**
```bash
export STAKE_API_KEY=masukkan_api_key_kamu_disini
python dice.py
```

**Windows (Command Prompt):**
```cmd
set STAKE_API_KEY=masukkan_api_key_kamu_disini
python dice.py
```

**Windows (PowerShell):**
```powershell
$env:STAKE_API_KEY = "masukkan_api_key_kamu_disini"
python dice.py
```

---

## 3. Instalasi Dependensi

```bash
pip install -r requirements.txt
```

Atau manual:
```bash
pip install requests
```

Jika pakai `.env` (Cara B):
```bash
pip install requests python-dotenv
```

---

## 4. Cara Menjalankan Script

```bash
python dice.py
```

Script akan otomatis:
- Cek API Key
- Login ke Stake.com
- Tampilkan statistik kumulatif dari semua sesi sebelumnya
- Tampilkan saldo akun
- Tampilkan menu pilihan mode

---

## 5. Panduan Menu

### Menu Utama — Pilih Mode

```
1. Dice Biasa       — atur sendiri currency, bet, target, dll
2. Strategy VIP IDR — auto-bet 98% win, Rp 200/roll, stop-loss Rp 30rb
```

---

### Mode 1 — Dice Biasa

Konfigurasi manual, kamu atur sendiri:

| Langkah | Pilihan |
|---|---|
| Currency | BTC / ETH / LTC / DOGE / XRP / TRX / USDT / USDC / BNB / IDR |
| Jumlah bet | Bebas (angka positif) |
| Target number | 1.01 – 97.99 |
| Kondisi | Over (hasil > target) atau Under (hasil < target) |
| Mode bermain | Manual (Enter tiap bet) atau Auto (otomatis) |

**Jika pilih Auto, bisa setting tambahan:**
- Jumlah ronde (0 = tanpa batas)
- Jeda antar bet (detik)
- Stop jika profit ≥ X
- Stop jika loss ≥ X

---

### Mode 2 — Strategy VIP IDR ⭐

Auto-bet langsung jalan tanpa konfigurasi tambahan:

| Setting | Nilai |
|---|---|
| Currency | IDR (Rupiah) |
| Bet per roll | Rp 200 (flat, tidak naik saat kalah) |
| Win chance | 98% |
| Multiplier | 1.0102x |
| Profit per menang | ~Rp 2 |
| Stop otomatis | Total wager ≥ Rp 2.000.000 |
| Stop-loss | Loss kumulatif ≥ Rp 30.000 |
| Jeda antar bet | 0.6 – 1.3 detik (acak) |
| Auto-restart | Tanya lanjut sesi baru setelah selesai |

**Fitur otomatis di setiap sesi:**
- VIP status + progress bar tampil di atas CLI sebelum sesi dimulai
- VIP progress di-refresh dari API setelah sesi selesai
- Alert khusus jika level VIP naik selama sesi
- Log sesi disimpan ke `log_sesi.csv` secara otomatis

---

## 6. Strategy VIP (Rekomendasi)

### Kenapa 98% Win Chance?

- Saldo turun sangat perlahan dan stabil
- Risiko bust mendadak sangat kecil
- Fokus pada **volume taruhan** (untuk naik VIP), bukan profit
- Dengan modal Rp 100.000 dan bet Rp 200: estimasi tahan **~10.000 roll**

### Estimasi dengan Modal Rp 100.000

| | Nilai |
|---|---|
| Expected loss per roll | ~Rp 2 (house edge 1%) |
| Estimasi tahan | ~10.000 roll |
| Waktu (±1 detik/roll) | ~2.8 jam |
| Volume terkumpul | ~Rp 2.000.000 |

### Progress VIP Silver

- Dibutuhkan total wager **~$8.400 USD** (≈ Rp 137.000.000) untuk naik ke Silver
- Setiap sesi Rp 100.000 → mengumpulkan ~Rp 2.000.000 wager
- Perlu **~69 sesi** dengan modal masing-masing Rp 100.000

---

## 7. Audit & Test

Jalankan test script untuk memverifikasi semua komponen berjalan sebelum sesi panjang:

```bash
python test_audit.py
```

Test yang dicek secara otomatis:
1. **Koneksi & Login** — pastikan API Key valid
2. **VIP Status Display** — tampilkan progress bar
3. **Saldo IDR** — konfirmasi saldo tersedia
4. **Live Bet 5 Ronde** — taruhan nyata kecil untuk validasi API
5. **Stop Condition Logic** — simulasi trigger target volume & stop-loss
6. **CSV Logging** — simpan & baca balik log sesi

---

## 🛑 Peringatan Penting

- Script ini menggunakan **API resmi Stake.com** — bukan browser bot
- Semua taruhan menggunakan **uang nyata** dari akun kamu
- House edge tetap ada di setiap strategi — tidak ada strategi yang 100% profit
- Gunakan dengan bijak dan sesuai kemampuan finansial

---

## 8. Struktur File

```
/
├── dice.py          ← Script utama
├── test_audit.py    ← Audit & test semua komponen
├── play.md          ← Panduan ini
├── requirements.txt ← Dependensi Python
├── .gitignore       ← File yang dikecualikan dari git
└── log_sesi.csv     ← Log otomatis setiap sesi (dibuat saat pertama run)
```
