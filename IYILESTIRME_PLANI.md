# Carbon-Aware Gateway — Sağlamlaştırma ve GitHub’a Hazırlık

**Plan tarihi:** 15 Eylül 2026
**Durum:** Tamamlandı. Uygulama, deney, yayın paketi ve yerel kabul kontrolleri tamamlandı; uzak GitHub CI/push kapsam dışıdır.
**Proje:** `cloud/`

## 1. Hedef ve inceleme sonucu

Proje; FastAPI, SQLite, karbon verisi sağlayıcıları, üç yönlendirme stratejisi, tahmin modelleri ve deney raporlarından oluşuyor. Mevcut modüler yapı korunabilir; baştan yazılması gerekmiyor.

**Öncelik, gösterilen sonuçların kodun gerçekten yaptığı işle örtüşmesi ve başka birinin projeyi kolayca çalıştırabilmesi.**

Kullanıcının seçtiği doğrultu:

- Anahtarsız çalışan portföy ve araştırma demosu.
- Gerçek kuyruk yerine gelecekteki uygun saati gösteren **erteleme önerisi**.
- İngilizce README ve Türkçe kurulum özeti.
- Canlı veri ve OpenWhisk isteğe bağlı entegrasyon olarak korunacak.

**İnceleme kapsamı:** 19 Python dosyası sözdizimi kontrolünden geçti. İzole fonksiyon kontrolleri ve uygulama içi HTTP çağrılarıyla aşağıdaki bazı hatalar yeniden üretildi. Hazır test paketi bulunmuyor; inceleme sırasındaki ortamda `pytest` ve `httpx` kurulu değil. Canlı servisler ve tam deney hattı çalıştırılmadı; inceleme sırasında kaynak dosyalar, veritabanı ve deney çıktıları değiştirilmedi.

## 2. Tespit edilen sorunlar

| Öncelik | Bulgu | Etkisi |
|---|---|---|
| Kritik | Erteleme işaretlenen istek hemen çalıştırılıyor. İzole kontrolde karar bölgesi DE, çalıştırılan bölge IE çıktı. | API, kayıtlar ve istatistikler gerçekte yapılan işi yanlış gösterebiliyor. |
| Kritik | Dashboard, kullanıcıdan gelen `action` değerini doğrudan `innerHTML` içine yerleştiriyor. | Kaydedilen bir istek, dashboard’da HTML/JavaScript çalıştırabilecek içerik taşıyabilir. |
| Yüksek | Optimizasyon baseline için kendisine verilen snapshot yerine yeniden veri okuyor; veritabanı ve dashboard ayrıca `380` sabitini kullanıyor. | Aynı isteğin tasarrufu farklı yerlerde farklı hesaplanıyor. |
| Yüksek | `0.001` enerji varsayımı açıklanmadan “CO₂ saved” gösteriliyor. Başarısız istekler de tasarruf toplamına girebiliyor. | Tahmini değerler ölçülmüş emisyon azaltımı gibi sunuluyor. |
| Yüksek | `/entsoe/status`, önce tanımlanan `/entsoe/{region}` tarafından yakalanıyor. | Durum endpoint’i yerine bölge sorgusu çalışıyor; HTTP çağrısıyla doğrulandı. |
| Yüksek | Geçersiz tahmin bölgesi HTTP 500 üretiyor; Prophet endpoint’inde adım sınırı yok. | Hatalı kullanıcı girdileri kontrollü karşılanmıyor. |
| Yüksek | `.env` yüklenmiyor; kod canlı ElectricityMaps kullanımını varsayılan açıyor, örnek dosya kapalı gösteriyor. Kodda sabit erişim değerleri bulunuyor. | Kurulum talimatı ile gerçek davranış uyuşmuyor. |
| Yüksek | Gerçek OpenWhisk hatası sessizce başarılı simülasyona dönüşebiliyor; kullanıcı verisi gerçek çağrıya aktarılmıyor. | Çalıştırma türü ve sonuç güvenilirliği belirsizleşiyor. |
| Yüksek | Deneyler uygulamadaki scheduler yerine ayrı uygulamalar kullanıyor; erteleme eşiği `400` yerine yaklaşık `65.2`, saatlik bekleme yerine `120 ms` ekleniyor. | Deney sonuçları uygulamanın mevcut davranışını temsil etmiyor. |
| Orta | Tahmin geçmişi saat etiketleriyle kayabiliyor; saatlik CSV yedeği geçmiş saat yerine mevcut saati örnekliyor. ARIMA ikinci farkı tek kez geri topluyor. | Tahminlerin zaman hizası ve bazı serilerde değerleri hatalı olabilir. |
| Orta | Prophet yedeği boş seride çöküyor; yedek model bazen “Prophet” kazandı diye etiketleniyor. | Model karşılaştırması yanıltıcı olabiliyor. |
| Orta | İki betik aynı `paper_numbers.json` dosyasını farklı şemalarla yazıyor. | Çıktının biçimi komutların çalışma sırasına bağlı. |
| Orta | Veritabanı hataları bazı yerlerde yutuluyor; round-robin hata halinde sürekli DE seçiyor. | Sistem arızalıyken normal çalışıyormuş gibi davranabiliyor. |
| Orta | Dashboard iki yerde birebir mevcut; MAE sabit yazılmış, veri kaynağı etiketleri eksik. | Bakım sırasında kopyalar ayrışabilir; arayüz güncel durumu göstermiyor. |
| Yayın hazırlığı | Git deposu, `.gitignore`, standart README ve CI bulunmuyor; klasörde Python dağıtımı, veritabanı ve loglar var. | Yanlış dosyaların GitHub’a yüklenmesi ve kurulumun başka makinelerde bozulması olası. |

