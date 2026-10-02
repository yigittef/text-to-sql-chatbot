import os
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    """Zorunlu bir ortam değişkeni eksik olduğunda fırlatılır."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigurationError(
            f"Zorunlu ortam değişkeni eksik: {name}. "
            f".env dosyanızı kontrol edin."
        )
    return value


@dataclass(frozen=True)
class DatabaseConfig:
    driver: str
    server: str
    database: str
    username: str
    password: str
    connection_timeout_seconds: int = 5
    query_timeout_seconds: int = 10

    @property
    def connection_string(self) -> str:
        return (
            f"DRIVER={{{self.driver}}};SERVER={self.server};DATABASE={self.database};"
            f"UID={self.username};PWD={self.password};TrustServerCertificate=yes;"
        )

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        return cls(
            driver=os.environ.get("DB_DRIVER", "ODBC Driver 18 for SQL Server"),
            server=_require_env("DB_SERVER"),
            database=_require_env("DB_NAME"),
            username=_require_env("DB_USER"),
            password=_require_env("DB_PASSWORD"),
        )


@dataclass(frozen=True)
class LLMConfig:
    """Gemini API baglanti ayarlari."""
    api_key: str
    model_name: str = "gemini-3.5-flash"

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=_require_env("GEMINI_API_KEY"),
            model_name=os.environ.get("GEMINI_MODEL_NAME", "gemini-3.5-flash"),
        )


@dataclass(frozen=True)
class LocalLLMConfig:
    """Kendi barındırılan (self-hosted) bir Ollama sunucusuna bağlantı ayarları.
    Sunucuya erişmek için VPN/özel ağ bağlantısı gerekebilir.

    NOT: repeat_penalty eklendi — testlerde modelin bazi karmasik
    sorularda (ozellikle cok tablolu JOIN gerektiren) ayni JOIN
    blogunu/cumleyi ART ARDA defalarca tekrarlayip "donguye kilitlendigi"
    (degenerate repetition) gozlemlendi (ornek: kup, kup2, kup3...kup7
    diye ayni blogu 7 kez kopyalamasi, ya da ayni duzeltme cumlesini 8
    kez tekrarlamasi). Bu, kucuk dil modellerinde bilinen yaygin bir
    zayifliktir. repeat_penalty (varsayilan Ollama degeri: 1.1), modelin
    az once urettigi token/kaliplari tekrar secmesini cezalandirir —
    1.3'e cikararak bu tekrar donguesune girme egilimini belirgin sekilde
    azaltiyoruz. num_predict zaten sonsuz tekrari sinirliyor ama
    repeat_penalty, sorunu SONUCTA kesmek yerine BASLAMADAN engelliyor."""
    base_url: str
    model_name: str = "qwen2.5-coder:7b"
    temperature: float = 0.0
    num_ctx: int = 8192
    num_predict: int = 1024
    repeat_penalty: float = 1.3

    @classmethod
    def from_env(cls) -> "LocalLLMConfig":
        return cls(
            base_url=_require_env("LOCAL_LLM_BASE_URL"),
            model_name=os.environ.get("LOCAL_LLM_MODEL_NAME", "qwen2.5-coder:7b"),
        )
