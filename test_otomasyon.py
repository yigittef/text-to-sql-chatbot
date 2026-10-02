"""Belirlenen soru listesini hem Gemini hem de yerel modele otomatik sorar,
cevap + SQL + süre + hata bilgisini test_sonuclari.csv dosyasına yazar.
Her API çağrısından sonra 10 saniye bekler.

Bu script iki LLM sağlayıcısını (bulut tabanlı Gemini ve yerel Ollama
modeli) aynı soru seti üzerinden karşılaştırmalı olarak test etmek için
yazıldı — hangi modelin hangi soru tipinde (çok tablolu JOIN, toplama,
göreceli eşik vb.) daha doğru SQL ürettiğini ölçmek amacıyla kullanıldı.

Kullanım: proje klasöründe terminalde:
    python test_otomasyon.py

NOT: Aşağıdaki SORULAR listesi boş bırakıldı — kendi veritabanı şemanıza
uygun örnek sorularla doldurup kullanabilirsiniz. Örnek:
    "En pahalı 3 ürün hangileri?",
    "Toplam kaç müşterimiz var?",
    "Hangi departmanda en çok çalışan var?",
"""
import csv
import os
import time

from dotenv import load_dotenv

from config import DatabaseConfig, LocalLLMConfig, LLMConfig
from db_repository import DatabaseRepository
from llm_client import GeminiLLMClient, LocalLLMClient
from logging_llm_client import LoggingLLMClient
from nlq_service import NaturalLanguageQueryService
from profile_repository import ProfileRepository
from schema_introspector import SchemaIntrospector

load_dotenv()

# ---- Sirayla sorulacak sorular (kendi senaryolariniza gore doldurun) ----
SORULAR = [
    # "En pahalı 3 ürün hangileri?",
    # "Toplam kaç müşterimiz var?",
]
OUTPUT_DOSYA = "test_sonuclari.csv"
CAGRI_ARASI_BEKLEME_SN = 10


def build_service(provider: str) -> NaturalLanguageQueryService:
    db_repository = DatabaseRepository(DatabaseConfig.from_env())
    schema_introspector = SchemaIntrospector(db_repository.engine)
    profile_repository = ProfileRepository(db_repository)
    if provider == "gemini":
        raw_client = GeminiLLMClient(LLMConfig.from_env())
    else:
        raw_client = LocalLLMClient(LocalLLMConfig.from_env())
    llm_client = LoggingLLMClient(raw_client)
    return NaturalLanguageQueryService(
        llm_client=llm_client,
        db_repository=db_repository,
        schema_introspector=schema_introspector,
        profile_repository=profile_repository,
    )


def main() -> None:
    if not SORULAR:
        print("SORULAR listesi boş. Dosyanın başındaki örnek sorulardan "
              "birkaçını açıp kendi şemanıza göre düzenleyin.")
        return

    dosya_var_mi = os.path.exists(OUTPUT_DOSYA)
    toplam_cagri = len(SORULAR) * 2
    yapilan_cagri = 0

    with open(OUTPUT_DOSYA, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not dosya_var_mi:
            writer.writerow(["soru", "saglayici", "cevap", "sql", "sure_saniye", "hata"])

        for soru in SORULAR:
            for provider in ("gemini", "local"):
                yapilan_cagri += 1
                print(f"\n>>> [{yapilan_cagri}/{toplam_cagri}] [{provider}] {soru}")
                service = build_service(provider)
                baslangic = time.perf_counter()
                try:
                    entry = service.answer(soru, history=())
                    gecen = time.perf_counter() - baslangic
                    if entry.has_error:
                        writer.writerow([soru, provider, "", entry.generated_sql or "", f"{gecen:.2f}", entry.error_message])
                        print(f"    HATA: {entry.error_message}")
                    else:
                        writer.writerow([soru, provider, entry.answer or "", entry.generated_sql or "", f"{gecen:.2f}", ""])
                        print(f"    OK ({gecen:.2f} sn): {(entry.answer or '')[:80]}")
                except Exception as exc:
                    gecen = time.perf_counter() - baslangic
                    writer.writerow([soru, provider, "", "", f"{gecen:.2f}", str(exc)])
                    print(f"    BEKLENMEYEN HATA: {exc}")
                f.flush()

                if yapilan_cagri < toplam_cagri:
                    print(f"    {CAGRI_ARASI_BEKLEME_SN} saniye bekleniyor...")
                    time.sleep(CAGRI_ARASI_BEKLEME_SN)

    print(f"\nTamamlandı. Sonuçlar '{OUTPUT_DOSYA}' dosyasına eklendi.")


if __name__ == "__main__":
    main()
