"""Veritabanı erişim katmanı. Bağlantı yönetimi SQLAlchemy'nin QueuePool'u
ile yapılır: sabit sayıda bağlantı önceden açılıp havuzda tutulur, her
sorgu için yeniden bağlantı kurulmaz."""
import logging
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from config import DatabaseConfig
from models import QueryResult

logger = logging.getLogger(__name__)


class DatabaseRepository:
    def __init__(
        self,
        config: DatabaseConfig,
        max_rows: int = 500,
        pool_size: int = 5,
        max_overflow: int = 5,
    ):
        self._config = config
        self._max_rows = max_rows
        self._engine: Engine = self._build_engine(config, pool_size, max_overflow)

    @property
    def engine(self) -> Engine:
        return self._engine

    @staticmethod
    def _build_engine(config: DatabaseConfig, pool_size: int, max_overflow: int) -> Engine:
        odbc_connect = quote_plus(config.connection_string)
        connection_url = f"mssql+pyodbc:///?odbc_connect={odbc_connect}"
        return create_engine(
            connection_url,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"timeout": config.connection_timeout_seconds},
        )

    def run_select_query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> QueryResult:
        try:
            with self._engine.connect() as connection:
                connection = connection.execution_options(
                    timeout=self._config.query_timeout_seconds
                )
                result = connection.execute(text(sql), params or {})
                columns = list(result.keys())
                rows = result.fetchmany(self._max_rows)
                return QueryResult(columns=columns, rows=rows)
        except Exception:
            logger.warning("SQL yürütme hatası. Sorgu: %s", sql, exc_info=True)
            raise

    def dispose(self) -> None:
        self._engine.dispose()