# NLQ Chatbot — Doğal Dil ile Veritabanı Sorgulama

Kullanıcının doğal dilde (Türkçe) sorduğu soruları SQL sorgusuna çeviren,
bir MSSQL veritabanı üzerinde çalıştıran ve sonucu yine doğal dilde
özetleyen bir Streamlit chatbot'u. İki farklı LLM sağlayıcısını
(bulut tabanlı Google Gemini ve yerel/self-hosted bir Ollama modeli)
karşılaştırmalı olarak destekler.

## Özellikler

- **Doğal dil → SQL**: Kullanıcı sorusunu, veritabanı şemasını kullanarak
  güvenli bir `SELECT`/`WITH` sorgusuna çevirir.
- **SQL güvenlik katmanı** (`sql_guard.py`): yazma komutlarını (INSERT/
  UPDATE/DELETE/DROP vb.) engeller, tekrar döngüsüne giren veya boş cevap
  döndüren model çıktılarını tespit eder.
- **Niyet sınıflandırma**: bir sorunun salt bilgi isteği mi, yazma isteği
  mi, karışık mı, yoksa hipotetik/varsayımsal bir senaryo mu olduğunu
  ayırt eder.
- **360° profil görünümü**: "X hakkında her şeyi anlat" gibi sorularda
  müşteri/çalışan için birden fazla tabloyu birleştiren özel bir görünüm
  sunar.
- **Dinamik şema keşfi** (`schema_introspector.py`): veritabanı şemasını
  her açılışta otomatik okur, düşük çeşitlilikli (enum benzeri) kolonların
  gerçek değerlerini de modele verir — yeni tablo/kolon eklendiğinde kod
  değişikliği gerekmez.
- **İki LLM sağlayıcısı arasında geçiş**: Gemini API ya da yerel bir
  Ollama modeli (`qwen2.5-coder` vb.), arayüzden tek tıkla seçilebilir.
- **Excel/PDF olarak dışa aktarma**, favori soru önbellekleme, otomatik
  grafik üretimi.

## Mimari

Repository pattern + dependency inversion ile katmanlı bir yapı:

```
app.py                  → Streamlit arayüzü
nlq_service.py           → Orkestrasyon: soru → SQL → sonuç → özet
db_repository.py         → SQLAlchemy ile veritabanı erişimi (connection pool)
llm_client.py             → LLM sağlayıcıları için soyut arayüz (Gemini / yerel)
schema_introspector.py   → Şemayı runtime'da keşfeder
sql_guard.py              → Üretilen SQL'i çalıştırmadan önce doğrular
profile_repository.py    → 360° müşteri/çalışan profili sorguları
favorites_repository.py  → En çok sorulan soruları önbellekler
export_service.py         → Excel/PDF dışa aktarma
models.py                 → Veri modelleri (dataclass)
```

## Kurulum

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` dosyasını kendi veritabanı ve API bilgilerinizle doldurun:

```
DB_SERVER=...
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
GEMINI_API_KEY=...
LOCAL_LLM_BASE_URL=...      # yerel modeli kullanmayacaksanız boş bırakılabilir
LOCAL_LLM_MODEL_NAME=...
```

## Çalıştırma

```bash
python -m streamlit run app.py
```

## Not

Bu depo, veritabanı şeması ve örnek veriler bakımından demo amaçlı,
gerçek bir şirkete ait olmayan kurgusal bir veri seti üzerine kuruludur.
