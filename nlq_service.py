"""Doğal dil sorusunu SQL'e çevirip çalıştıran orkestrasyon katmanı."""
import difflib
import logging
import re
from typing import Dict, List, Optional, Sequence

from db_repository import DatabaseRepository
from llm_client import LLMClient
from models import ChatEntry, QueryResult
from profile_repository import ProfileRepository
from schema_introspector import SchemaIntrospector
from sql_guard import EmptySqlError, SqlRepetitionLoopError, UnsafeSqlError, sanitize_generated_sql

_trace_logger = logging.getLogger("llm_trace")

_MAX_CONTEXT_TURNS = 5
_MAX_ANSWER_CHARS_IN_CONTEXT = 300
_MAX_SQL_CHARS_IN_CONTEXT = 500
_MAX_SQL_FIX_ATTEMPTS = 2

_NO_DATA_SENTINEL = "BILGI_YOK"
_NO_DATA_MESSAGE = (
    "🤔 Bu soruyu cevaplayabilmem için gereken bilgi veritabanımızda "
    "bulunmuyor. Farklı bir soru sormak ister misiniz?"
)
_WRITE_REFUSED_MESSAGE = (
    "🔒 Bu chatbot yalnızca veri sağlayabilir; veri ekleme, silme veya "
    "değiştirme yapamaz. Bu işlemi SSMS üzerinden yapmanız gerekiyor."
)
_MIXED_QUESTION_NOTE = (
    "\n\n🔒 Not: Sorunuzun bir kısmı veri ekleme/silme/değiştirme talebi "
    "içeriyordu. Bu chatbot yalnızca veri sağlayabilir; bu işlemi SSMS "
    "üzerinden yapmanız gerekiyor."
)
_GENERIC_RETRY_FAILED_MESSAGE = (
    "🤔 Sorunuz işlenirken tekrar eden bir hatayla karşılaşıldı "
    "(muhtemelen model bir döngüye kilitlendi). Lütfen soruyu daha "
    "basit bir şekilde ya da farklı ifadelerle tekrar sorun."
)

_ONLY_WRITE = "SADECE_YAZMA"
_MIXED = "KARISIK"
_HYPOTHETICAL = "HIPOTETIK"
_INFO = "BILGI"

_INTENT_TEMPLATE = """Kullanıcının sorusunu şu 4 kategoriden birine ayır:

SADECE_YAZMA = soru TAMAMEN ve SADECE veritabanında gerçek bir değişiklik \
(ekleme/güncelleme/silme) istiyor, başka hiçbir bilgi/analiz talebi yok.

KARISIK = soru hem bilgi/analiz/listeleme istiyor HEM DE ayrıca, ek olarak, \
gerçek bir ekleme/güncelleme/silme isteği de içeriyor.

HIPOTETIK = koşullu/varsayımsal sorular ('olsaydı', 'olurdu', 'silseydik' \
gibi ifadeler içerir, gerçek işlem değildir).

BILGI = sadece bilgi, analiz, listeleme sorusu, hiçbir yazma isteği yok.

SADECE şu dört kelimeden birini yaz: SADECE_YAZMA, KARISIK, HIPOTETIK, BILGI.

Soru: {question}
"""

_PROFILE_DETECTION_TEMPLATE = """Kullanıcının sorusu bir müşterinin TAM \
PROFİLİNİ/ÖZETİNİ istiyor mu (ör. 'X hakkında her şeyi anlat', 'X'in \
özetini çıkar')? Evetse SADECE müşterinin adını soyadını yaz, başka \
hiçbir şey yazma. Değilse SADECE 'HAYIR' yaz.

Soru: {question}
"""