Ek teknik bulgu: Prophet’te “hourly” adıyla verilen `period=24`, **24 gün** anlamına geliyor. Mevcut günlük mevsimsellik korunup bu yanlış ek bileşen kaldırılmalı. [Prophet resmi dokümantasyonu](https://facebook.github.io/prophet/docs/seasonality%2C_holiday_effects%2C_and_regressors.html)

## 3. Uygulama planı

### Aşama 1 — Yapılandırma ve güvenilir API

- [x] Tek yapılandırma noktası oluştur; `.env` dosyasını servis modüllerinden önce yükle. Gerçek ortam değişkenleri dosyadaki değerlerden öncelikli olsun.
- [x] Varsayılanları CSV verisi, simülasyon backend’i ve `127.0.0.1` olarak belirle. Python 3.12’yi desteklenen başlangıç sürümü yap.
- [x] Sabit anahtarları kaldır; örnek yapılandırmada boş değerler ve açıklamalar kullan.
- [x] Bölgeyi `DE/IE/FR/PL`, tahmin adımını tüm endpoint’lerde `1–24` olarak doğrula; hatalı girdilere 422 döndür.
- [x] Statik ENTSO-E durum rotasını dinamik bölge rotasından önce tanımla.
- [x] Başlangıç işlemlerini FastAPI lifespan düzenine taşı; beklenen dış servis hatalarını yapılandırılmış, gizli veri içermeyen loglarla bildir.
- [x] Dashboard’da kullanıcı ve servis kaynaklı metinleri güvenli DOM işlemleriyle göster.


### Aşama 2 — Yönlendirme ve metrik doğruluğu

- [x] Her yönlendirme için tek karbon snapshot’ı kullan. Seçim ve dört bölgenin aritmetik ortalaması olan round-robin referansı aynı girdiden hesaplansın.
- [x] API, veritabanı ve dashboard aynı hesaplanan metrikleri kullansın; istemcide yeniden tasarruf hesabı yapılmasın.
- [x] İstek başına enerji varsayımını `0.001 kWh` varsayılanıyla açıkça yapılandır ve sonuçlarda belirt. Tasarrufu “tahmini” olarak adlandır; negatif değerleri gizleme.
- [x] Başarısız çalıştırmaları başarı metriklerinden ayır; başarısız istekler için tasarruf hesaplama.
- [x] Erteleme önerisi, çalıştırılan bölgeyi değiştirmesin. İş mevcut karar bölgesinde hemen çalışsın; önerilen bölge, UTC zamanı ve tahmini karbon ayrı döndürülsün.
- [x] Varsayılan `400` eşiğini koru. Öneriyi göstermek için eşiği sonuç elde edecek şekilde değiştirmek yerine kontrollü yüksek karbon test senaryosu kullan.
- [x] Epsilon yönteminde SLA’yı sağlayan bölge yoksa en düşük gecikmeli bölgeyi seç ve `sla_satisfied=false` bildir. Bunun tahmini temel gecikme hedefi olduğunu açıkla.
- [x] Gerçek OpenWhisk modunda hata halinde simülasyona geçme; başarısız sonucu bildir. Kullanıcı parametrelerini aktar, gerçek backend’i ve toplam çağrı süresini koru.
- [x] Round-robin sayacını açık SQLite yazma işlemi içinde güncelle; hata halinde DE’ye sessiz dönüşü kaldır.

**API ve veri değişiklikleri:**

- [x] Yönlendirme yanıtına `deferral_recommendation`, çalıştırma backend’i, veri kaynağı, enerji varsayımı ve SLA sonucu eklenir.
- [x] Yeni istekler `exec_mode="immediate"` kullanır; eski `defer_info` alanı geçiş için `null` tutulur.
- [x] İstatistiklere başarılı/başarısız istek sayıları ve öneri sayısı eklenir.
- [x] Kayıtlara metrik sürümü eklenir. Eski kayıtlar korunur; yeni tasarruf toplamlarına karıştırılmaz.
- [x] Veritabanı yolu yapılandırılabilir olur; test ve deneyler uygulamanın veritabanını kullanmaz.

### Aşama 3 — Tahminler ve deneylerin tutarlılığı

- [x] Geçmiş ve gelecek zamanlarını son gözlem üzerinden üret; UTC zaman damgalarını kullan. CSV verisini güncel ölçüm yerine tekrarlanan örnek profil olarak etiketle.
- [x] ARIMA’da nokta tahminine eklenen rastgele gürültüyü kaldır; ikinci fark kullanıldığında iki aşamalı geri toplama yap. Tahmin ve hata ölçümünü ayırarak iç içe değerlendirmeyi kaldır.
- [x] Prophet’te hatalı mevsimselliği kaldır; eğitim ve değerlendirme ayarlarını eşitle. Boş/kısa seri, sıfır MAE ve changepoint hesabını düzelt.
- [x] Yedek modeli açıkça `exponential_smoothing` olarak raporla; hangi modelin çalıştığını ayrı alanla belirt.
- [x] ENTSO-E ayrıştırıcısında birim, zaman çözünürlüğü ve üretim/tüketim ayrımını örnek XML’lerle doğrula. MW değerlerini doğrudan MWh diye toplama; karbon hesabını üretim karışımından türetilen tahmin olarak sun. [ENTSO-E veri görünümü](https://transparency.entsoe.eu/generation/r2/actualGenerationPerProductionType/show?name=)
- [x] Deneyler ortak seçim ve metrik kodunu kullansın. Snapshot, saat ve rastgelelik bağımlılıkları dışarıdan verilebilsin.
- [x] Aynı iş yükünü stratejilere uygula; karşılaştırmalarda eşleştirilmiş örneklem düzenini kullan. İstatistik hesabını SciPy’ye bırak; boş/sabit örneklerde tanımsız sonuçları açıklamalı `null` olarak yaz.
- [x] Varsayılan deneyden sahte erteleme tasarrufunu ve `120 ms` bekleme ekini kaldır. Önerilerin olası faydası ayrı, gerçekleşmemiş tahmin olarak raporlansın.
- [x] Deney komutlarına `--seed`, `--samples`, `--output-dir` ekle. Varsayılan deney backend’i yalnız simülasyon olsun.
- [x] Deney betiği ana JSON’u üretsin; rapor betiği bu JSON’dan HTML ve tek şemalı makale özeti oluştursun.
- [x] Eski sonuçları tarihsel örnek olarak ayır; yeni sonuçlarla karşılaştırmadan eski yüzdeleri veya “Prophet daha iyi” iddiasını koruma.


### Aşama 4 — Dashboard ve kod temizliği

- [x] Dashboard’u tek HTML kaynağından sun; JavaScript ve CSS’yi statik dosyalara ayır. Mevcut görünümü koru.
- [x] MAE, veri kaynağı, backend ve tasarruf bilgilerini API’den göster.
- [x] Küçük eklemeler olarak mevcut API’nin optimizasyon yöntemi seçimini ve erteleme önerisini arayüze aç.
- [x] HTTP hata kontrolü, istek zaman aşımı ve üst üste binmeyen yenileme ekle. Bir panelin hatası diğer panelleri gizlemesin.
- [x] Mobil ekranlarda kartların ve tabloların kullanılabilirliğini düzelt; seçimleri erişilebilir düğmelere dönüştür. (390px headless Chromium kabulü geçti.)
- [x] Tekrarlanan bölge tanımlarını, kullanılmayan importları ve geçmiş düzeltmeleri anlatıp mevcut kodla çelişen yorumları temizle.
- [x] Yeni frontend framework’ü, ORM veya mikroservis ekleme.


### Aşama 5 — GitHub paketi

- [x] Temel uygulama, deney ve Prophet bağımlılıklarını ayır; grafikler için eksik `matplotlib` bağımlılığını ekle. Temiz ortamda doğrulanan sürümler için kilitli bağımlılık listesi oluştur.
- [x] `.gitignore` ile `.python`, `.docker-cli`, veritabanı/WAL dosyaları, loglar, önbellekler ve `.env` dosyalarını dışarıda bırak; yerel dosyaları silme.
- [x] İngilizce README’ye proje amacı, mimari, Windows/Linux kurulumları, örnek istek, ekran görüntüsü, deney komutları ve bilinen sınırlamaları ekle. Türkçe kısa rehber hazırla.
- [x] CSV’lerin kaynağı doğrulanamıyorsa “ENTSO-E’den alınmış gerçek veri” iddiasını kaldır; örnek veri olarak tanımla.
- [x] Akademik taslakta katkı sahiplerini koru; öğrenci numarası içeren iletişim satırlarını halka açık sürümden çıkar. Tek yerel OpenWhisk üzerinde dört action çalıştığını doğru anlat.
- [x] OpenWhisk betiğini mevcut container’ı otomatik silmeyecek, global CLI ayarlarını değiştirmeyecek ve hazır olmayan serviste hata verecek şekilde düzenle. Ortak worker dosyasını kullan.
- [x] Windows ve Linux üzerinde temel kurulum, test ve Ruff kontrolü çalıştıran GitHub Actions ekle. (İş akışı eklendi; GitHub üzerinde çalıştırıldığı iddia edilmiyor.)
- [x] Temiz yayın içeriğiyle yerel Git deposunu hazırla. Uzak GitHub deposu oluşturma ve push işlemini bu analiz kapsamına dahil etme.
- [x] Ortak yazarlı proje olduğu için lisans varsayarak ekleme; lisans kararı verilene kadar yeniden kullanım izni iddiasında bulunma.

## 4. Test ve kabul kriterleri

| Alan | Kabul ölçütü |
|---|---|
| Temiz kurulum | Python 3.12 ortamında temel bağımlılıklarla, API anahtarı ve Docker olmadan açılır. |
| API | `/entsoe/status` doğru yanıt verir; geçersiz bölge ve sınır dışı tahmin adımı 422 üretir. |
| Karar tutarlılığı | Karar, invocation, kayıt ve dashboard aynı çalıştırma bölgesini gösterir. |
| Erteleme önerisi | Yüksek karbon senaryosunda öneri oluşur; iş hemen ve yalnız bir kez çalışır; tahmini fayda gerçekleşmiş tasarrufa eklenmez. |
| Metrikler | Aynı snapshot ile bütün katmanlar aynı sonucu üretir; başarısız ve eski sürüm kayıtları yeni tasarruf toplamından ayrılır. |
| Optimizasyon | Eşit değerler, Pareto baskınlığı ve SLA’yı sağlayan bölge bulunmaması doğrulanır. |
| Entegrasyonlar | Zaman aşımı, bozuk yanıt ve OpenWhisk hatası sahte başarı üretmez; gerçek backend parametre aktarımı mock ile doğrulanır. |
| Tahminler | Boş/kısa/sabit seri, ikinci fark ve gece yarısı geçişi test edilir; yedek model doğru adlandırılır. |
| Deneyler | Aynı seed ve girdiler aynı sayısal sonuçları üretir; çıktı komutları şema değiştirmez; uygulama veritabanı etkilenmez. |
| Arayüz | HTML içeren `action` düz metin görünür; hata durumları, mobil görünüm ve yenileme davranışı tarayıcıda kontrol edilir. |
| Yayın | CI geçer; Git içeriğinde anahtar, kişisel çalışma verisi, log veya gömülü Python bulunmaz. |

## 5. Uygulama sırası ve kapsam sınırları

**Tamamlanma sırası:** Önce davranış ve metrik doğruluğu, ardından deneyler, sonra arayüz temizliği ve GitHub sunumu.

İlk sürüme gerçek kuyruk, kullanıcı hesabı, Kubernetes veya üretim dağıtımı eklenmeyecek. Mevcut mimari korunacak; büyük ve uğraştırıcı yeni özellikler yerine doğruluk, bakım kolaylığı, tekrarlanabilirlik ve sunum kalitesi iyileştirilecek.

Bu dosyanın oluşturulması uygulamayı başlatmaz. Kod değişiklikleri, bağımlılık kurulumu, veritabanı güncellemeleri, deney çıktılarının yeniden üretilmesi ve Git hazırlığı, kullanıcı daha sonra uygulamayı istediğinde yapılacaktır.

## 6. Uygulama ve doğrulama kaydı

### 15 Eylül 2026

- Kullanıcı uygulama talimatı verdi; Karpathy yönergeleriyle çalışma başladı.
- `config.py`: `.env` yükleme ve ortam önceliği, CSV/simülasyon/loopback varsayılanları, yapılandırılabilir SQLite yolu ve pozitif enerji varsayımı eklendi. Servislerdeki gömülü erişim değerleri kaldırıldı; dağıtım betikleri henüz denetlenmedi.
- API bölge/adım doğrulaması ve ENTSO-E rota sırası düzeltildi. Başlangıç lifespan yapısına taşındı; sağlayıcı hatalarında gizli yanıt içeriği yerine hata türü loglanıyor.
- `gateway/metrics.py`, optimizer, scheduler ve SQLite aynı snapshot/metrikleri kullanıyor. `metric_version=2`; eski kayıtlar korunuyor, eski ve başarısız kayıtlar yeni başarı metriklerine katılmıyor. Round-robin güncellemesi `BEGIN IMMEDIATE` kullanıyor; SQLite hataları gizlenmiyor.
- Erteleme yalnız öneridir; iş karar bölgesinde hemen bir kez çağrılır. UTC öneri zamanı, kaynak, backend, enerji varsayımı ve SLA sonucu raporlanır. Gerçek OpenWhisk hata/bozuk yanıt/zaman aşımında simülasyona düşmez; parametre dosyasıyla kullanıcı verisini aktarır ve toplam çağrı süresini döndürür.
- Dashboard tek HTML kaynağına taşındı; CSS/JS `static/` altında. Dinamik içerik DOM/textContent ile gösteriliyor. Metrikler API'den alınıyor; yöntem seçimi, öneri, backend, MAE, panel bazlı hata kontrolü, zaman aşımı ve çakışmayan yenileme eklendi. Mobil CSS ve erişilebilir düğmeler uygulandı fakat tarayıcıda henüz doğrulanmadı.
- CSV geçmişi tekrarlanan örnek profil olarak UTC saatleriyle üretiliyor; gelecek saatler son gözleme bağlı. ARIMA gürültüsü ve iç içe değerlendirme kaldırıldı; ikinci fark iki kez geri toplanıyor. Prophet aynı eğitim/değerlendirme ayarlarını kullanıyor; yanlış 24 günlük bileşen kaldırıldı, changepoint ve sıfır MAE karşılaştırması düzeltildi. Yedek model `exponential_smoothing`. Nokta tahminleri üretiliyor; belirsizlik aralıkları hesaplanmadığı için `lower_bound`/`upper_bound` alanları `null`.
- Doğrulama: mevcut Python 3.12.10 ile `python -m unittest discover -s tests -v`: **30 test geçti**. Testler geçici veritabanı kullanır. `node --check static/dashboard.js` geçti. Gerçek kurulu Prophet ile IE tahmini çalıştı ve `model_used=prophet`, `fallback_reason=null` döndü. Bu, temiz ortam kurulumunun doğrulandığı anlamına gelmez.
- Tarayıcı kabul kontrolü denenmiş ancak araçlar kullanılamamıştır: browser sağlayıcısı bulunamadı; Windows kontrolü `native pipe unavailable` döndürdü. HTML içeren action'ın tarayıcıda düz metin görünmesi, mobil görünüm ve yenileme hata senaryoları açık kabul maddeleridir. Test sunucusu başlatılmadı, mevcut uygulama veritabanı değiştirilmedi.
- Sıradaki işler: ENTSO-E XML birim/zaman/üretim ayrımı; ortak scheduler kullanan tekrarlanabilir deneyler ve tek rapor şeması; GitHub paketi, temiz kurulum/CI ve tarayıcı kabul doğrulaması. Eski deney/akademik iddialar henüz güncellenmedi.

### 15 Eylül 2026 — ENTSO-E ve deney hattı

- ENTSO-E ayrıştırıcısı üretim/tüketim yönünü ayırıyor; MAW değerlerini dönem süresiyle MWh'ye çeviriyor. A01 tam aralıkları ve A03 basamaklı güç serileri destekleniyor. Eksik noktalar, uyumsuz zaman kapsamı, çakışma, bilinmeyen birim/tip ve geçersiz miktarlar tahmin diye raporlanmıyor. Karbon hesabında gram dönüşümü düzeltildi; sonuç üretim karışımı tahmini olarak etiketlendi. Test XML'leri sentetik ve kaynak açıklamaları `tests/fixtures/README.md` içinde.
- Deneyler `route_request` ve uygulamayla ortak `simulate_latency` fonksiyonunu kullanıyor. Snapshot, UTC saat ve aynı rastgele sayılar stratejiler arasında paylaşılıyor. Gerçek backend, ağ ve SQLite erişimi yapılmıyor; bu sınırlar testlerde hata fırlatan mock'larla doğrulandı.
- Runner `--seed`, `--samples`, `--output-dir` kabul ediyor; yalnız şema 3 ana JSON'unu yazıyor. Rapor betiği bundan HTML ve tek şemalı makale özetini, grafik betiği aynı JSON'dan üç PNG'yi üretiyor. Rapor metinleri HTML için kaçışlanıyor. Sabit/farksız eşleştirilmiş serilerin tanımsız test sonuçları açıklamalı `null` oluyor.
- `experiments/output/` altında seed 42, 50 örnek ve toplam 450 simülasyon çağrısı üretildi. Gerçek kurulu Prophet dahil ikinci tam çalıştırma ilk JSON ile birebir eşleşti. Rapor ve üç grafik komutu başarıyla çalıştı; scheduler karşılaştırma grafiği görsel olarak kontrol edildi. Diğer grafiklerin ve HTML raporunun görsel kabulü henüz yapılmadı.
- `python -m unittest discover -s tests -q`: **39 test geçti**. Ana uygulama veritabanı değiştirilmedi. Eski `experiments/results/` dosyaları tarihsel olarak işaretlendi; eski akademik iddiaların ve ana README'nin güncellenmesi hâlâ gerekli.
- Sıradaki işler: yayın paketi/bağımlılık ayrımı, README ve akademik taslak, OpenWhisk dağıtım betiği, Ruff/CI/temiz ortam doğrulaması, Git hazırlığı ve açık görsel kabul testleri.

### 16 Eylül 2026 — Yayın paketi ve temiz Windows doğrulaması

- Temel, deney, Prophet ve geliştirme bağımlılıkları ayrıldı. `requirements-core.lock` ve `requirements-full.lock`, birbirinden ayrı temiz Python 3.12.10 ortamlarında doğrulanan paketlerden üretildi. Gömülü Python'da `venv` bulunmadığından ayrı interpreter/standart kitaplık ve boş site-packages dizinleri kullanıldı; eski kurulu paketler bu ortamlara eklenmedi. Ortamlar `.verification/` altında ve Git dışında.
- Temel temiz ortam: 35 test geçti, SciPy gerektiren 4 deney testi atlandı. Prophet/SciPy bulunmadığı ayrıca doğrulandı. Gerçek HTTP sunucusuyla lifespan, route, SQLite kayıtları, dashboard ve statik dosya smoke testi geçti. Test sunucusu kapatıldı; geçici veritabanı kullanıldı.
- Tam temiz ortam: son eklenen deployment testleri dahil **43 test geçti**. Gerçek Prophet tahmini yedeğe düşmeden çalıştı. Ruff kontrolü geçti; kullanılmayan importlar ve eski davranışı anlatan modül açıklamaları temizlendi.
- OpenWhisk dağıtımı tek worker dosyasını kullanıyor, anahtarı ortamdan alıyor, yalnız loopback portu açıyor. Var olan container'ı silmez ve global CLI ayarı yazmaz. Mock komutlarla çalışan container'ı kullanma, durmuş container'da hata, hazır olmayan API'de hata ve yeni container'ın loopback bağlantısı doğrulandı. Bash sözdizimi kontrolü geçti; gerçek OpenWhisk deployment yapılmadı.
- İngilizce README, Türkçe rehber ve akademik taslak güncellendi. Yazarlar korundu, öğrenci numaralı iletişim satırı çıkarıldı. Taslak şema-3 çıktılarından güncel tabloları kullanıyor; eski temporal-shifting ve “Prophet her yerde daha iyi” iddiaları kaldırıldı. README'nin gerçek dashboard ekran görüntüsü hâlâ eksik.
- `.github/workflows/ci.yml` Windows/Linux Python 3.12 matrisiyle temel kurulum, smoke, tam testler, Ruff ve deney artefaktlarını kapsıyor. Uzak depo oluşturulmadığı için GitHub CI çalışması yok. Yerel Linux doğrulaması da henüz yok: Docker Linux engine pipe mevcut değil. Bu, test başarısı olarak sayılmıyor.
- Yerel Git deposu `main` dalıyla oluşturuldu ve yayın içeriği staging alanına alındı. Uzak bağlantı veya push yok. Ignore kuralları yerel Python, Docker ayarları, veritabanı/WAL, log, `.env`, önbellek ve eski deney çıktılarını dışlıyor. Staged içerikte önceki sabit anahtarlar ve dört öğrenci numarası için tarama sonuçsuz; ignore edilmesi gereken takipli dosya bulunmadı. Lisans eklenmedi.
- Tarayıcı araç envanteri yeniden kontrol edildi: `apps=[]`, `browsers=[]`. Bu nedenle gerçek HTML/action, panel hata/yenileme, mobil görünüm, screenshot ve HTML rapor görsel kabulü açık. Linux testi, görsel kabul ve tüm maddelerin son kapsam denetimi tamamlanmadan hedef bitmiş sayılmayacak.

### 16 Eylül 2026 — Linux yayın doğrulaması

- Docker Desktop Linux motoru başlatıldı ve `docker compose -f compose.verify.yml run --rm verify` başarıyla tamamlandı. Salt okunur kaynak mount'ı üzerinden disposable Python 3.12-slim kopyası oluşturuldu.
- Linux core kurulumu, **46 test (4 opsiyonel deney testi atlandı)**, gerçek HTTP smoke, tam bağımlılık kurulumu, `pip check`, **46 tam test**, Ruff, gerçek Prophet tahmini, 8 örnekli deney, rapor ve üç grafik üretimi geçti. Container sonlandı; kalıcı servis bırakılmadı.
- `compose.verify.yml` ve `scripts/verify_linux.py` tekrar edilebilir Linux kontrolü sağlar. CI workflow'unda aynı temel ve tam kontroller tanımlıdır; uzak GitHub Actions çalıştırması yapılmadı.

### 16 Eylül 2026 — Dashboard ve rapor görsel kabulü

- Geçici Playwright + headless Chromium ile gerçek Uvicorn HTTP sunucusu üzerinden masaüstü (1440px) ve mobil (390px) dashboard açıldı. CSS/JS statik asset'leri, API verileri ve forecast metadata'sı görünür bulundu.
- Mobil viewport'ta `scrollWidth > clientWidth` false; tüm seçim düğmeleri `aria-pressed` taşıyor. HTML içeren `<img src=x onerror=alert(1)>` action, kayıt tablosunda düz metin göründü; hiçbir `td` veya sonuç kutusu HTML node'u içermedi.
- Dashboard'da gerçek route çağrısı ve SQLite metrikleri görüntülendi. Üretilen dashboard masaüstü ekran görüntüsü `experiments/output/dashboard-desktop.png` olarak README'ye eklendi; mobil kanıt `dashboard-mobile.png` olarak saklandı. Generated `phase2_report.html` de headless tarayıcıda açılıp metin içeriği doğrulandı ve `phase2-report.png` kaydedildi.
- Headless tarayıcı testi geçici `.verification/` paketini kullandı; Chromium ve Node paketleri yayın içeriğine alınmadı. Test Uvicorn süreci kapatıldı ve geçici veritabanı kullanıldı.

### 16 Eylül 2026 — Son kapsam denetimi

- `rg '\- \[ \]' IYILESTIRME_PLANI.md` sonucu boş: plandaki tüm uygulanabilir maddeler tamamlandı.
- Son doğrulamalar: Windows tam ortamında 43 test, Linux tam container'ında 46 test, Ruff, gerçek HTTP smoke, gerçek Prophet, deney/rapor/grafik üretimi ve headless Chromium masaüstü/mobil/rapor kabulü geçti.
- Uzak depo oluşturma/push, hosted GitHub Actions çalıştırması, gerçek OpenWhisk deployment'ı ve bağlı tarayıcı sağlayıcısı gerektiren etkileşimli oturum kapsam dışı bırakıldı; bunlar sonuçların doğrulanması için gerekli değildi ve kullanıcı adına dış sistem değişikliği yapılmadı.
- Proje hedefi bu planın tanımladığı yerel, anahtarsız araştırma demosu ve yayın paketi için tamamlanmıştır.
