# Kısa kurulum rehberi

Bu proje Python 3.12 ile çalışan yerel bir araştırma demosudur. Varsayılan
kurulumda API anahtarı ve Docker gerekmez. CSV dosyaları örnek profildir;
çalıştırmalar simüle edilir.

## Windows PowerShell

Proje klasöründe:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Tarayıcıdan `http://127.0.0.1:8000/dashboard` adresini açın. API belgeleri
`http://127.0.0.1:8000/docs` adresindedir. Durdurmak için Ctrl+C kullanın.

## Linux

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

## Deneyler ve kontroller

Aşağıdaki `python` yerine sanal ortamın Python yolunu kullanın:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python tests/smoke_server.py
python -m ruff check .
python experiments/run_experiments.py --seed 42 --samples 50 --output-dir experiments/output
python experiments/generate_report.py --input experiments/output/experiment_results.json --output-dir experiments/output
python experiments/generate_plots.py --input experiments/output/experiment_results.json --output-dir experiments/output/figures
```

Gerçek Prophet için ayrıca `requirements-prophet.txt` kurulur. Kurulu değilse
model adı açıkça `exponential_smoothing` olur. Temel kurulumda deney testleri atlanır.

## Sonuçları yorumlama

- Tasarruf ölçülmüş değildir; istek başına varsayılan `0.001 kWh` ile tahmin edilir.
- Erteleme sadece öneridir; iş hemen bir kez çalışır, geleceğe kuyruklanmaz.
- SLA, tahmini temel gecikme hedefidir; toplam yanıt süresi garantisi değildir.
- Dört bölge modellenir. İsteğe bağlı OpenWhisk kurulumu tek yerel instance
  üzerindeki dört action'dır; dört coğrafi bölgeye dağıtım yapılmaz.
- Eski deneyler güncel sonuçları temsil etmez. Güncel çıktılar `experiments/output/`
  altında üretilir. Ortak yazarların lisans kararı henüz yoktur.

İsteğe bağlı ayarlar için `.env.example` dosyasını `.env` adıyla kopyalayın.
Anahtarları Git'e eklemeyin. Ayrıntılar [İngilizce README](README.md) ve
[uygulama planında](IYILESTIRME_PLANI.md) yer alır.