_SQL_GENERATION_TEMPLATE = """Sen bir SQL Server uzmanısın. Aşağıdaki veritabanı şemasına göre, \
kullanıcının sorusundaki BİLGİ/ANALİZ kısmını cevaplayacak TEK BİR SELECT \
(veya WITH ile başlayan CTE) sorgusu yaz.

Kurallar:
- SQL Server'da LIMIT yok. Sonucu belirli sayıda satırla sınırlamak \
gerekiyorsa (ör. 'en çok', 'ilk 3') SELECT'in başına TOP (N) ekle: \
SELECT TOP (N) .... Soru 'tüm', 'her' gibi kayıtların tamamını istiyorsa \
TOP ekleme.
- 'Kaç GÜN' sorulduğunda satır SAYISINI (COUNT) değil, gerçek gün farkını \
hesapla: DATEDIFF(DAY, baslangic_tarihi, bitis_tarihi) + 1, birden fazla \
kayıt varsa SUM ile topla. 'Kaç KİŞİ/KAYIT SAHİBİ' sorulduğunda \
COUNT(DISTINCT ilgili_id) kullan. 'Kaç TALEP/KAYIT/SATIR' sorulduğunda \
COUNT(*) kullan. Bu üçü birbirinin yerine ASLA geçmez.
- Bir tabloda 'durum' gibi bir kolon YOKSA ama başlangıç/bitiş tarihi \
kolonları VARSA, 'aktif' kavramını GETDATE()'in bu tarih aralığında olup \
olmadığını kontrol ederek hesapla — kolonu uydurma.
- SUM/COUNT gibi bir toplama fonksiyonu kullanmadan önce, JOIN'lerin \
satır sayısını YAPAY OLARAK ÇOĞALTMADIĞINDAN emin ol: cevap için \
gerekmeyen hiçbir tabloyu sorguya katma, aynı tabloya gerçekten ihtiyaç \
olmadıkça birden fazla kez JOIN yapma.
- Soru 'bu/bunlardan/yukarıdaki/bahsettiğin' gibi ifadelerle önceki bir \
sonuca atıfta bulunuyorsa, bağlamdaki "O soruda kullanılan SQL filtre \
mantığı" satırındaki WHERE/tarih koşulunu AYNEN kullan.
- Aynı kavramı (ör. bir kişi/nesnenin tarihsel talepleri/hareketleri) \
tutan birden fazla tablo varsa: HANGİ BAŞLANGIÇ/BİTİŞ TARİHİ kolonlarını \
GERÇEKTEN içerdiğine bakarak doğru tabloyu seç — tarih aralığı geçen bir \
soruda, sadece TOPLAM/ÖZET bir sayı tutan (kendi tarih kolonu olmayan) \
bir tabloyu ASLA kullanma; sorunun istediği tarih detayını gerçekten \
taşıyan tabloyu bul.
- Tablo/kolon isimlerini şemadan BİREBİR kopyala — şemada olmayan hiçbir \
tablo/kolon adı uydurma. Şüphedeysen, o kavramı hangi tablonun \
gerçekten içerdiğini şemadaki kolon listesinden kontrol et.
- Sorunun içinde ayrıca bir ekleme/güncelleme/silme isteği de varsa, o \
kısmı TAMAMEN YOK SAY, sadece bilgi/analiz kısmını SELECT ile cevapla.
- Sadece veri OKUMA yap; INSERT/UPDATE/DELETE/CREATE/ALTER/DROP asla yazma.
- 'Kritik/düşük/az' gibi göreceli bir eşik ifadesi (ör. 'kritik stok', \
'düşük bakiye') geçerse ve şemada bunu tanımlayan sabit bir kolon/değer \
yoksa, makul bir eşik varsay (ör. ilgili miktarın en düşük %20'lik \
dilimi) ve bunu SELECT içinde kendin hesapla — asla var olmayan bir eşik \
kolonuna referans verme.
- Kullanıcı varsayımsal/koşullu bir hesaplama isterse, bunu ASLA reddetme \
— SELECT içinde matematiksel/mantıksal olarak hesapla, veriyi değiştirme.
- Soru önceki konuşmaya bir takip sorusuysa bağlamı kullan.
- Karmaşık sorgularda CTE kullanabilirsin ama sadece şemada listelenen \
kolonları kullan.
- BİRDEN FAZLA TABLO JOIN edildiğinde, SEÇTİĞİN HER KOLONU mutlaka tablo \
takma adıyla belirt — asla takma ad olmadan çıplak kolon adı yazma. \
Farklı tablolarda aynı isimde kolon varsa, her birine AS ile farklı bir \
isim ver.
- LEFT JOIN kullanılması gereken durumlarda (ör. 'varsa' ifadesi geçiyorsa) \
INNER JOIN yerine LEFT JOIN kullan.
- Sorunun bilgi/analiz kısmı, şemadaki hiçbir tablo/kolonla mantıksal \
olarak ilişkilendirilemiyorsa, SADECE ve TAM OLARAK şu metni yaz: {no_data_sentinel}

Şema:
{schema}

{context}Soru: {question}
"""

