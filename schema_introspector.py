"""Veritabanı şemasını runtime'da keşfeder ve LLM prompt'u için okunabilir bir
açıklama üretir.

Her soruda TAM şema gönderilir (filtreleme yapılmaz) — bu, maliyet/hız
yerine doğruluğu önceliklendiren bilinçli bir tercihtir.

ENUM DEĞER ÖNBELLEĞİ: 'durum', 'izin_turu' gibi düşük çeşitlilikli metin
kolonlarının GERÇEK olası değerleri şemaya eklenir — model artık
"Aktif"/"Red"/"Onay" gibi var olmayan değerler uydurmak yerine,
veritabanındaki gerçek metinleri kullanır. Bu değerler her soruda yeniden
sorgulanmaz — ilk çağrıda 1 kez hesaplanıp bellekte tutulur.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    foreign_key: Optional[str] = None


class SchemaIntrospector:
    def __init__(
        self,
        engine: Engine,
        excluded_tables: Tuple[str, ...] = ("sysdiagrams",),
        enum_max_distinct: int = 10,
    ):
        self._engine = engine
        self._excluded_tables = set(excluded_tables)
        self._enum_max_distinct = enum_max_distinct
        self._enum_values_cache: Optional[Dict[str, Dict[str, List[str]]]] = None

    def build_schema_description(self) -> str:
        """LLM'e verilecek 'Tablolar:\\ntablo (kolon, kolon -> ref.id, kolon
        [değerler: ...])' formatında, veritabanindaki TUM tablolarin tam
        aciklamasini uretir."""
        inspector = inspect(self._engine)
        table_names = self._table_names(inspector)

        lines = ["Tablolar:"]
        for table_name in table_names:
            columns = self._describe_columns(inspector, table_name)
            lines.append(f"{table_name} ({', '.join(columns)})")
        return "\n".join(lines)

    def get_all_columns(self) -> Dict[str, List[str]]:
        """Her tablonun kolon adlarını döndürür (tablo_adi -> [kolon1, ...]).

        Bu, SQL hata mesajlarındaki 'Invalid column name X' gibi ifadelerde
        geçen kolonun GERÇEKTE hangi tablo(lar)da var olduğunu bulmak için
        kullanılır — böylece her yanlış kolon/tablo çifti için elle kural
        yazmak yerine, doğrulama otomatik ve genel şekilde yapılır."""
        inspector = inspect(self._engine)
        result: Dict[str, List[str]] = {}
        for table_name in self._table_names(inspector):
            result[table_name] = [col["name"] for col in inspector.get_columns(table_name)]
        return result

    def _table_names(self, inspector) -> List[str]:
        return sorted(
            name for name in inspector.get_table_names() if name not in self._excluded_tables
        )

    def _describe_columns(self, inspector, table_name: str) -> List[str]:
        foreign_keys = self._map_foreign_keys(inspector, table_name)
        enum_values = self._get_enum_values(table_name)
        described = []
        for column in inspector.get_columns(table_name):
            column_name = column["name"]
            if column_name in foreign_keys:
                described.append(f"{column_name} -> {foreign_keys[column_name]}")
            elif column_name in enum_values:
                degerler = ", ".join(enum_values[column_name])
                described.append(f"{column_name} [değerler: {degerler}]")
            else:
                described.append(column_name)
        return described

    @staticmethod
    def _map_foreign_keys(inspector, table_name: str) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for fk in inspector.get_foreign_keys(table_name):
            local_columns = fk.get("constrained_columns", [])
            remote_table = fk.get("referred_table")
            remote_columns = fk.get("referred_columns", [])
            for local_col, remote_col in zip(local_columns, remote_columns):
                mapping[local_col] = f"{remote_table}.{remote_col}"
        return mapping

    def _get_enum_values(self, table_name: str) -> Dict[str, List[str]]:
        if self._enum_values_cache is None:
            self._enum_values_cache = self._compute_enum_values()
        return self._enum_values_cache.get(table_name, {})

    def _compute_enum_values(self) -> Dict[str, Dict[str, List[str]]]:
        """Düşük çeşitlilikli (enum benzeri) metin kolonlarının gerçek
        değerlerini veritabanından çekip döndürür. Sadece 1 kez (uygulama
        açılışında) çalışır, sonrası bellekten okunur."""
        inspector = inspect(self._engine)
        string_type_keywords = ("VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "TEXT")
        result: Dict[str, Dict[str, List[str]]] = {}

        table_names = self._table_names(inspector)

        with self._engine.connect() as connection:
            for table_name in table_names:
                table_result: Dict[str, List[str]] = {}
                for column in inspector.get_columns(table_name):
                    col_type = str(column["type"]).upper()
                    if not any(keyword in col_type for keyword in string_type_keywords):
                        continue
                    col_name = column["name"]
                    if col_name.lower() == "id" or col_name.lower().endswith("_id"):
                        continue
                    try:
                        rows = connection.execute(
                            text(
                                f"SELECT DISTINCT [{col_name}] FROM [{table_name}] "
                                f"WHERE [{col_name}] IS NOT NULL"
                            )
                        ).fetchall()
                    except Exception:
                        continue
                    values = sorted(str(row[0]) for row in rows)
                    if 1 < len(values) <= self._enum_max_distinct:
                        table_result[col_name] = values
                if table_result:
                    result[table_name] = table_result
        return result