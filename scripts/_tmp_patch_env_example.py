import io
import sys

PATH = '.env.example'

OLD = (
    '# 1b. DATABASE ZONEMINDER (OPSIONAL - hanya untuk scripts/test_db.py)\n'
    '# ------------------------------------------------------------------------------\n'
    '# Skrip diagnostik database TIDAK ikut container; dijalankan manual dari host.\n'
    '# Blok ini sengaja TIDAK dipakai docker-compose, jadi tidak akan membuat\n'
    '# docker compose up gagal walaupun dibiarkan seperti apa adanya.\n'
    '#\n'
    '# Perhatian: user MySQL ZoneMinder (default zmuser) berbeda dari user web\n'
    '# ZoneMinder. Lihat zm-conf/ atau Options > Database untuk nilainya.\n'
    'ZM_DB_HOST=localhost\n'
    'ZM_DB_PORT=3306\n'
    'ZM_DB_NAME=zm\n'
    '# ZM_DB_USER=zmuser\n'
    '# ZM_DB_PASS=ganti_dengan_password_mysql\n'
)

NEW = (
    '# 1b. DATABASE ZONEMINDER (OPSIONAL - HANYA untuk skrip host scripts/test_db.py)\n'
    '# ------------------------------------------------------------------------------\n'
    '# PENTING: blok ini TIDAK dipakai docker-compose. Database produksi mengambil\n'
    '# password dari docker secret (lihat docker-compose.yml):\n'
    '#   secrets/zm_db_pass.txt        -> service db & zoneminder\n'
    '#   secrets/mariadb_root_pass.txt -> service db\n'
    '#\n'
    '# Skrip diagnostik (python scripts/test_db.py) memakai PyMySQL langsung ke DB,\n'
    '# sehingga butuh host+port yang terekspos. Karena port DB produksi sengaja\n'
    '# tidak dipublikasikan, skrip ini biasanya perlu tunnel; jalur DB yang sudah\n'
    '# terbukti dari host adalah:\n'
    '#   bash scripts/dbq.sh \x22SELECT Id,Name FROM Monitors\x22\n'
    '#\n'
    '# Nilai contoh di bawah TIDAK sama dengan secret produksi. Isi ulang hanya\n'
    '# bila Anda benar-benar menjalankan scripts/test_db.py dari host.\n'
    'ZM_DB_HOST=localhost\n'
    'ZM_DB_PORT=3306\n'
    'ZM_DB_NAME=zm\n'
    '# ZM_DB_USER=zmuser\n'
    '# ZM_DB_PASS=ganti_sesuai_secrets_zm_db_pass.txt\n'
)

with io.open(PATH, 'r', encoding='utf-8', newline='') as f:
    txt = f.read()

count = txt.count(OLD)
print('occurrences_of_old_block=%d' % count)

if count == 1:
    new_txt = txt.replace(OLD, NEW)
elif count == 0:
    anchor = '# ZM_DB_PASS=ganti_dengan_password_mysql\n'
    acount = txt.count(anchor)
    print('fallback_anchor_occurrences=%d' % acount)
    if acount != 1:
        print('FAILED: no usable anchor')
        sys.exit(2)
    new_txt = txt.replace(anchor, '# ZM_DB_PASS=ganti_sesuai_secrets_zm_db_pass.txt\n')
else:
    print('FAILED: ambiguous old block')
    sys.exit(2)

if new_txt == txt:
    print('FAILED: no change')
    sys.exit(2)

with io.open(PATH, 'w', encoding='utf-8', newline='') as f:
    f.write(new_txt)

print('written=ok')
