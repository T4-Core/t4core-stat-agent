"""
OKF md 읽기·쓰기 — 프론트매터(YAML) + 본문, 사람 구간 보존, 경로 해석 (OKF v0.3 §경로)

  Doc.read(path)            → Doc(meta, body, path)   CRLF·BOM 을 정리해서 읽음 (Windows git autocrlf)
  Doc.text()                → '---\\n<yaml>---\\n<body>' (LF)
  write_if_changed(path, doc, keep=…)  내용이 같으면 쓰지 않음. 바뀐 경우에만 generated.at 을 새로 (git diff 를 실제 변경만)
  resolve(bundle, from_file, ref)  '/x/y.md' = 번들 루트 기준 · 'https:' = 외부 · 그 밖 = 파일 위치 기준
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import yaml

RESERVED = {"index.md", "log.md"}
HUMAN_START, HUMAN_END = "<!-- human:start -->", "<!-- human:end -->"
_HUMAN = re.compile(re.escape(HUMAN_START) + r"\n?(.*?)\n?" + re.escape(HUMAN_END), re.DOTALL)
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def now():
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def dump_yaml(meta: dict) -> str:
    """최상위는 블록(키마다 한 줄), 안쪽의 짧은 목록·매핑만 한 줄(flow) — 사람이 읽고 git diff 보기 좋게"""
    out = []
    for k, v in meta.items():
        style = None if isinstance(v, (dict, list)) else False
        out.append(yaml.safe_dump({k: v}, allow_unicode=True, sort_keys=False, default_flow_style=style, width=1000))
    return "".join(out)


@dataclass
class Doc:
    meta: dict = field(default_factory=dict)
    body: str = ""
    path: Path | None = None
    error: str = ""

    @classmethod
    def parse(cls, text: str, path=None):
        t = text.lstrip("﻿").replace("\r\n", "\n")
        if not t.startswith("---\n"):
            return cls({}, t, path, "프론트매터 없음")
        end = t.find("\n---", 4)
        if end < 0:
            return cls({}, t, path, "프론트매터 끝(---)이 없음")
        try:
            meta = yaml.safe_load(t[4:end + 1]) or {}
        except yaml.YAMLError as e:
            return cls({}, t, path, f"YAML 오류: {str(e).splitlines()[0]}")
        if not isinstance(meta, dict):
            return cls({}, t, path, "프론트매터가 매핑이 아님")
        rest = t[end + 4:]
        return cls(meta, rest.removeprefix("\n"), path)

    @classmethod
    def read(cls, path):
        p = Path(path)
        return cls.parse(p.read_text(encoding="utf-8"), p)

    @property
    def type(self):
        return str(self.meta.get("type") or "").strip()

    def text(self) -> str:
        body = self.body if self.body.endswith("\n") or not self.body else self.body + "\n"
        return f"---\n{dump_yaml(self.meta)}---\n{body}"

    def human(self) -> str:
        m = _HUMAN.search(self.body)
        return m.group(1).strip("\n") if m else ""

    def links(self):
        return [m.group(1) for m in _LINK.finditer(self.body)]


def human_block(text=""):
    return f"{HUMAN_START}\n{text.strip()}\n{HUMAN_END}\n" if text.strip() else f"{HUMAN_START}\n{HUMAN_END}\n"


def _same(a: Doc, b: Doc, ignore=("generated",)):
    strip = lambda m: {k: v for k, v in m.items() if k not in ignore}
    return strip(a.meta) == strip(b.meta) and a.body.strip() == b.body.strip()


def write_if_changed(path, doc: Doc, owned=None, producer="process:okf-build/1") -> str:
    """→ 'new' | 'changed' | 'same'
    owned: 생성기가 책임지는 키. 기존 파일의 다른 키(사람이 넣은 키·모르는 키·verified·superseded_by 등)는 보존 (v0.3)
    본문의 사람 구간(<!-- human:start --> … <!-- human:end -->)도 기존 파일 것을 그대로"""
    p = Path(path)
    old = Doc.read(p) if p.exists() else None
    if old is not None and not old.error:
        if owned is not None:
            for k, v in old.meta.items():
                if k not in owned and k not in doc.meta:
                    doc.meta[k] = v
        if HUMAN_START in doc.body and old.human():
            doc.body = _HUMAN.sub(lambda m: f"{HUMAN_START}\n{old.human()}\n{HUMAN_END}", doc.body, count=1)
    if old is not None and not old.error and _same(old, doc):
        return "same"
    doc.meta["generated"] = {"by": producer, "at": now()}
    # generated 는 type 바로 뒤가 읽기 좋음
    doc.meta = {k: doc.meta[k] for k in ["type", "title", "description", "resource", "tags", "status", "superseded_by",
                                         "generated", "verified"] if k in doc.meta} | doc.meta
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc.text(), encoding="utf-8", newline="\n")
    return "changed" if old is not None else "new"


def concept_id(bundle: Path, path: Path) -> str:
    return "/" + PurePosixPath(Path(path).resolve().relative_to(Path(bundle).resolve()).as_posix()).as_posix()


def resolve(bundle: Path, from_file: Path, ref: str) -> Path | None:
    """번들 안 경로 → 파일 경로 (외부 URL·앵커만 있는 링크는 None). '#…' 꼬리는 뗌"""
    ref = str(ref or "").strip()
    if not ref or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", ref) or ref.startswith("#"):
        return None
    ref = ref.split("#", 1)[0]
    base = Path(bundle) if ref.startswith("/") else Path(from_file).parent
    return (base / ref.lstrip("/")).resolve()


def iter_docs(bundle: Path, dirs=("tables", "classifications", "concepts")):
    """번들의 개념 문서 (예약 파일 제외)"""
    root = Path(bundle)
    for d in dirs:
        if (root / d).exists():
            for p in sorted((root / d).rglob("*.md")):
                if p.name not in RESERVED:
                    yield p
