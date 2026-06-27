#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  setup.sh — Setup otomatis Stake Dice Bot di VPS Ubuntu
#  Jalankan: bash setup.sh
# ─────────────────────────────────────────────────────────────

set -e

BOLD="\033[1m"
GREEN="\033[92m"
CYAN="\033[96m"
YELLOW="\033[93m"
RED="\033[91m"
DIM="\033[2m"
R="\033[0m"

header() { echo -e "\n${CYAN}◆ ${BOLD}$1${R}"; echo -e "${CYAN}$(printf '─%.0s' {1..52})${R}"; }
ok()     { echo -e "  ${GREEN}✅${R}  $1"; }
info()   { echo -e "  ${DIM}ℹ️   $1${R}"; }
warn()   { echo -e "  ${YELLOW}⚠️   $1${R}"; }
err()    { echo -e "  ${RED}❌  $1${R}"; }

echo -e "${CYAN}"
echo "  ╔═════════════════════════════════════════════════════╗"
echo "  ║       Stake Dice Bot — VPS Setup Script             ║"
echo "  ║       Ubuntu 22.04 LTS  ·  by setup.sh             ║"
echo "  ╚═════════════════════════════════════════════════════╝"
echo -e "${R}"

# ── 1. Cek OS ────────────────────────────────────────────────
header "1. Cek Sistem"
if ! command -v apt &>/dev/null; then
    err "Script ini hanya untuk Ubuntu/Debian. Keluar."
    exit 1
fi
ok "Ubuntu/Debian terdeteksi"

# ── 2. Update & install paket sistem ────────────────────────
header "2. Install Paket Sistem"
info "Menjalankan apt update..."
sudo apt update -qq
sudo apt install -y python3 python3-pip screen curl 2>/dev/null | tail -1
ok "python3, pip3, screen terinstall"

# ── 3. Install requests (satu-satunya dependency wajib) ─────
header "3. Install Python Dependencies"
pip3 install requests --quiet
ok "requests terinstall"

# ── 4. Set API Key ───────────────────────────────────────────
header "4. Konfigurasi API Key"
echo -e "  ${DIM}Generate API key di: Stake.com → Settings → API${R}\n"

if [ -n "$STAKE_API_KEY" ]; then
    warn "STAKE_API_KEY sudah ada di environment, skip input."
else
    read -rp "  Masukkan STAKE_API_KEY kamu: " INPUT_KEY
    if [ -z "$INPUT_KEY" ]; then
        warn "API key kosong — skip. Set manual nanti dengan:"
        echo -e "  ${DIM}export STAKE_API_KEY=\"key_kamu\"${R}"
    else
        # Simpan ke ~/.bashrc agar permanen
        # Hapus entry lama dulu jika ada
        sed -i '/^export STAKE_API_KEY=/d' ~/.bashrc
        echo "export STAKE_API_KEY=\"$INPUT_KEY\"" >> ~/.bashrc
        export STAKE_API_KEY="$INPUT_KEY"
        ok "API key disimpan ke ~/.bashrc (permanen)"
    fi
fi

# ── 5. Cek file dice.py ──────────────────────────────────────
header "5. Cek File Bot"
if [ ! -f "dice.py" ]; then
    err "dice.py tidak ditemukan di direktori ini: $(pwd)"
    echo -e "  ${DIM}Pastikan kamu menjalankan setup.sh di folder yang sama dengan dice.py${R}"
    exit 1
fi
ok "dice.py ditemukan"

# Cek syntax Python
if python3 -c "import ast; ast.parse(open('dice.py').read())" 2>/dev/null; then
    ok "Syntax dice.py valid"
else
    err "Syntax dice.py ada masalah. Periksa file."
    exit 1
fi

# ── 6. Buat script launcher ──────────────────────────────────
header "6. Buat Launcher"
LAUNCH_DIR="$(pwd)"

cat > run.sh << EOF
#!/bin/bash
# Launcher Stake Dice Bot
cd "$LAUNCH_DIR"
source ~/.bashrc
python3 dice.py
EOF
chmod +x run.sh
ok "run.sh dibuat"

# ── 7. Instruksi penggunaan ───────────────────────────────────
header "7. Cara Menjalankan di VPS"

echo -e "
  ${BOLD}Jalankan bot:${R}
  ${CYAN}python3 dice.py${R}

  ${BOLD}Jalankan di background (tetap jalan walau SSH ditutup):${R}
  ${CYAN}screen -S stake${R}
  ${CYAN}python3 dice.py${R}
  ${DIM}→ Pilih Mode 3 (VPS Auto-Run) untuk jalan 24/7${R}

  ${BOLD}Detach dari screen (biarkan jalan di background):${R}
  ${CYAN}Ctrl+A  lalu  D${R}

  ${BOLD}Kembali ke screen:${R}
  ${CYAN}screen -r stake${R}

  ${BOLD}Lihat semua screen aktif:${R}
  ${CYAN}screen -ls${R}

  ${BOLD}Matikan bot:${R}
  ${CYAN}screen -r stake${R}  lalu  ${CYAN}Ctrl+C${R}
"

echo -e "${GREEN}${BOLD}  Setup selesai! Bot siap dijalankan. 🚀${R}\n"
