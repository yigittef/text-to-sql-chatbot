"""Uygulama genelinde kullanılan veri modelleri."""
from dataclasses import dataclass
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class QueryResult:
    columns: Sequence[str]
    rows: Sequence[Sequence[Any]]

    def is_empty(self) -> bool:
        return len(self.rows) == 0


@dataclass(frozen=True)
class CustomerProfile:
    """360 derece müşteri görünümü için toplanan veriler."""
    customer_row: Sequence[Any]
    orders: Sequence[Sequence[Any]]
    top_products: Sequence[Sequence[Any]]
    account_card: Optional[Sequence[Any]]
    shipments: Sequence[Sequence[Any]]


@dataclass(frozen=True)
class EmployeeProfile:
    """Çalışan özet görünümü için toplanan veriler."""
    employee_row: Sequence[Any]
    izin_talepleri: Sequence[Sequence[Any]]
    performans_kayitlari: Sequence[Sequence[Any]]
    tamamlanan_egitimler: Sequence[Sequence[Any]]


@dataclass
class ChatEntry:
    """Sohbet geçmişindeki tek bir soru-cevap kaydı.

    Chatbot yalnızca bilgi okur — bu yüzden bir "onay bekliyor" alanı yok.
    Her kayıt: SELECT sonucu, 360 profil, "bilgi yok" mesajı, ya da hata.

    exclude_from_context: Bu cevap (yazma reddi, bozuk/tekrar cevabı
    yüzünden başarısız deneme vb.) gelecekteki sorulara BAĞLAM olarak
    ASLA gönderilmemeli — çünkü model bu tür "başarısız/reddedilmiş"
    örnekleri görünce, alakasız sonraki sorularda da aynı kalıba
    (yanlışlıkla reddetme/BILGI_YOK) kaymaya eğilimli oluyor.
    """
    question: str
    answer: Optional[str] = None
    generated_sql: Optional[str] = None
    query_result: Optional[QueryResult] = None
    no_relevant_data: bool = False
    error_message: Optional[str] = None
    profile: Optional[CustomerProfile] = None
    employee_profile: Optional[EmployeeProfile] = None
    llm_provider: Optional[str] = None
    exclude_from_context: bool = False

    @property
    def has_error(self) -> bool:
        return self.error_message is not None