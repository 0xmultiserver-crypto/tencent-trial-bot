# Tencent Cloud Free Trial Auto-Claim Bot

Bot otomatis buat klaim free trial VPS Tencent Cloud. Dirancang untuk Windows, otomatis klaim jam 11 malam (atau waktu lain yang lu设定).

## Fitur

- Auto-refresh dan klaim trial VPS
- Bisa setup waktu target (default 23:00 WIB)
- Retry otomatis kalau gagal
- Support login manual atau auto-login
- Notifikasi Telegram (optional)

## Persiapan

### 1. Install Python
Pastikan Python 3.8+ sudah terinstall:
```bash
python --version
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Install Chrome
Pastikan Google Chrome sudah terinstall di Windows lu.

## Konfigurasi

Edit `config.json` sesuai credentials lu:

```json
{
  "tencent": {
    "username": "081234567890",
    "password": "passwordlu",
    "login_method": "phone"
  },
  "scheduler": {
    "target_time": "23:00",
    "max_retries": 3,
    "pre_refresh_seconds": 120
  },
  "trial": {
    "target_spec": "2核2G3M"
  }
}
```

**Keterangan:**
- `username`: Nomor HP atau email Tencent Cloud
- `password`: Password akun Tencent
- `login_method`: "phone" atau "email"
- `target_time`: Jam target klaim (format HH:MM)
- `target_spec`: Spesifikasi VPS yang mau diclaim
- `pre_refresh_seconds`: Mulai refresh page N detik sebelum jam target

## Cara Pakai

### Run dengan jadwal (default 23:00):
```bash
python tencent_trial_bot.py
```

### Run langsung (tanpa nunggu):
```bash
python tencent_trial_bot.py --now
```

### Run jam tertentu:
```bash
python tencent_trial_bot.py --time 22:55
```

### Run headless (tanpa GUI):
```bash
python tencent_trial_bot.py --headless
```

## Cara Kerja

1. **T+120 detik**: Bot akan refresh page trial
2. **T+0 detik**: Bot klik tombol "试用" (Coba)
3. **Retry**: Kalau gagal, retry sampai 3x dengan interval 30 detik
4. **Success**: Kirim notifikasi kalau berhasil

## Troubleshooting

### Chrome driver error
```bash
# Install webdriver-manager otomatis
pip install webdriver-manager
```

### Login failed
Coba login manual dulu, lalu biarkan bot jalan. Bot akan detect kalau sudah login.

### Trial selalu diambil orang
- Kurangin `pre_refresh_seconds` jadi 60 atau 30
- Atau coba run jam 22:50-22:55 pagi banget

## Catatan

- Trial Tencent Cloud jujurcada每天限量 (daily limited)
- Kalau mau pastian dapat,尽量 run tepat waktu
- Jangan lupa edit config.json dulu sebelum run!

## License

MIT