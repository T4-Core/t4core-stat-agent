"""[NEW v4] BM25 토크나이저 — 설정 이름(type)으로 고름

  kiwi       Kiwi 형태소 (기본). variant:
               table  = ingestion/table_text.tokenize (현재 표 검색 = baseline)
               hybrid = retrieval/lexical.tokenize (복합어 분해 + 지역명·'율' 축약형 추가)
             user_dict: none | lexicon | <파일 경로>
               lexicon = CSV 값 사전의 항목·분류 이름 + term_dict 통계어를 사용자 단어(NNP)로 등록
                         ('출생아수' 가 '출생'+'아'+'수' 로 쪼개지지 않게)
               파일    = 한 줄에 단어 하나 (탭 뒤에 품사, 없으면 NNP)
             tags: 남길 품사 앞머리 (기본 NN·SL·SN·XR·VV·VA)
  okt / mecab  KoNLPy (선택 설치: pip install konlpy, mecab 은 시스템 설치도 필요)
  char_ngram   공백을 뺀 글자 n-gram (n: [2, 3]) — 형태소 분석기 없이 띄어쓰기·복합어 차이에 강함
  whitespace   공백 + 기호 기준 단순 분리 (하한선 비교용)

모든 토크나이저는 id 를 가진다 → 같은 코퍼스·같은 id 면 문서 토큰을 캐시에서 다시 씀
"""
from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path

DEFAULT_TAGS = ("NN", "SL", "SN", "XR", "VV", "VA")
_SPLIT = re.compile(r"[\s\|/,·()\[\]{}:;~\-\"'<>]+")


class KiwiTokenizer:
    def __init__(self, variant="table", user_dict=None, tags=DEFAULT_TAGS, split_complex=False):
        if variant not in ("table", "hybrid"):
            raise ValueError(f"kiwi variant 는 table | hybrid: {variant}")
        self.variant, self.user_dict, self.tags, self.split_complex = variant, user_dict, tuple(tags), split_complex
        self._kiwi, self._lock = None, threading.Lock()
        self._words = self._user_words() if user_dict and user_dict != "none" else []
        default = (variant == "table" and not self._words and self.tags == DEFAULT_TAGS and not split_complex)
        wh = hashlib.sha1("\n".join(self._words).encode()).hexdigest()[:8] if self._words else "-"
        self.id = "kiwi:table" if default else \
            f"kiwi:{variant}:{wh}:{','.join(self.tags)}:{int(split_complex)}"

    def _user_words(self):
        if self.user_dict == "lexicon":
            return lexicon_words()
        p = Path(self.user_dict)
        if not p.exists():
            raise FileNotFoundError(f"kiwi user_dict 파일 없음: {p}")
        return [x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]

    def _get(self):
        if self._kiwi is None:
            from kiwipiepy import Kiwi
            k = Kiwi()
            for w in self._words:
                form, _, tag = w.partition("\t")
                try:
                    k.add_user_word(form.strip(), (tag or "NNP").strip())
                except Exception:  # noqa: BLE001  (등록 못 하는 단어는 건너뜀)
                    pass
            self._kiwi = k
        return self._kiwi

    def __call__(self, text):
        text = str(text or "")
        if self.variant == "table" and not self._words and self.tags == DEFAULT_TAGS and not self.split_complex:
            from backend.rag.ingestion.table_text import tokenize
            return tokenize(text)                         # baseline 과 같은 함수 (같은 Kiwi 인스턴스)
        with self._lock:
            k = self._get()
            toks = [t.form for t in k.tokenize(text, split_complex=self.split_complex) if t.tag.startswith(self.tags)]
            if self.variant == "hybrid":
                from backend.rag.retrieval.lexical import REGION_SUFFIX
                extra = [t.form for t in k.tokenize(text, split_complex=True) if t.tag.startswith(self.tags)]
                for t in toks:
                    if len(t) >= 3 and REGION_SUFFIX.search(t):
                        stem = REGION_SUFFIX.sub("", t)
                        if len(stem) >= 2:
                            extra.append(stem)
                    if len(t) >= 4 and t[-1] in "율률":
                        extra.append(t[-3:])
                toks += [e for e in extra if e not in toks]
        return toks


def lexicon_words(max_len=12):
    """CSV 값 사전 항목·분류 이름(지역 제외) + term_dict 통계어 → 사용자 단어 목록 (공백 없는 2~max_len 글자)"""
    words = set()
    try:
        from backend.rag.csv_index import load_index
        v = load_index().v
        v = v[(v["kind"].isin(["item", "dim"])) & (v["slot"] != "지역")]
        words |= set(v["name"].astype(str))
    except FileNotFoundError:
        pass
    try:
        from backend.rag.query_analyzer.terms import TERM_INDEX     # 일상어 → 통계어 (통계어 쪽만 등록)
        for ts in TERM_INDEX.values():
            words |= {x for x in ts if isinstance(x, str)}
    except Exception:  # noqa: BLE001  (term_dict 가 없어도 CSV 단어만으로 진행)
        pass
    # 한글이 들어 있고 공백·괄호·범위 기호가 없는 2~max_len 글자 ('1인가구' 는 되고 '20~24세'·'2020' 은 안 됨)
    return sorted(w for w in words if 2 <= len(w) <= max_len and re.search(r"[가-힣]", w)
                  and not re.search(r"[\s()~·,\-]", w) and not re.fullmatch(r"[\d가-힣]*\d+세(이상|이하|미만)?", w))


class KonlpyTokenizer:
    def __init__(self, engine="okt", tags=("Noun", "Alpha", "Number", "Verb", "Adjective", "NN", "SL", "SN", "XR", "VV", "VA")):
        try:
            import konlpy.tag as kt
        except ImportError as e:
            raise ImportError(f"{engine} 토크나이저는 konlpy 가 필요합니다: pip install konlpy") from e
        self.engine = {"okt": kt.Okt, "mecab": kt.Mecab}[engine]()
        self.tags, self.id, self._lock = tuple(tags), f"konlpy:{engine}", threading.Lock()

    def __call__(self, text):
        with self._lock:
            return [w for w, t in self.engine.pos(str(text or "")) if t.startswith(self.tags)]


class CharNgramTokenizer:
    def __init__(self, n=(2, 3), keep_words=True):
        self.n = tuple(sorted(int(x) for x in (n if isinstance(n, (list, tuple)) else [n])))
        self.keep_words = keep_words
        self.id = f"char_ngram:{'-'.join(map(str, self.n))}:{int(keep_words)}"

    def __call__(self, text):
        out = []
        for w in _SPLIT.split(str(text or "").lower()):
            if not w:
                continue
            if self.keep_words and len(w) > max(self.n):
                out.append(w)
            for n in self.n:
                if len(w) >= n:
                    out += [w[i:i + n] for i in range(len(w) - n + 1)]
                elif n == self.n[0]:
                    out.append(w)                    # 가장 짧은 n 보다 짧은 낱말은 그대로
        return out


class WhitespaceTokenizer:
    id = "whitespace"

    def __call__(self, text):
        return [w for w in _SPLIT.split(str(text or "").lower()) if w]