_SQL_FIX_TEMPLATE = """Aşağıdaki SQL Server sorgusu çalıştırılırken hata verdi. \
SADECE düzeltilmiş SELECT/CTE sorgusunu yaz — açıklama, yorum, kod bloğu \
işareti ekleme. GERÇEK BİR SELECT/WITH SORGUSU YAZMAK ZORUNLUSUN — sadece \
yorum satırları (-- ...) yazıp bırakma, bu geçersiz sayılır. Hata \
mesajında BİRDEN FAZLA sorun listeleniyorsa, her birini TEK TEK kontrol \
et ve HEPSİNİ düzelt. Sorguyu KISA ve SADE tut — aynı JOIN bloğunu \
farklı takma adlarla tekrar tekrar ekleme, her tablo bir sorguda SADECE \
1 KEZ geçmeli. AŞAĞIDAKİ OTOMATİK ŞEMA KONTROLÜ VARSA, ORADAKİ BİLGİYİ \
KESİN DOĞRU KABUL ET.

Orijinal soru: {question}

Şema:
{schema}

Hatalı SQL:
{failed_sql}

Veritabanı hatası:
{error_message}
{hint}

Düzeltilmiş SQL:
"""

_ANSWER_SUMMARY_TEMPLATE = """Kullanıcı şunu sordu: {question}
Veritabanından şu sonuç döndü (kolonlar: {columns}):
{rows}
Bu sonucu kullanıcıya sade, anlaşılır bir Türkçe cümleyle özetle. SANA \
VERİLEN SAYI/TARİHLERİ OLDUĞU GİBİ KULLAN — kendi başına yeni bir \
tarih farkı/gün sayısı hesaplaması YAPMA, sonuçta hazır verilmeyen \
hiçbir sayıyı uydurma. Sorunun içinde ayrıca bir ekleme/güncelleme/silme \
isteği varsa ona hiç değinme. Bu bir hipotetik/varsayımsal hesaplamaysa, \
gerçek bir işlem yapılmış gibi konuşma — bunun yerine 'bu senaryoda...' \
gibi ifadeler kullan.
"""

_PROFILE_SUMMARY_TEMPLATE = """Bir müşteri hakkında bilgi topladık. Bunu \
2-3 cümlelik kısa, özetleyici bir Türkçe paragrafa çevir.
İsim: {name}, Şehir: {city}, Toplam sipariş sayısı: {order_count}, \
En çok aldığı ürünler: {top_products}, Kargo durumları: {shipment_statuses}
"""

_EMPLOYEE_SUMMARY_TEMPLATE = """Bir çalışan hakkında bilgi topladık. Bunu \
2-3 cümlelik kısa, özetleyici bir Türkçe paragrafa çevir. Maaş bilgisi \
verilmediyse maaştan hiç bahsetme.
İsim: {name}, Departman: {department}, Unvan: {title}, İşe Başlama: {hire_date}, \
Şehir: {city}, Toplam izin talebi: {leave_count}, Tamamlanan eğitim sayısı: {training_count}, \
Son performans puanı: {last_performance_score}
"""

_TABLE_REFERENCE_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+(\w+)", re.IGNORECASE)


def _extract_referenced_tables(sql: str, all_columns: Dict[str, List[str]]) -> List[str]:
    found = {match.group(1) for match in _TABLE_REFERENCE_PATTERN.finditer(sql)}
    return [name for name in found if name in all_columns]


def _find_date_range_columns(columns: List[str]):
    start = next((c for c in columns if "baslangic" in c.lower()), None)
    end = next((c for c in columns if "bitis" in c.lower()), None)
    return start, end


