"""data/raw/*.pdf -> data/samples/*.md 변환.

페이지별 전략:
  1) 표지/디자인 페이지(제어문자·Private-use 영역 비율이 높음) → 건너뜀
  2) pymupdf4llm 으로 markdown 추출
  3) 추출 결과에 U+FFFD 가 섞이면, 해당 페이지만 pymupdf 원시 텍스트로 대체
     (pymupdf4llm 은 PDF 의 커스텀 폰트로 인코딩된 원문자 ㉑ 등을
      `\\ufffd` 로 치환해버리지만, pymupdf 원시 추출은 원본 한글 시퀀스 보존)
  4) 확실히 식별된 원문자 시퀀스는 실제 원문자로 치환
     (ex. "쇭쇶"(U+C1ED U+C1F6) → "㉑"). 매핑 불확실한 건 raw 그대로 둠.
"""
import argparse
import logging
import re
import sys
import time
from pathlib import Path

import pymupdf
import pymupdf4llm

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# PDF 커스텀 폰트 → 원문자 치환 테이블
# 국세청 『2025년 법인세 신고안내』 PDF 에서 확인된 매핑.
# (쇭=U+C1ED, 쇮=U+C1EE, 쇵~쇻=U+C1F5~U+C1FB)
# 일부 시퀀스는 컨텍스트가 애매해서 매핑 미포함 → raw 유지.
# ------------------------------------------------------------------
CIRCLE_SUBS = {
    # 쇭 prefix (컨텍스트 추론: MAX(쇭쇵,㉑), ㉔근거법령→쇭쇺수입금액→쇭쇻대응원가)
    "쇭쇵": "⑳",
    "쇭쇶": "㉑",
    "쇭쇷": "㉒",
    "쇭쇸": "㉓",
    "쇭쇹": "㉔",
    "쇭쇺": "㉕",
    "쇭쇻": "㉖",
    # 쇮 prefix (다른 표/폰트 서브셋에서 ㉕~㉛ 중복 인코딩)
    "쇮쇵": "㉕",
    "쇮쇶": "㉖",
    "쇮쇷": "㉗",
    "쇮쇸": "㉘",
    "쇮쇹": "㉙",
    "쇮쇺": "㉚",
    "쇮쇻": "㉛",
}

# 공백/개행이 끼어들 수 있어 두 글자 사이 \s* 허용
_CIRCLE_PAT = re.compile(r"([쇭쇮])\s*([쇵-쇻])")


def _apply_circle_subs(text: str) -> str:
    """raw 텍스트에 원문자 치환 적용 (공백/개행 틈이 있어도 매칭)."""
    def repl(m):
        key = m.group(1) + m.group(2)
        return CIRCLE_SUBS.get(key, key)
    return _CIRCLE_PAT.sub(repl, text)


# pymupdf4llm 이 내보내는 그림/벡터그래픽 플레이스홀더 제거.
# RAG 임베딩에 잡음만 되므로 라인 전체 삭제.
_PLACEHOLDER_PAT = re.compile(
    r"^[ \t]*\*\*==>[^<]+<==\*\*[ \t]*$\n?",
    re.MULTILINE,
)
# 결과적으로 남는 3 개 이상 연속 빈 줄을 2 개로 축약.
_BLANKLINES_PAT = re.compile(r"\n{3,}")


def _strip_noise(text: str) -> str:
    text = _PLACEHOLDER_PAT.sub("", text)
    text = _BLANKLINES_PAT.sub("\n\n", text)
    return text


