#!/usr/bin/env python3
"""
Live Test Terbatas — MINES (UANG ASLI)
Menjalankan logika production main.py (jalankan_strategy_mines_vip) dengan
batas keras N ronde, lalu berhenti otomatis. Tidak ada menu, tidak
ada pertanyaan interaktif — cocok untuk sekali jalan di VPS/shell.
"""

import sys
from main import (
    API_KEY, gql, USER_QUERY, jalankan_strategy_mines_vip,
    g, BOLD, GREEN, RED, YELLOW, print_banner,
)

MAKS_RONDE = int(sys.argv[1]) if len(sys.argv) > 1 else 5

if not API_KEY:
    print(g(RED, "❌ STAKE_API_KEY tidak ditemukan di environment."))
    sys.exit(1)

print_banner()
print(g(YELLOW, f"⏳ Menghubungkan ke Stake.com untuk live test MINES {MAKS_RONDE} ronde (UANG ASLI)..."))

try:
    user = gql(USER_QUERY)["user"]
except PermissionError as e:
    print(g(RED, f"❌ API Key tidak valid: {e}"))
    sys.exit(1)
except Exception as e:
    print(g(RED, f"❌ Gagal login: {e}"))
    sys.exit(1)

print(g(GREEN, f"✅ Login sebagai: {g(BOLD, user['name'])}"))
print(g(YELLOW, f"⚠️  Ini LIVE BET dengan uang asli, dibatasi keras {MAKS_RONDE} ronde saja.\n"))

jalankan_strategy_mines_vip(user, vps_mode=True, maks_ronde=MAKS_RONDE)

print(g(GREEN, "\n✅ Live test selesai — sesi dihentikan otomatis sesuai batas ronde."))