def _build_error_hint(error_message: str, all_columns: Dict[str, List[str]], failed_sql: str = "") -> str:
    invalid_columns = set(re.findall(r"Invalid column name '(\w+)'", error_message))
    invalid_objects = set(re.findall(r"Invalid object name '(\w+)'", error_message))
    unbound_identifiers = set(re.findall(r'multi-part identifier "([\w.]+)"', error_message))

    if not invalid_columns and not invalid_objects and not unbound_identifiers:
        return ""

    referenced_tables = _extract_referenced_tables(failed_sql, all_columns) if failed_sql else []

    hint_lines = ["\nOTOMATİK ŞEMA KONTROLÜ:"]
    for col in invalid_columns:
        tables_with_col = sorted(
            table for table, cols in all_columns.items() if col in cols
        )
        tables_missing_col = [t for t in referenced_tables if t not in tables_with_col]

        if tables_with_col:
            line = (
                f"- '{col}' kolonu "
                + (f"{', '.join(tables_missing_col)} tablosunda/tablolarında " if tables_missing_col else "kullandığın tabloda ")
                + f"YOK. Bu isimde bir kolon gerçekte şu tablo(lar)da var: "
                + f"{', '.join(tables_with_col)}. Sorgunu buna göre düzelt "
                + "(sadece o tabloya geçerek, ya da bu kolonu tamamen çıkararak)."
            )
            hint_lines.append(line)
            for t in tables_missing_col:
                cols = all_columns.get(t, [])
                start_col, end_col = _find_date_range_columns(cols)
                if start_col and end_col:
                    hint_lines.append(
                        f"  → ÖNEMLİ: '{t}' tablosunda '{col}' kolonu KESİNLİKLE YOK "
                        f"ama '{start_col}' ve '{end_col}' kolonları VAR. 'Aktif' "
                        f"kavramını 'GETDATE() BETWEEN {t}.{start_col} AND "
                        f"{t}.{end_col}' şeklinde tarih karşılaştırmasıyla hesapla "
                        f"— '{col}' kolonunu bu tabloda kullanmayı bırak."
                    )
        else:
            hint_lines.append(
                f"- '{col}' adında bir kolon veritabanının hiçbir tablosunda yok. "
                f"Bu kolonu tamamen kaldır ya da amacına uygun gerçek bir kolon kullan."
            )
    for obj in invalid_objects:
        close = difflib.get_close_matches(obj, all_columns.keys(), n=3)
        if close:
            hint_lines.append(
                f"- '{obj}' adında bir tablo yok. Muhtemelen kastettiğin: "
                f"{', '.join(close)}."
            )
    for identifier in unbound_identifiers:
        col = identifier.split(".")[-1]
        tables_with_col = sorted(
            table for table, cols in all_columns.items() if col in cols
        )
        hint_lines.append(
            f"- '{identifier}' bağlanamadı — muhtemelen '{identifier.split('.')[0]}' "
            f"takma adı FROM/JOIN listesinde tanımlanmamış, ya da yanlış tabloya "
            f"atanmış. '{col}' kolonu gerçekte şu tablo(lar)da var: "
            f"{', '.join(tables_with_col) if tables_with_col else 'hiçbir tabloda yok'}."
        )
    return "\n".join(hint_lines)


