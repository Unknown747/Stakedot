# 🎲 Stake Dice Bot — Panduan Lengkap

---

## 📋 Daftar Isi
1. [Konfigurasi Cepat (Edit di Sini)](#1-konfigurasi-cepat-edit-di-sini)
2. [Setup API Key Stake.com](#2-setup-api-key-stakecom)
3. [Instalasi & Menjalankan](#3-instalasi--menjalankan)
4. [Panduan Menu (Mode 1 / 2 / 3)](#4-panduan-menu-mode-1--2--3)
5. [Deploy di VPS](#5-deploy-di-vps)
6. [Perkiraan Kecepatan & Target VIP](#6-perkiraan-kecepatan--target-vip)
7. [Struktur File](#7-struktur-file)

---

## 1. Konfigurasi Cepat (Edit di Sini)

Semua variabel yang sering diubah ada di **satu blok** dalam `dice.py` fungsi `jalankan_strategy_vip()`:

```python
# ── Konfigurasi strategi ──────────────────────────────────────────────────
currency            = "idr"
base_bet            = Decimal("400")       # ← UBAH NILAI BET (Rp 400 / 600 / 800 / 1000)
rest_setiap_volume  = Decimal("5000000")   # ← Istirahat setiap X rupiah wager (default 5 juta)
rest_menit_volume   = 15                   # ← Durasi istirahat checkpoint (menit)
max_loss_limit      = Decimal("45000")     # ← Stop-loss: berhenti jika loss ≥ X (default 45 ribu)
topup_alert_idr     = Decimal("75000")     # ← Warning terminal jika saldo < X (default 75 ribu)
```

**Contoh ubah bet ke Rp 500:**
```python
base_bet = Decimal("500")
```

**Contoh ubah stop-loss ke Rp 50.000:**
```python
max_loss_limit = Decimal("50000")
```

**Contoh istirahat setiap Rp 2 juta selama 10 menit:**
```python
rest_setiap_volume = Decimal("2000000")
rest_menit_volume  = 10
```

---

## 2. Setup API Key Stake.com

### Cara mendapatkan API Key
1. Login ke akun Stake.com
2. Klik foto profil → **Settings**
3. Pilih tab **API**
4. Klik **Create API Key** → beri nama → salin key

> ⚠️ Key hanya tampil sekali. Simpan baik-baik. Jangan bagikan ke siapapun.

---

### Set API Key — Pilih salah satu cara:

**Di VPS / Terminal Linux (permanen):**
```bash
echo 'export STAKE_API_KEY="api_key_kamu"' >> ~/.bashrc
source ~/.bashrc
```

**Di VPS / Terminal Linux (sementara, hilang setelah reboot):**
```bash
export STAKE_API_KEY="api_key_kamu"
```

**Di Replit (paling aman):**
1. Klik ikon 🔒 **Secrets** di sidebar kiri
2. Klik **+ New Secret**
3. Key: `STAKE_API_KEY` — Value: paste API key kamu

**Di file `.env` (lokal):**
```
STAKE_API_KEY=api_key_kamu
```

---

## 3. Instalasi & Menjalankan

### Instalasi (VPS Ubuntu)
```bash
# Cara cepat — jalankan setup otomatis:
bash setup.sh

# Atau manual:
sudo apt install python3 python3-pip screen -y
pip3 install requests
```

### Jalankan script
```bash
python3 dice.py
```

---

## 4. Panduan Menu (Mode 1 / 2 / 3)

```
  1. Dice Biasa       — atur sendiri currency, bet, target, dll
  2. Strategy VIP IDR — auto-bet 98% win, Rp 600/roll, istirahat otomatis
  3. VPS Auto-Run     — seperti mode 2, jalan 24/7 tanpa input
```

---

### Mode 1 — Dice Biasa

Konfigurasi manual sepenuhnya:

| Langkah | Pilihan |
|---|---|
| Currency | BTC / ETH / LTC / DOGE / XRP / TRX / USDT / USDC / BNB / IDR |
| Jumlah bet | Bebas (angka positif) |
| Target number | 1.01 – 97.99 |
| Kondisi | Over (hasil > target) atau Under (hasil < target) |
| Mode bermain | Manual (Enter tiap bet) atau Auto |

Jika pilih Auto:
- Jumlah ronde (0 = tanpa batas)
- Jeda antar bet (detik)
- Stop jika profit ≥ X
- Stop jika loss ≥ X

---

### Mode 2 — Strategy VIP IDR ⭐

Auto-bet langsung jalan:

| Setting | Nilai |
|---|---|
| Currency | IDR (Rupiah) |
| Base Bet | **Rp 600** (ubah di variabel `base_bet`) |
| Win Chance | 98% |
| Multiplier | ~1.0102x |
| Delay antar bet | Tidak ada — API Stake jadi natural throttle |
| Auto-throttle | Sleep otomatis jika >30 b/m (proteksi rate-limit) |
| Log terminal | Setiap spin: ✅/❌, wager, saldo, W/L, **kecepatan (b/m)**, **ETA ke 1 Juta** |
| Istirahat checkpoint | Setiap Rp 5.000.000 wager → 15 menit, lanjut otomatis |
| Stop-loss | Loss ≥ Rp 45.000 → istirahat 5–10 menit, lanjut sesi baru |
| Top-Up Alert | Saldo < Rp 75.000 → peringatan di terminal (sekali per sesi) |
| Log file | Setiap spin disimpan ke `log_sesi.csv` (max 500 baris, rotasi otomatis) |

**Contoh tampilan log terminal:**
```
✅ #24  │  Wager: 14.400  │  Saldo: 177.880  │  Loss: -147  │  W/L: 24/0 (100.0%)  │  6.3 b/m  │  ETA 1Jt: 158m  │  ⏱ 00:03:47
```

Fitur otomatis:
- VIP status + progress bar sebelum sesi
- VIP progress di-refresh setelah sesi
- Alert terminal jika level VIP naik
- Setelah tiap sesi: tanya y/n untuk sesi baru

---

### Mode 3 — VPS Auto-Run 🖥️

Seperti Mode 2 tapi **jalan sepenuhnya otomatis tanpa input**:

- Istirahat antar sesi otomatis 15 menit (hardcoded)
- Setelah tiap sesi selesai: countdown istirahat → mulai sesi baru otomatis
- Ctrl+C saat **betting** = keluar program
- Ctrl+C saat **countdown** = skip istirahat, langsung sesi baru

```
  ⏸  Istirahat 60 menit — sesi berikutnya ± pukul 15:30
  ⏰  [████████░░░░░░░░░░░░░░░░░░░░░░░░░░░] 52:18 tersisa
```

---

## 5. Deploy di VPS

### Setup otomatis (1 perintah):
```bash
bash setup.sh
```

### Setup manual:
```bash
# Install dependencies
sudo apt install python3 python3-pip screen -y
pip3 install requests

# Set API key permanen
echo 'export STAKE_API_KEY="api_key_kamu"' >> ~/.bashrc
source ~/.bashrc
```

### Jalankan di background (tetap jalan walau SSH ditutup):
```bash
screen -S stake          # buka sesi background
python3 dice.py          # jalankan bot
# → pilih Mode 3 untuk 24/7 otomatis

Ctrl+A lalu D            # detach (biarkan jalan di background)
```

### Perintah screen penting:

| Perintah | Fungsi |
|---|---|
| `screen -r stake` | Buka kembali sesi bot |
| `screen -ls` | Lihat semua sesi aktif |
| `Ctrl+A` lalu `D` | Detach tanpa matikan |
| `Ctrl+C` | Hentikan bot |

---

## 6. Perkiraan Kecepatan & Target VIP

### Kecepatan nyata (tanpa delay buatan, API Stake sebagai throttle):

| Kondisi API | Kecepatan |
|---|---|
| API cepat (1–2 dtk/resp) | ~25–30 b/m *(auto-throttle aktif)* |
| API normal (5–10 dtk/resp) | ~6–12 b/m |
| API lambat (>10 dtk/resp) | ~4–6 b/m |
| **Rata-rata nyata** | **~6–10 b/m** |

### Dengan Base Bet Rp 600, rata-rata 8 b/m:

| Metrik | Estimasi |
|---|---|
| Volume per jam | ~Rp 288.000 |
| Checkpoint 5 juta | tercapai dalam ~17 jam |
| Stop-loss Rp 45.000 | terpicu rata-rata setiap ~6.600 bet |

> **Catatan:** Kecepatan sebenarnya ditentukan oleh response time server Stake, bukan script.
> ETA ke Rp 1 Juta wager tampil langsung di log terminal setiap spin.

### Target VIP Silver (sisa ~$10.500 ≈ Rp 168 juta wager):

| Base Bet | Volume/jam (est.) | Estimasi total waktu |
|---|---|---|
| Rp 400 | ~Rp 192.000 | ~875 jam |
| **Rp 600** | **~Rp 288.000** | **~583 jam** |
| Rp 800 | ~Rp 384.000 | ~438 jam |

> House edge 1% — expected loss per Rp 100.000 modal ≈ Rp 1.000 per sesi.  
> Script berhenti otomatis jika loss ≥ Rp 45.000 dari saldo awal.

---

## 7. Struktur File

```
/
├── dice.py              ← Script utama (edit variabel di jalankan_strategy_vip)
├── test_audit.py        ← Audit & test semua komponen
├── setup.sh             ← Setup otomatis di VPS Ubuntu
├── play.md              ← Panduan ini
├── requirements.txt     ← Dependensi Python
├── .gitignore           ← File yang dikecualikan dari git
├── log_sesi.csv         ← Log aktif sesi berjalan (max 500 baris)
└── log_arsip/           ← Arsip log lama (max 10 file, rotasi otomatis)
    └── log_sesi_YYYYMMDD_HHMMSS.csv
```

---

## ⚠️ Peringatan Penting

- Script ini menggunakan **API resmi Stake.com** — bukan browser bot
- Semua taruhan menggunakan **uang nyata** dari akun kamu
- House edge tetap ada — tidak ada strategi yang 100% profit
- Gunakan dengan bijak sesuai kemampuan finansial
