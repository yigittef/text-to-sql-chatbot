"""LLM tarafından üretilen SQL sorgularını çalıştırmadan önce doğrular."""
import re
from collections import Counter

_FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "EXEC", "EXECUTE", "MERGE", "GRANT", "REVOKE",
    "BACKUP", "RESTORE", "SHUTDOWN", "KILL", "DBCC", "OPENROWSET",
    "OPENQUERY", "sp_", "xp_",
)

_TABLE_REFERENCE_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+(\w+)", re.IGNORECASE)
_MAX_SAME_TABLE_REFERENCES = 4


class UnsafeSqlError(ValueError):
    """Üretilen SQL güvenli kabul edilmediğinde fırlatılır (yazma isteği,
    birden fazla GERÇEK ifade, SELECT/WITH dışı bir ifade vb.) — bu
    GERÇEK bir reddedilme durumudur, kullanıcıya 'yazma yapamam' mesajı
    gösterilir."""


class SqlRepetitionLoopError(RuntimeError):
    """Model bir tekrar döngüsüne kilitlenip AYNI TABLOYU çok fazla kez
    (farklı takma adlarla) sorguya kattığında fırlatılır. BU BİR YAZMA
    İSTEĞİ DEĞİLDİR — modelin bozulduğunun işaretidir."""


class EmptySqlError(RuntimeError):
    """Model, gerçek bir SELECT/WITH sorgusu yazmadan SADECE açıklama/
    yorum satırları (ör. '-- Hata: ...' cümlesini defalarca tekrarlayan
    bir döngü) döndürdüğünde fırlatılır. BU DA BİR YAZMA İSTEĞİ DEĞİLDİR
    — modelin cevabı eksik/bozuk üretmesidir, düzeltme döngüsünde tekrar
    denenmeli, doğrudan 'yazma yapamam' mesajına ÇEVRİLMEMELİ."""


def sanitize_generated_sql(raw_sql: str) -> str:
    sql = _strip_code_fences(raw_sql)
    sql = _truncate_after_terminal_semicolon(sql)

    if not sql:
        raise UnsafeSqlError("Model boş bir SQL sorgusu döndürdü.")
    if ";" in sql:
        raise UnsafeSqlError("Birden fazla SQL ifadesi tespit edildi.")

    lines = [line.strip() for line in sql.split("\n") if line.strip()]
    if lines and all(line.startswith("--") for line in lines):
        raise EmptySqlError(
            "Model sadece yorum/açıklama satırları döndürdü, gerçek bir "
            "SELECT/WITH sorgusu hiç yazmadı."
        )

    if not re.match(r"^(\s*--[^\n]*\n)*\s*(SELECT|WITH)\b", sql, flags=re.IGNORECASE):
        raise UnsafeSqlError("Yalnızca SELECT/CTE sorgularına izin verilir.")

    upper_sql = sql.upper()
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper_sql):
            raise UnsafeSqlError(f"Güvenlik nedeniyle yasaklı anahtar kelime tespit edildi: {keyword}")

    _check_for_repetition_loop(sql)

    return sql


def _truncate_after_terminal_semicolon(sql: str) -> str:
    """Model bazen TEK bir SELECT/CTE ifadesinin sonuna noktalı virgül
    koyup ardından açıklayıcı yorum satırları (-- ...) ekliyor — bu
    GÜVENLİ bir yazım alışkanlığıdır, ikinci bir SQL ifadesi DEĞİLDİR."""
    if ";" not in sql:
        return sql
    first_semicolon = sql.index(";")
    before = sql[:first_semicolon]
    after = sql[first_semicolon + 1:]
    after_lines = [line.strip() for line in after.split("\n") if line.strip()]
    only_trailing_comments = all(line.startswith("--") for line in after_lines)
    if only_trailing_comments:
        return before.strip()
    return sql


def _check_for_repetition_loop(sql: str) -> None:
    """Aynı tablonun sorguda kaç kez (farklı takma adlarla) referans
    verildiğini sayar — çok-CTE'li meşru sorguları yanlışlıkla
    reddetmez."""
    table_names = _TABLE_REFERENCE_PATTERN.findall(sql)
    if not table_names:
        return
    counts = Counter(name.lower() for name in table_names)
    most_common_table, most_common_count = counts.most_common(1)[0]
    if most_common_count > _MAX_SAME_TABLE_REFERENCES:
        raise SqlRepetitionLoopError(
            f"Model bir tekrar döngüsüne girmiş görünüyor "
            f"('{most_common_table}' tablosu sorguda {most_common_count} kez "
            f"referans verilmiş — aynı JOIN zinciri farklı takma adlarla "
            f"kopyalanmış olabilir)."
        )


def _strip_code_fences(raw_sql: str) -> str:
    """Modelin döndürdüğü metinden SADECE gerçek SQL'i çıkarır."""
    text_value = raw_sql.strip()
    fence_match = re.search(
        r"```(?:sql)?\s*\n?(.*?)```", text_value, flags=re.IGNORECASE | re.DOTALL
    )
    if fence_match:
        text_value = fence_match.group(1).strip()
    else:
        text_value = re.sub(r"^```sql|^```|```$", "", text_value, flags=re.IGNORECASE).strip()
    return text_value.rstrip(";").strip()