class NaturalLanguageQueryService:
    def __init__(
        self,
        llm_client: LLMClient,
        db_repository: DatabaseRepository,
        schema_introspector: SchemaIntrospector,
        profile_repository: Optional[ProfileRepository] = None,
    ):
        self._llm_client = llm_client
        self._db_repository = db_repository
        self._schema_introspector = schema_introspector
        self._profile_repository = profile_repository or ProfileRepository(db_repository)

    def answer(self, question: str, history: Sequence[ChatEntry] = ()) -> ChatEntry:
        _trace_logger.info(
            "\n🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥\n"
            "🟥 YENİ SORU BAŞLADI: %s\n"
            "🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥",
            question,
        )
        try:
            intent = self._classify_intent(question)

            if intent == _ONLY_WRITE:
                return ChatEntry(question=question, answer=_WRITE_REFUSED_MESSAGE, exclude_from_context=True)

            profile_name = self._detect_profile_request(question)
            if profile_name is not None:
                return self._answer_profile(question, profile_name, intent)

            return self._answer_information(question, history, intent)
        finally:
            _trace_logger.info(
                "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n"
                "🟩 SORU BİTTİ: %s\n"
                "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n",
                question,
            )

    def _classify_intent(self, question: str) -> str:
        raw = self._llm_client.generate(_INTENT_TEMPLATE.format(question=question)).strip().upper()
        if raw in (_ONLY_WRITE, _MIXED, _HYPOTHETICAL, _INFO):
            return raw
        return _INFO

    def _detect_profile_request(self, question: str) -> Optional[str]:
        raw = self._llm_client.generate(_PROFILE_DETECTION_TEMPLATE.format(question=question)).strip()
        # NOT: Model bazen "HAYIR" yerine "Hayır." (nokta/farklı büyük-küçük
        # harfle) yazabiliyor — eskiden TAM eşleşme arandığı için bu durumda
        # "Hayır." kelimesinin kendisi yanlışlıkla aranacak bir isim
        # sanılıyordu. Şimdi noktalama/boşluk temizlenip esnek karşılaştırılıyor.
        normalized = raw.upper().strip(" .!?\"'")
        return None if normalized == "HAYIR" else raw

    def _answer_profile(self, question: str, name: str, intent: str) -> ChatEntry:
        customer_profile = self._profile_repository.find_customer_profile(name)
        employee_profile = self._profile_repository.find_employee_profile(name)

        if customer_profile is None and employee_profile is None:
            return ChatEntry(
                question=question,
                answer=f'🤔 "{name}" adında bir müşteri veya çalışan bulamadım.',
            )

        parts = []
        if customer_profile is not None:
            customer_summary = self._llm_client.generate(_PROFILE_SUMMARY_TEMPLATE.format(
                name=customer_profile.customer_row[1],
                city=customer_profile.customer_row[2],
                order_count=len(customer_profile.orders),
                top_products=[row[0] for row in customer_profile.top_products[:3]],
                shipment_statuses=[row[2] for row in customer_profile.shipments],
            ))
            parts.append(("👤 Müşteri", customer_summary))

        if employee_profile is not None:
            last_score = (
                employee_profile.performans_kayitlari[0][1]
                if employee_profile.performans_kayitlari else "kayıt yok"
            )
            employee_summary = self._llm_client.generate(_EMPLOYEE_SUMMARY_TEMPLATE.format(
                name=employee_profile.employee_row[1],
                department=employee_profile.employee_row[2],
                title=employee_profile.employee_row[3],
                hire_date=employee_profile.employee_row[4],
                city=employee_profile.employee_row[5],
                leave_count=len(employee_profile.izin_talepleri),
                training_count=len(employee_profile.tamamlanan_egitimler),
                last_performance_score=last_score,
            ))
            parts.append(("🧑‍💼 Çalışan", employee_summary))

        if len(parts) > 1:
            header = f'ℹ️ "{name}" adında hem bir müşteri hem bir çalışan bulundu, ikisini de gösteriyorum:\n\n'
            summary = header + "\n\n".join(f"**{label}:**\n{text}" for label, text in parts)
        else:
            summary = parts[0][1]

        if intent == _MIXED:
            summary += _MIXED_QUESTION_NOTE

        return ChatEntry(
            question=question, answer=summary,
            profile=customer_profile, employee_profile=employee_profile,
        )

    def _answer_information(self, question: str, history: Sequence[ChatEntry], intent: str) -> ChatEntry:
        schema = self._schema_introspector.build_schema_description()

        raw_sql = self._generate_raw_sql(question, history, schema)

        if raw_sql.strip().upper() == _NO_DATA_SENTINEL:
            return ChatEntry(question=question, answer=_NO_DATA_MESSAGE, no_relevant_data=True)

        sql: Optional[str] = None
        result = None
        error_message: Optional[str] = None

        for attempt in range(_MAX_SQL_FIX_ATTEMPTS + 1):
            try:
                sql = sanitize_generated_sql(raw_sql)
            except UnsafeSqlError:
                return ChatEntry(question=question, answer=_WRITE_REFUSED_MESSAGE, exclude_from_context=True)
            except (SqlRepetitionLoopError, EmptySqlError) as loop_exc:
                error_message = str(loop_exc)
                sql = None
            else:
                try:
                    result = self._db_repository.run_select_query(sql)
                    error_message = None
                    break
                except Exception as db_exc:
                    error_message = str(db_exc)

            if attempt >= _MAX_SQL_FIX_ATTEMPTS:
                if sql is None:
                    return ChatEntry(question=question, answer=_GENERIC_RETRY_FAILED_MESSAGE, exclude_from_context=True)
                # NOT: Artik RuntimeError firlatip app.py'nin genel "beklenmeyen
                # hata" mesajina dusmuyoruz - bunun yerine uretilen (ama
                # calistirilamayan) SQL'i de ChatEntry icinde tasiyoruz,
                # boylece arayuz kullaniciya "SQL Sorgusunu Goster" secenegini
                # hata mesajinin altinda bile sunabiliyor.
                return ChatEntry(
                    question=question,
                    error_message=f"SQL çalıştırılırken hata oluştu: {error_message}",
                    generated_sql=sql,
                    exclude_from_context=True,
                )

            _trace_logger.info(
                "SQL sorunu (deneme %d/%d), LLM'e gerçek hata + otomatik "
                "şema ipucuyla birlikte yeniden soruluyor.\nSQL:\n%s\nHata: %s",
                attempt + 1, _MAX_SQL_FIX_ATTEMPTS, sql or raw_sql, error_message,
            )
            all_columns = self._schema_introspector.get_all_columns()
            hint = _build_error_hint(error_message or "", all_columns, sql or raw_sql)
            try:
                fixed_raw_sql = self._llm_client.generate(_SQL_FIX_TEMPLATE.format(
                    question=question, schema=schema, failed_sql=sql or raw_sql,
                    error_message=error_message, hint=hint,
                ))
            except Exception as fix_exc:
                _trace_logger.info(
                    "SQL düzeltme denemesi de başarısız oldu: %s", fix_exc,
                )
                return ChatEntry(question=question, answer=_GENERIC_RETRY_FAILED_MESSAGE, exclude_from_context=True)

            if fixed_raw_sql.strip().upper() == _NO_DATA_SENTINEL:
                return ChatEntry(question=question, answer=_NO_DATA_MESSAGE, no_relevant_data=True)
            raw_sql = fixed_raw_sql

        if result is None or sql is None:
            return ChatEntry(question=question, answer=_GENERIC_RETRY_FAILED_MESSAGE, exclude_from_context=True)

        summary = self._summarize(question, result)
        if intent == _MIXED:
            summary += _MIXED_QUESTION_NOTE
        return ChatEntry(question=question, answer=summary, generated_sql=sql, query_result=result)

    def _generate_raw_sql(self, question: str, history: Sequence[ChatEntry], schema: str) -> str:
        prompt = _SQL_GENERATION_TEMPLATE.format(
            schema=schema,
            context=self._build_context(history, question),
            question=question,
            no_data_sentinel=_NO_DATA_SENTINEL,
        )
        return self._llm_client.generate(prompt)

    @staticmethod
    def _build_context(history: Sequence[ChatEntry], current_question: Optional[str] = None) -> str:
        normalized_current = (current_question or "").strip().lower()
        relevant = [
            entry for entry in history
            if not entry.has_error
            and not entry.no_relevant_data
            and not entry.exclude_from_context
            and entry.question.strip().lower() != normalized_current
        ][-_MAX_CONTEXT_TURNS:]
        if not relevant:
            return ""
        lines = ["Önceki konuşma (bağlam):"]
        for entry in relevant:
            lines.append(f"Kullanıcı sordu: {entry.question}")
            if entry.answer:
                answer_text = entry.answer
                if len(answer_text) > _MAX_ANSWER_CHARS_IN_CONTEXT:
                    answer_text = answer_text[:_MAX_ANSWER_CHARS_IN_CONTEXT] + " […kısaltıldı…]"
                lines.append(f"Chatbot cevapladı: {answer_text}")
            if entry.generated_sql:
                sql_text = entry.generated_sql
                if len(sql_text) > _MAX_SQL_CHARS_IN_CONTEXT:
                    sql_text = sql_text[:_MAX_SQL_CHARS_IN_CONTEXT] + " […kısaltıldı…]"
                lines.append(f"(O soruda kullanılan SQL filtre mantığı: {sql_text})")
        lines.append("")
        return "\n".join(lines) + "\n"

    def _summarize(self, question: str, result: QueryResult) -> str:
        prompt = _ANSWER_SUMMARY_TEMPLATE.format(
            question=question, columns=list(result.columns), rows=list(result.rows)
        )
        return self._llm_client.generate(prompt)