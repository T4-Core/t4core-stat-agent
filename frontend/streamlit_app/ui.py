"""시안(screens.html)의 디자인 토큰 · 부품 → Streamlit CSS · HTML 조각

카드는 st.container(key="card-…") 로 만들고 CSS 의 .st-key-card-… 로 모양을 입힘 (Streamlit ≥ 1.40)
"""
from __future__ import annotations

from html import escape as _escape


def escape(s, quote=True):
    """HTML 이스케이프 + '~' (Streamlit 마크다운이 '2015~2020 … 20~24세' 사이를 취소선으로 읽음)"""
    return _escape(str(s), quote=quote).replace("~", "&#126;")


def md(s):
    """버튼 이름 · 캡션처럼 마크다운으로 읽히는 문자열 — '~' 취소선 방지"""
    return str(s or "").replace("~", "\\~")

CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
:root{--teal:#7BA39D;--teal-d:#5F8B85;--teal-dd:#3F6661;--teal-l:#DCE9E6;--teal-ll:#EEF4F3;--bg:#EDF2F1;--surface:#FAFCFB;
 --card:#FFFFFF;--line:#E2EAE8;--line-s:#EDF1F0;--ink:#1E2928;--ink2:#55625F;--ink3:#8A9794;--accent:#E9A57B}
html,body,[class*="css"],.stApp{font-family:Pretendard,"Noto Sans KR","Malgun Gothic",sans-serif!important}
.stApp{background:var(--bg)}
header[data-testid="stHeader"]{background:transparent;height:0}
#MainMenu,footer{visibility:hidden}
.block-container{max-width:1400px;padding-top:1.2rem;padding-bottom:6rem;background:var(--surface);border:1px solid var(--line);
 border-radius:28px;margin-top:14px}
h1,h2,h3{letter-spacing:-.4px;color:var(--ink)}
/* 카드 */
[class*="st-key-card"]{background:var(--card);border:1px solid var(--line)!important;border-radius:22px!important;padding:18px 20px!important}
[class*="st-key-card-sel"]{border-color:var(--teal)!important;box-shadow:0 0 0 4px rgba(123,163,157,.16)}
[class*="st-key-comp"]{background:#fff;border:1px solid var(--line)!important;border-radius:24px!important;
 box-shadow:0 8px 28px rgba(63,102,97,.07);padding:10px 16px!important}
/* 버튼 · 입력 */
.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button,[data-testid="stPopover"] button{border-radius:14px;font-weight:600}
.stButton>button[kind="primary"],.stFormSubmitButton>button{background:var(--teal);border-color:var(--teal)}
.stButton>button[kind="primary"]:hover,.stFormSubmitButton>button:hover{background:var(--teal-d);border-color:var(--teal-d)}
[data-testid="stTextInput"] input{border-radius:14px}
[data-testid="stForm"]{border:none;padding:0}
/* 조각 */
.nx-logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:19px;color:var(--teal-dd)}
.nx-logo i{width:34px;height:34px;border-radius:11px;background:var(--teal);display:grid;place-items:center;color:#fff;font-style:normal}
.nx-h1{font-size:28px;font-weight:700;text-align:center;margin:4px 0 2px;color:var(--ink)}
.nx-sub{color:var(--ink2);font-size:15px;text-align:center;margin-bottom:14px}
.nx-lbl{font-size:12px;font-weight:600;color:var(--ink3);letter-spacing:.2px;margin:6px 0 6px}
.nx-chip{display:inline-flex;align-items:center;height:28px;padding:0 12px;border-radius:999px;background:var(--teal-ll);
 border:1px solid var(--line);font-size:12.5px;font-weight:600;color:var(--teal-dd);white-space:nowrap;margin:2px 4px 2px 0}
.nx-chip.g{background:#fff;color:var(--ink2);font-weight:500}
.nx-qb{display:flex;flex-wrap:wrap;align-items:center;gap:8px;background:#fff;border:1px solid var(--line);border-radius:999px;
 padding:8px 12px 8px 20px;font-size:14.5px;font-weight:600;width:fit-content;margin:0 auto 14px}
.nx-ch{display:flex;align-items:center;gap:10px;font-size:16px;font-weight:700;color:var(--ink)}
.nx-ch i{width:32px;height:32px;border-radius:10px;background:var(--teal-ll);display:grid;place-items:center;color:var(--teal-d);font-style:normal}
.nx-title{font-size:14.5px;font-weight:700;color:var(--ink)}
.nx-meta{font-size:12px;color:var(--ink3)}
.nx-kv{background:var(--teal-ll);border-radius:16px;padding:14px 18px;margin:10px 0}
.nx-kv .h{display:flex;gap:8px;font-weight:700;color:var(--teal-dd);margin-bottom:6px}
.nx-kv li{list-style:none;display:flex;justify-content:space-between;gap:12px;font-size:13.5px;padding:4px 0;color:var(--ink2)}
.nx-kv li b{color:var(--ink);text-align:right}
.nx-ans{font-size:14.5px;line-height:1.75;color:var(--ink2)}
.nx-ans b{color:var(--ink)}
.nx-src{border-top:1px solid var(--line-s);padding-top:10px;margin-top:6px;font-size:12px;color:var(--ink3);display:flex;justify-content:space-between;gap:10px}
.nx-src a,.nx-link{color:var(--teal-d);font-weight:600;text-decoration:none}
.nx-row{display:flex;align-items:center;gap:12px;padding:11px 14px;border:1px solid var(--line);border-radius:12px;background:#fff;
 font-size:13px;color:var(--ink2);margin-top:8px}
.nx-row a{margin-left:auto}
.nx-legend{display:flex;gap:16px;font-size:12px;color:var(--ink2);margin:2px 0 8px}
.nx-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.nx-big{font-size:26px;font-weight:700;color:var(--ink)}
.nx-em{color:var(--teal-d);font-weight:700}
.nx-step{display:flex;align-items:center;gap:12px;font-size:14px;color:var(--ink3);padding:7px 0}
.nx-step i{width:22px;height:22px;border-radius:50%;border:1.5px solid var(--line);display:grid;place-items:center;font-style:normal;font-size:12px;color:#fff}
.nx-step.done{color:var(--ink2)} .nx-step.done i{background:var(--teal);border-color:var(--teal)}
.nx-step span{margin-left:auto;font-size:12px}
.nx-note{font-size:12.5px;color:var(--ink3)}
.nx-empty{text-align:center;padding:60px 0 30px}
</style>
"""


def chip(t, ghost=False):
    return f'<span class="nx-chip{" g" if ghost else ""}">{escape(str(t))}</span>'


def question_bubble(q, chips=()):
    return f'<div class="nx-qb">{escape(q)}{"".join(chip(c) for c in chips)}</div>'


def card_head(icon, title, extra=""):
    return f'<div class="nx-ch"><i>{icon}</i>{escape(title)}{extra}</div>'


def kv(title, items, icon="💡"):
    lis = "".join(f"<li>{escape(str(a))}<b>{escape(str(b))}</b></li>" for a, b in items)
    return f'<div class="nx-kv"><div class="h">{icon} {escape(title)}</div><ul style="margin:0;padding:0">{lis}</ul></div>'


def bullets(title, points, icon="💡"):
    lis = "".join(f"<li>{escape(str(p))}</li>" for p in points)
    return f'<div class="nx-kv"><div class="h">{icon} {escape(title)}</div><ul style="margin:0;padding:0">{lis}</ul></div>'


def source_line(name, url):
    link = f'<a href="{escape(url)}" target="_blank">KOSIS에서 보기 ›</a>' if url else ""
    return f'<div class="nx-src"><span>출처 · {escape(name or "통계표")}</span>{link}</div>'


def table_row(name, url):
    link = f'<a class="nx-link" href="{escape(url)}" target="_blank">KOSIS ›</a>' if url else ""
    return f'<div class="nx-row">🗂️ <span>사용한 통계표 · {escape(name)}</span>{link}</div>'


def legend():
    return ('<div class="nx-legend"><span><i style="background:#7BA39D"></i>질문한 시점</span>'
            '<span><i style="background:#DCE9E6"></i>사이 연도</span></div>')


def steps(rows):
    """rows = [(이름, 끝났는가, 시간 문자열)]"""
    out = []
    for name, done, t in rows:
        out.append(f'<div class="nx-step{" done" if done else ""}"><i>{"✓" if done else ""}</i>{escape(name)}'
                   f'<span>{escape(t or "")}</span></div>')
    return "".join(out)


def answer_html(text):
    """답변 문장: 숫자+단위는 굵게, 줄바꿈은 문단"""
    import re
    paras = [p.strip() for p in (text or "").split("\n") if p.strip()]
    # 값(단위가 붙은 숫자 · 천 단위 쉼표 숫자)만 굵게 — 연도('2021년')는 그대로
    num = re.compile(r"(-?\d[\d,]*(?:\.\d+)?\s*(?:%p|%|만\s*가구|만\s*명|가구|명|건|호|천명|배)|\d{1,3}(?:,\d{3})+(?:\.\d+)?)")
    return "".join(f'<p class="nx-ans">{num.sub(lambda m: f"<b>{m.group(1)}</b>", escape(p, quote=False))}</p>' for p in paras)
