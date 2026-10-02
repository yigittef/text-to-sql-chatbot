"""Kullanıcının en çok sorduğu örnek soruları JSON dosyasında saklar.

Büyük ölçekte (günde binlerce farklı soru), her soruyu ilk sorulduğunda
kalıcı dosyaya yazmak dosyayı sınırsızca şişirir — çoğu soru sadece bir
kez sorulur, bir daha hiç tekrarlanmaz ("uzun kuyruk"). Bu yüzden:
  - Bir soru ilk kez sorulduğunda, kalıcı dosyaya HİÇ yazılmaz; sadece
    process belleğinde (sınırlı boyutlu, FIFO ile taşan) bir "aday"
    listesine eklenir.
  - Aynı soru İKİNCİ kez sorulduğunda, aday listesinden çıkarılıp
    kalıcı dosyaya count=2 ile yazılır; sonraki her tekrarında sayaç
    artar.
Bu, dosyanın sadece gerçekten tekrar eden (dolayısıyla favori olmaya
aday) soruları biriktirmesini sağlar; tek seferlik binlerce soru
dosyayı asla şişirmez. Bellekteki aday listesi de sınırlı boyutlu
olduğu için, aynı anda çok sayıda farklı soru gelse bile bellek
sınırsızca büyümez.
"""
import json
import os
from collections import OrderedDict
from typing import Dict, List, Tuple

_DEFAULT_EXAMPLES = (
    "En pahalı 3 ürün hangileri?",
    "Toplam kaç müşterimiz var?",
    "En çok sipariş veren müşteri kim?",
    "Hangi departmanda en çok çalışan var?",
    "Hâlâ yolda olan kaç kargo var?",
    "Kategorilere göre toplam stok değerini göster",
)


class FavoritesRepository:
    def __init__(
        self,
        file_path: str = "favori_sorular.json",
        min_entries_for_favorites: int = 3,
        max_examples: int = 6,
        min_repeats_to_persist: int = 2,
        max_candidates_in_memory: int = 2000,
    ):
        self._file_path = file_path
        self._min_entries = min_entries_for_favorites
        self._max_examples = max_examples
        self._min_repeats = min_repeats_to_persist
        self._max_candidates = max_candidates_in_memory
        self._candidates: "OrderedDict[str, int]" = OrderedDict()

    def record_question(self, question: str) -> None:
        counts = self._load()

        if question in counts:
            counts[question] += 1
            self._save(counts)
            return

        seen_before = self._candidates.pop(question, None)
        if seen_before is not None:
            # Ikinci kez soruldu — artik kalici dosyaya yazmaya deger.
            counts[question] = self._min_repeats
            self._save(counts)
            return

        # Ilk kez soruldu — kalici dosyaya yazmadan, sadece bellekte tut.
        self._candidates[question] = 1
        self._evict_if_needed()

    def get_examples(self) -> Tuple[List[str], str]:
        counts = self._load()
        if len(counts) >= self._min_entries:
            ordered = sorted(counts.items(), key=lambda item: -item[1])
            selected = [question for question, _ in ordered[: self._max_examples]]
            for fallback in _DEFAULT_EXAMPLES:
                if len(selected) >= self._max_examples:
                    break
                if fallback not in selected:
                    selected.append(fallback)
            return selected, "⭐ Favoriler"
        return list(_DEFAULT_EXAMPLES), "Örnek sorular"

    def _evict_if_needed(self) -> None:
        # FIFO: en once eklenen (en eski) adaylari at, bellek sinirini asma.
        while len(self._candidates) > self._max_candidates:
            self._candidates.popitem(last=False)

    def _load(self) -> Dict[str, int]:
        if not os.path.exists(self._file_path):
            return {}
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, counts: Dict[str, int]) -> None:
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(counts, f, ensure_ascii=False, indent=2)