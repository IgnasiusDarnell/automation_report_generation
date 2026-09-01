def terbilang(n: int) -> str:
    n = int(n)
    satuan = ["", "Satu", "Dua", "Tiga", "Empat", "Lima", "Enam", "Tujuh", "Delapan", "Sembilan", "Sepuluh", "Sebelas"]
    
    if n < 12:
        return satuan[n]
    elif n < 20:
        return f"{terbilang(n - 10)} Belas"
    elif n < 100:
        return f"{terbilang(n // 10)} Puluh {terbilang(n % 10)}".strip()
    elif n < 200:
        return f"Seratus {terbilang(n - 100)}".strip()
    elif n < 1000:
        return f"{terbilang(n // 100)} Ratus {terbilang(n % 100)}".strip()
    elif n < 2000:
        return f"Seribu {terbilang(n - 1000)}".strip()
    elif n < 1000000:
        return f"{terbilang(n // 1000)} Ribu {terbilang(n % 1000)}".strip()
    return str(n)

BULAN_NAMES = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni", 
    "Juli", "Agustus", "September", "Oktober", "November", "Desember"
]

HARI_NAMES = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]