def _is_cover_like(text: str) -> bool:
    """표지/디자인 페이지 휴리스틱.

    임베디드 커스텀 폰트 전용 페이지는 U+0000~U+001F, U+0080~U+0FFF
    같은 '일반 본문에 잘 안 쓰이는' 코드포인트 비율이 높다.
    본문 페이지는 대부분 한글 음절(U+AC00~U+D7A3) 또는 ASCII.
    """
    if not text.strip():
        return True
    normal = 0
    weird = 0
    for ch in text:
        cp = ord(ch)
        if cp < 0x20:
            # \n, \t 등 개행은 정상
            if ch in "\n\r\t":
                continue
            weird += 1
        elif 0x20 <= cp < 0x80:  # ASCII printable
            normal += 1
        elif 0xAC00 <= cp <= 0xD7A3:  # 한글 음절
            normal += 1
        elif 0x3000 <= cp <= 0x33FF:  # CJK 기호/원문자
            normal += 1
        elif 0xFF00 <= cp <= 0xFFEF:  # 전각
            normal += 1
        elif 0x4E00 <= cp <= 0x9FFF:  # CJK 통합 한자
            normal += 1
        else:
            weird += 1
    total = normal + weird
    if total == 0:
        return True
    ratio = weird / total
    return ratio > 0.30


def convert(pdf_path: Path, out_path: Path) -> dict:
    """단일 PDF -> Markdown 파일."""
    start = time.perf_counter()
    doc = pymupdf.open(str(pdf_path))
    total_pages = doc.page_count

    skipped_cover = 0
    fallback_raw = 0
    kept_md = 0

    parts: list[str] = []
    for page_num in range(total_pages):
        raw_text = doc[page_num].get_text("text")

        if _is_cover_like(raw_text):
            skipped_cover += 1
            continue

        md_chunk = pymupdf4llm.to_markdown(
            doc,
            pages=[page_num],
            show_progress=False,
        )

        if "�" in md_chunk:
            # pymupdf4llm 이 일부 원문자를 U+FFFD 로 치환 → raw 텍스트 사용
            fixed = _apply_circle_subs(raw_text)
            parts.append(
                f"\n\n<!-- page {page_num + 1} (raw text fallback) -->\n\n{fixed}\n"
            )
            fallback_raw += 1
        else:
            # 정상 추출된 페이지 — 혹시 pymupdf4llm 이 원문자를 한글 그대로
            # 남겨뒀다면 치환 한 번 더 적용 (일반적으로 이 경로엔 해당 없음)
            parts.append(_apply_circle_subs(md_chunk))
            kept_md += 1

    doc.close()
    merged = _strip_noise("\n".join(parts))
    out_path.write_text(merged, encoding="utf-8")
    elapsed = time.perf_counter() - start
    size_kb = out_path.stat().st_size / 1024

    stats = {
        "pages": total_pages,
        "skipped_cover": skipped_cover,
        "fallback_raw": fallback_raw,
        "kept_md": kept_md,
        "elapsed": elapsed,
        "size_kb": size_kb,
    }
    logger.info(
        "[%s] %d pages (md=%d, raw_fallback=%d, cover_skipped=%d) "
        "-> %s (%.1f KB, %.1fs)",
        pdf_path.name,
        total_pages,
        kept_md,
        fallback_raw,
        skipped_cover,
        out_path.name,
        size_kb,
        elapsed,
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default="data/raw", help="PDF 원본 디렉터리")
    parser.add_argument("--out", default="data/samples", help="Markdown 출력 디렉터리")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 .md 가 있어도 덮어쓴다",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    raw_dir = Path(args.raw)
    out_dir = Path(args.out)
    if not raw_dir.exists():
        logger.error("원본 디렉터리가 없습니다: %s", raw_dir)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(raw_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning("변환할 PDF 가 없습니다: %s", raw_dir)
        return 0

    logger.info("PDF %d개 변환 시작 (%s -> %s)", len(pdfs), raw_dir, out_dir)
    for pdf in pdfs:
        out = out_dir / f"{pdf.stem}.md"
        if out.exists() and not args.overwrite:
            logger.info("[skip] %s (이미 존재, --overwrite 로 강제 변환)", out.name)
            continue
        convert(pdf, out)

    logger.info("완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
