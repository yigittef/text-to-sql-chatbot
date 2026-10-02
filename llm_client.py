"""LLM sağlayıcılarını soyutlayan arayüz.

Dependency Inversion Principle: üst katmanlar (nlq_service) somut bir
sağlayıcıya değil, bu soyut arayüze bağımlıdır. Yeni bir sağlayıcıya geçmek
yalnızca yeni bir LLMClient implementasyonu eklemeyi gerektirir.
"""
import concurrent.futures
from abc import ABC, abstractmethod

from google import genai
from langchain_ollama import ChatOllama

from config import LocalLLMConfig, LLMConfig


class LLMClient(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Verilen prompt için modelin ürettiği metni döndürür."""


class GeminiLLMClient(LLMClient):
    """Gemini API üzerinden çalışan LLM istemcisi."""

    def __init__(self, config: LLMConfig):
        self._model_name = config.model_name
        self._client = genai.Client(api_key=config.api_key)

    def generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._model_name, contents=prompt
        )
        if not response.text:
            raise RuntimeError("LLM boş bir yanıt döndürdü.")
        return response.text.strip()



class LocalLLMClient(LLMClient):
    """Kendi barındırılan (self-hosted) bir Ollama sunucusu üzerinden çalışan
    LLM istemcisi. Sunucuya erişmek için VPN/özel ağ bağlantısı gerekebilir."""

    def __init__(self, config: LocalLLMConfig, timeout_seconds: int = 60):
        self._config = config
        self._timeout_seconds = timeout_seconds

    def _build_model(self) -> ChatOllama:
        return ChatOllama(
            model=self._config.model_name,
            base_url=self._config.base_url,
            temperature=self._config.temperature,
            num_ctx=self._config.num_ctx,
            num_predict=self._config.num_predict,
            repeat_penalty=self._config.repeat_penalty,
            num_gpu=99,
            keep_alive="24h",
        )

    def generate(self, prompt: str) -> str:
        model = self._build_model()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(model.invoke, prompt)
        try:
            response = future.result(timeout=self._timeout_seconds)
        except concurrent.futures.TimeoutError:
            executor.shutdown(wait=False)
            raise RuntimeError(
                f"Yerel LLM {self._timeout_seconds} saniye içinde cevap "
                f"vermedi. Sunucu hâlâ önceki bir istekle meşgul olabilir "
                f"— birkaç dakika bekleyip tekrar deneyin."
            )
        except Exception:
            executor.shutdown(wait=False)
            raise
        executor.shutdown(wait=False)
        if not response.content:
            raise RuntimeError("Yerel LLM boş bir yanıt döndürdü.")
        return response.content.strip()
