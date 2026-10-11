# WN Download Manager (Windows Sürümü)

**WN Download Manager**, [Mesut Çevik](https://github.com/)'in macOS için geliştirdiği **MC Download Manager** adlı indirme yöneticisini baz alarak, onun Windows sürümü olarak geliştirdiğim güçlü ve açık kaynaklı bir masaüstü uygulamasıdır. Orijinal projede olmayan bir şekilde indirilen videoları altyazıyla indirme özelliği eklemiş bulunmakta. Orijinal projenin çok parçalı ve yüksek hızlı indirme deneyimini modern Python, **ttkbootstrap** ve Windows ekosistemiyle buluşturur.

Internet Download Manager (IDM) ve MC Download Manager gibi profesyonel araçların gelişmiş özelliklerini Türkçe arayüz ve modern karanlık tema ile sunar.

> Bu proje, Mesut Çevik'in macOS için geliştirdiği MC Download Manager'dan ilham almıştır ve Windows kullanıcıları için yeniden geliştirilmiştir. Kullanım kolaylığı adına ek özellikler eklenmiştir

---

## 🚀 Temel Özellikler

- **Çok Parçalı (Multi-Segment) Paralel İndirme**:
  - HTTP Range istekleri ile dosyayı 1 ila 32 parçaya bölerek maksimum bant genişliği kullanımı.
  - Parçaların dinamik olarak birleştirilmesi ve dosya bütünlüğü (Content-Length) kontrolü.
- **Duraklatma / Devam Etme (Pause & Resume)**:
  - İndirmeleri dilediğiniz an duraklatın ve kaldığı bayttan devam ettirin.
  - Olası elektrik kesintisi veya uygulama kapanmalarında SQLite üzerinde indirme durumu otomatik olarak korunur.
- **Video & Medya İndirici (yt-dlp Entegrasyonu)**:
  - YouTube, Twitter, Instagram, TikTok, Vimeo ve yüzlerce siteden doğrudan video ve ses indirme.
  - 4K (2160p), 1080p, 720p, 480p ve Yalnızca Ses (MP3) format seçenekleri.
  - FFmpeg ile otomatik ses ve görüntü birleştirme desteği.
- **Altyazı İndirme (2 Tür)**:
  - **Manuel (Yüklenen) Altyazılar**: Video sahibi tarafından yüklenmiş resmi altyazıları indirir.
  - **Otomatik Oluşturulan Altyazılar**: Platformun otomatik olarak ürettiği altyazıları indirir.
- **Otomatik Pano (Clipboard) İzleme**:
  - Kopyalanan bağlantıları otomatik analiz eder, indirilebilir bir dosya veya video algılandığında hızlı indirme penceresini açar.
- **Modern ve Şık Arayüz (ttkbootstrap - Darkly Teması)**:
  - Kategorilere göre filtreleme: *Tümü, Belgeler, Resimler, Müzik, Video, Arşivler, Programlar, Diğer*.
  - Her indirme için canlı hız, kalan süre (ETA) ve yüzde göstergeleri.
  - Parça detay penceresi ile segmentlerin durumunu görsel olarak inceleme.
- **Sistem Tepsisi (System Tray) Entegrasyonu**:
  - Arka planda sessiz çalışma, sağ tık menüsü ile hızlı erişim.
- **Masaüstü Bildirimleri**:
  - İndirme tamamlandığında Windows masaüstü bildirimi.
- **Özel Başlık & Hız Sınırı Desteği**:
  - Özel User-Agent, Referer ve çerezler ile indirme.
  - Ağ kullanımını dengelemek için KB/s cinsinden hız limiti belirleme.

---

## 🛠 Kurulum

### 1. Gereksinimler
- Python 3.9 veya daha yeni bir sürüm (Windows 10 / 11)
- [İsteğe Bağlı] Video birleştirme için sistemde `ffmpeg` bulunması önerilir.

### 2. Bağımlılıkların Yüklenmesi
**Öncelikle bilgisayarınızda Python'un yüklü olduğundan emin olun.** Kontrol etmek için PowerShell veya CMD'de şu komutu çalıştırın:

```powershell
python --version
```

Bir sürüm numarası (örn. `Python 3.11.5`) görüyorsanız Python yüklüdür. Hata alıyorsanız [python.org](https://www.python.org/downloads/) adresinden indirip kurun (kurulum sırasında **"Add Python to PATH"** seçeneğini işaretlemeyi unutmayın).

Python'un yüklü olduğundan emin olduktan sonra, komut istemcisinde (PowerShell veya CMD) proje dizininde şu komutu çalıştırın:

```powershell
pip install -r requirements.txt
```

---

## 💻 Kullanım

Uygulamayı başlatmak için önce komut istemcisinde (PowerShell veya CMD) projenin bulunduğu klasöre gidin, ardından uygulamayı çalıştırın:

```powershell
cd C:\Kullanici\Yolu\wn-download-manager-win
python main.py
```

> `C:\Kullanici\Yolu\wn-download-manager-win` kısmını, projeyi kendi bilgisayarınızda kaydettiğiniz klasörün yolu ile değiştirin. Örneğin proje Masaüstünüzdeyse: `cd C:\Users\KullaniciAdi\Desktop\wn-download-manager-win`

### Kısayol Tuşları:
- **Ctrl + N**: Yeni İndirme Ekle penceresini açar.
- **Delete**: Seçili indirmeyi kaldırır.
- **F5**: İndirme listesini yeniler.
- **Çift Tıklama**: Seçili indirmenin parça detaylarını ve ilerlemesini gösterir.
- **Sağ Tıklama**: İndirmeyi duraklatma, devam ettirme, klasörde açma veya dosyayı silme menüsü.

---

## 📂 Proje Yapısı

```
wn-download-manager-win/
│
├── main.py                  # Uygulama giriş noktası, tekil oturum ve sistem tepsisi
├── download_engine.py       # Çok kanallı paralel Range indirme motoru
├── video_downloader.py      # yt-dlp tabanlı video, ses ve altyazı indirme yöneticisi
├── gui.py                   # ttkbootstrap arayüzü ve iletişim pencereleri
├── clipboard_monitor.py     # Pano dinleme ve otomatik bağlantı yakalayıcı
├── database.py              # SQLite veri tabanı katmanı
├── utils.py                 # Yardımcı fonksiyonlar ve yapılandırma
├── requirements.txt         # Gerekli Python kütüphaneleri
├── README.md                # Proje dokümantasyonu (Türkçe)
└── assets/
    └── icon.py              # Uygulama simgesi ve üretici fonksiyonlar
```

---

## ⚙️ Yapılandırma ve Veri Kaydı

Uygulama ayarları ve indirme geçmişi kullanıcının ev dizinindeki `.mc_download_manager` klasöründe tutulur:
- **Yapılandırma Dosyası**: `~/.mc_download_manager/config.json`
- **Veri Tabanı**: `~/.mc_download_manager/downloads.db`
- **Uygulama Günlüğü**: `~/.mc_download_manager/mcdm.log`

---

## 📄 Lisans
Bu proje MIT lisansı altında özgürce geliştirilebilir ve dağıtılabilir.
