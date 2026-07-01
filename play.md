# 🎯 Stake Limbo Bot — Panduan Lengkap

---

## 📋 Daftar Isi
1. [Konfigurasi Cepat (Edit di Sini)](#1-konfigurasi-cepat-edit-di-sini)
2. [Setup API Key Stake.com](#2-setup-api-key-stakecom)
3. [Instalasi & Menjalankan](#3-instalasi--menjalankan)
4. [Cara Kerja Bot (Auto-Run)](#4-cara-kerja-bot-auto-run)
5. [Deploy di VPS](#5-deploy-di-vps)
6. [Perkiraan Kecepatan & Target VIP](#6-perkiraan-kecepatan--target-vip)
7. [Struktur File](#7-struktur-file)

---

## 1. Konfigurasi Cepat (Edit di Sini)

Semua variabel yang sering diubah ada di **satu blok** dalam `main.py` fungsi `jalankan_strategy_vip()`:

```python
# ── Konfigurasi strategi ──────────────────────────────────────────────────
currency               = "idr"
base_bet               = Decimal("500")      # ← UBAH NILAI BET (Rp 500 / 1.000 / dst)
win_chance_pct         = 98                  # ← Win chance (%) — menentukan multiplier_target
rest_setiap_volume     = Decimal("2500000")  # ← Istirahat setiap X rupiah wager (default 2,5 juta)
rest_menit_volume      = 15                  # ← Durasi istirahat checkpoint (menit)
max_loss_limit         = Decimal("22500")    # ← Stop-loss: berhenti jika loss ≥ X (default 22,5 ribu)
topup_alert_idr        = Decimal("37500")    # ← Warning terminal jika saldo < X (default 37,5 ribu)
profit_lock_idr        = Decimal("10000")    # ← Kunci profit: berhenti jika profit ≥ X
on_loss_multiply_enabled = True              # ← Aktif/nonaktifkan on-loss multiply
on_loss_multiply_pct     = Decimal("2")      # ← Persentase kenaikan bet tiap kalah
on_loss_multiply_cap     = base_bet * 5      # ← Bet maksimum (cap 5× base bet)
```

> Semua batas (stop-loss, top-up alert, profit lock, checkpoint istirahat) sudah diturunkan proporsional (setengah) mengikuti penurunan base bet dari Rp 1.000 → Rp 500, supaya rasio risiko terhadap bet tetap konsisten dan saldo lebih tahan lama.

**Contoh ubah bet ke Rp 2.000:**
```python
base_bet = Decimal("2000")
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
python3 main.py
```

Tidak ada menu, tidak ada input apapun — bot langsung masuk ke mode **Auto-Run** begitu dijalankan.

---

## 4. Cara Kerja Bot (Auto-Run)

Bot ini hanya bermain game **Limbo** (mode game Dice lama sudah dihapus total dari script).

| Setting | Nilai |
|---|---|
| Game | **Limbo** (`limboBet` GraphQL mutation) |
| Currency | IDR (Rupiah) |
| Base Bet | **Rp 500** (ubah di variabel `base_bet`) |
| Win Chance | 98% |
| Multiplier Target | ~1.0102x |
| Delay antar bet | Tidak ada — API Stake jadi natural throttle |
| Auto-throttle | Sleep otomatis jika >30 b/m (proteksi rate-limit) |
| Log terminal | Setiap spin: ✅/❌, bet aktif, wager, saldo, W/L, kecepatan (b/m), ETA |
| Istirahat checkpoint | Setiap Rp 2.500.000 wager → 15 menit, lanjut otomatis |
| Stop-loss | Loss ≥ Rp 22.500 → istirahat, lanjut sesi baru |
| Profit lock | Profit ≥ Rp 10.000 → sesi berhenti, kunci profit |
| Top-Up Alert | Saldo < Rp 37.500 → peringatan di terminal (sekali per sesi) |
| Log file | Setiap sesi disimpan ke `log_sesi.csv` (max 500 baris, rotasi otomatis) |
| Restart otomatis | Sesi baru mulai otomatis setelah istirahat 15 menit — jalan 24/7 tanpa input |

### 🔄 Sistem On-Loss Multiply (Money Management)

| Setting | Nilai default |
|---|---|
| Status | **AKTIF** (matikan: `on_loss_multiply_enabled = False`) |
| Kenaikan per kalah | **+2%** dari bet saat ini (compounding, bukan lipat ganda) |
| Reset | Menang → langsung kembali ke Base Bet |
| Cap keras | **5× Base Bet** (Rp 2.500 untuk base Rp 500) — bet tidak akan pernah melebihi ini |

**Logika alur:**
```
Bet (Rp 500)
  ├── MENANG → reset ke Base Bet → lanjut
  └── KALAH  → bet naik 2% (Rp 510) → lanjut
                ├── MENANG → reset ke Base Bet → lanjut
                └── KALAH  → naik lagi 2% (maks 5× base bet) → lanjut
```

> **Catatan:** kenaikan 2% per kalah jauh lebih ringan dibanding martingale (yang melipatgandakan
> bet tiap kalah). Ini meredam erosi saldo tanpa risiko ledakan bet yang cepat menghabiskan modal.

**Contoh tampilan log terminal:**
```
✅ #24 · Bet 500 · Wgr 12.000 · Sld 188.940 · Loss 0 · W/L 24/0 (100.0%)
❌ #25 · Bet 500 · Wgr 12.500 · Sld 188.440 · Loss 500 · W/L 24/1 (96.0%)
✅ #26 · x1.02 510 · Wgr 13.010 · Sld 188.950 · Loss 0 · W/L 25/1 (96.2%)
```

Fitur otomatis:
- VIP status + progress bar sebelum sesi
- VIP progress di-refresh setelah sesi
- Alert terminal jika level VIP naik
- Setelah tiap sesi: istirahat otomatis 15 menit, lalu sesi baru otomatis (tanpa input)
- Ctrl+C saat **betting** = keluar program
- Ctrl+C saat **countdown istirahat** = skip istirahat, langsung sesi baru

```
  ⏸  Istirahat 15 menit — sesi berikutnya ± pukul 15:30
  ⏰  [████████░░░░░░░░░░░░░░░░░░░░░░░░░░░] 12:18 tersisa
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
python3 main.py          # bot langsung auto-run, tanpa menu

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

### Dengan Base Bet Rp 500, rata-rata 8 b/m:

| Metrik | Estimasi |
|---|---|
| Volume per jam | ~Rp 240.000 |
| Checkpoint 2,5 juta | tercapai dalam ~10,4 jam |
| Stop-loss Rp 22.500 | terpicu rata-rata setiap ~4.500 bet |

> **Catatan:** Kecepatan sebenarnya ditentukan oleh response time server Stake, bukan script.
> ETA ke target wager tampil langsung di log terminal setiap spin.

### Target VIP Silver (sisa ~$10.500 ≈ Rp 168 juta wager):

| Base Bet | Volume/jam (est.) | Estimasi total waktu |
|---|---|---|
| Rp 500 | ~Rp 240.000 | ~700 jam |
| Rp 1.000 | ~Rp 480.000 | ~350 jam |
| Rp 2.000 | ~Rp 960.000 | ~175 jam |

> House edge ~1% — expected loss per Rp 100.000 modal ≈ Rp 1.000 per sesi.
> Script berhenti otomatis jika loss ≥ Rp 22.500 dari saldo awal.

---

## 7. Struktur File

```
/
├── main.py              ← Script utama (edit variabel di jalankan_strategy_vip)
├── test_audit.py        ← Audit & test semua komponen (game Limbo)
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
