"""Herhangi bir LLMClient'ı sarmalayıp, giden her prompt'u ve dönen her
cevabı loglayan şeffaf bir gözlem katmanı.

TASARIM DESENİ: Decorator. Gerçek istemciyi (GeminiLLMClient veya
LocalLLMClient) DEĞİŞTİRMEZ — onu "sarar", aynı LLMClient arayüzünü
(generate metodu) sunar, ama araya loglama adımı ekler.

NOT: LOG'A yazılan şema metni kısaltılır (aşağıdaki _summarize_schema_
for_log) — LLM'e gönderilen GERÇEK prompt bundan etkilenmez, hâlâ tam
şema gönderilir. Bu, sadece terminal/log dosyasının aynı büyük şema
metnini her tek çağrıda tekrar tekrar yazıp şişmesini önlemek için.
"""
import logging
import re
import time

from llm_client import LLMClient

logger = logging.getLogger("llm_trace")

_SCHEMA_BLOCK_PATTERN = re.compile(r"(Tablolar:\n)(.*?)(\n\n)", re.DOTALL)


def _summarize_schema_for_log(text_value: str) -> str:
    def _replace(match: re.Match) -> str:
        table_lines = [line for line in match.group(2).split("\n") if line.strip()]
        return (
            f"{match.group(1)}[{len(table_lines)} tablo — şema log'da kısaltıldı, "
            f"LLM'e TAM olarak gönderildi]{match.group(3)}"
        )
    return _SCHEMA_BLOCK_PATTERN.sub(_replace, text_value, count=1)


class LoggingLLMClient(LLMClient):
    def __init__(self, wrapped: LLMClient):
        self._wrapped = wrapped
        self._call_sayaci = 0

    def generate(self, prompt: str) -> str:
        self._call_sayaci += 1
        cagri_no = self._call_sayaci

        logger.info("\n" + "=" * 78)
        logger.info("LLM ÇAĞRISI #%d — GİDEN PROMPT:", cagri_no)
        logger.info("-" * 78)
        logger.info(_summarize_schema_for_log(prompt))

        baslangic = time.perf_counter()
        try:
            cevap = self._wrapped.generate(prompt)
        except Exception:
            gecen = time.perf_counter() - baslangic
            logger.exception("LLM ÇAĞRISI #%d — %.2f sn SONRA HATA:", cagri_no, gecen)
            raise
        gecen = time.perf_counter() - baslangic

        logger.info("-" * 78)
        logger.info("LLM ÇAĞRISI #%d — DÖNEN CEVAP (%.2f sn):", cagri_no, gecen)
        logger.info(cevap)
        logger.info("=" * 78 + "\n")

        return cevap

    