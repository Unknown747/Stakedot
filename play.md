# 🎲 Stake Dice Bot — Panduan Lengkap

---

## 📋 Daftar Isi
1. [Konfigurasi Cepat (Edit di Sini)](#1-konfigurasi-cepat-edit-di-sini)
2. [Setup API Key Stake.com](#2-setup-api-key-stakecom)
3. [Setup Notifikasi Telegram](#3-setup-notifikasi-telegram)
4. [Instalasi & Menjalankan](#4-instalasi--menjalankan)
5. [Panduan Menu (Mode 1 / 2 / 3)](#5-panduan-menu-mode-1--2--3)
6. [Deploy di VPS](#6-deploy-di-vps)
7. [Perkiraan Kecepatan & Target VIP](#7-perkiraan-kecepatan--target-vip)
8. [Struktur File](#8-struktur-file)

---

## 1. Konfigurasi Cepat (Edit di Sini)

Semua variabel yang sering diubah ada di **satu blok** dalam `dice.py` fungsi `jalankan_strategy_vip()`:

```python
# ── Konfigurasi strategi ──────────────────────────────────────────────────
currency            = "idr"
base_bet            = Decimal("400")       # ← UBAH NILAI BET (Rp 200 / 400 / 500 / 1000)
rest_setiap_volume  = Decimal("5000000")   # ← Istirahat setiap X rupiah wager (default 5 juta)
rest_menit_volume   = 15                   # ← Durasi istirahat volume checkpoint (menit)
max_loss_limit      = Decimal("30000")     # ← Stop-loss: berhenti jika loss ≥ X (default 30 ribu)
topup_alert_idr     = Decimal("50000")     # ← Kirim alert Telegram jika saldo < X (default 50 ribu)
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
> `python-dotenv` tidak wajib diinstall. Jika tidak ada, pakai cara export di atas.

---

## 3. Setup Notifikasi Telegram

Bot otomatis kirim notifikasi ke HP kamu saat:
- ✅ Checkpoint wager tercapai (tiap 5 juta)
- 🛑 Stop-loss terpicu
- 🎉 Level VIP naik
- 📊 Ringkasan setiap sesi selesai

### Langkah setup:

**Step 1 — Buat Bot Telegram:**
1. Buka Telegram → cari **@BotFather**
2. Kirim `/newbot`
3. Ikuti instruksi → salin **Bot Token** (format: `123456:ABCdef...`)

**Step 2 — Dapatkan Chat ID:**
1. Kirim pesan apa saja ke bot kamu
2. Buka browser: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Cari `"chat":{"id":` → salin angkanya (contoh: `987654321`)

**Step 3 — Set environment variable:**
```bash
echo 'export TELEGRAM_BOT_TOKEN="token_kamu"' >> ~/.bashrc
echo 'export TELEGRAM_CHAT_ID="chat_id_kamu"' >> ~/.bashrc
source ~/.bashrc
```

> Jika `TELEGRAM_BOT_TOKEN` tidak diset, script tetap berjalan normal — notifikasi hanya di-skip diam-diam.

---

## 4. Instalasi & Menjalankan

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

## 5. Panduan Menu (Mode 1 / 2 / 3)

```
  1. Dice Biasa       — atur sendiri currency, bet, target, dll
  2. Strategy VIP IDR — auto-bet 98% win, Rp 400/roll, istirahat otomatis
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
| Base Bet | **Rp 400** (ubah di variabel `base_bet`) |
| Win Chance | 98% |
| Multiplier | ~1.0102x |
| Delay antar bet | 0.2 – 0.8 detik (speed mode) |
| Log terminal | Setiap 50 bet |
| Istirahat checkpoint | Setiap Rp 5.000.000 wager → 15 menit, lanjut otomatis |
| Stop-loss | Loss ≥ Rp 30.000 → istirahat 5–10 menit, lanjut sesi baru |
| **Top-Up Alert** | **Saldo < Rp 50.000 → notif Telegram (sekali per sesi)** |
| Notifikasi | Telegram (jika disetup) |

Fitur otomatis:
- VIP status + progress bar sebelum sesi
- VIP progress di-refresh setelah sesi
- Alert + notifikasi Telegram jika level VIP naik
- Log sesi disimpan ke `log_sesi.csv`
- Setelah tiap sesi: tanya y/n untuk sesi baru

---

### Mode 3 — VPS Auto-Run 🖥️

Seperti Mode 2 tapi **jalan sepenuhnya otomatis tanpa input**:

- Tanya durasi istirahat antar sesi (default 60 menit)
- Setelah tiap sesi selesai: countdown istirahat → mulai sesi baru otomatis
- Ctrl+C saat **betting** = keluar program
- Ctrl+C saat **countdown** = skip istirahat, langsung sesi baru

```
  ⏸  Istirahat 60 menit — sesi berikutnya ± pukul 15:30
  ⏰  [████████░░░░░░░░░░░░░░░░░░░░░░░░░░░] 52:18 tersisa
```

---

## 6. Deploy di VPS

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

# Opsional: Telegram
echo 'export TELEGRAM_BOT_TOKEN="token_kamu"' >> ~/.bashrc
echo 'export TELEGRAM_CHAT_ID="chat_id_kamu"' >> ~/.bashrc

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

## 7. Perkiraan Kecepatan & Target VIP

### Dengan Base Bet Rp 400, delay 0.2–0.8 detik:

| Metrik | Estimasi |
|---|---|
| Kecepatan | ~118 bet/menit |
| Volume per jam | ~Rp 2.800.000 |
| Checkpoint 5 juta | tercapai dalam ~1 jam 45 menit |
| Stop-loss Rp 30.000 | terpicu rata-rata setiap ~6.600 bet |

### Target VIP Silver (sisa ~$10.500 ≈ Rp 168 juta wager):

| Base Bet | Volume/jam | Estimasi total waktu |
|---|---|---|
| Rp 200 | ~Rp 1.400.000 | ~120 jam |
| **Rp 400** | **~Rp 2.800.000** | **~60 jam** |
| Rp 500 | ~Rp 3.500.000 | ~48 jam |

> House edge 1% — expected loss per Rp 100.000 modal ≈ Rp 1.000 per sesi.  
> Script berhenti otomatis jika loss ≥ Rp 30.000 dari saldo awal.

---

## 8. Struktur File

```
/
├── dice.py          ← Script utama (edit variabel di jalankan_strategy_vip)
├── test_audit.py    ← Audit & test semua komponen
├── setup.sh         ← Setup otomatis di VPS Ubuntu
├── play.md          ← Panduan ini
├── requirements.txt ← Dependensi Python
├── .gitignore       ← File yang dikecualikan dari git
└── log_sesi.csv     ← Log otomatis setiap sesi (dibuat saat pertama run)
```

---

## ⚠️ Peringatan Penting

- Script ini menggunakan **API resmi Stake.com** — bukan browser bot
- Semua taruhan menggunakan **uang nyata** dari akun kamu
- House edge tetap ada — tidak ada strategi yang 100% profit
- Gunakan dengan bijak sesuai kemampuan finansial
