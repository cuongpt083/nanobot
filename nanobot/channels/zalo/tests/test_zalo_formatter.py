"""Unit tests for Zalo markdown formatting and styles extraction."""

from nanobot.channels.zalo.zalo_formatter import (
    format_and_split_for_zalo,
    format_for_zalo,
    utf16_len,
)


def test_format_empty() -> None:
    text, styles = format_for_zalo("")
    assert text == ""
    assert styles == []


def test_format_headings() -> None:
    md = "# Heading 1\n## Heading 2\n### Heading 3"
    text, styles = format_for_zalo(md)

    assert "📌 Heading 1" in text
    assert "📌 Heading 2" in text
    assert "🔹 Heading 3" in text

    # Verify styles contain bold and big for h1, bold for h2/h3
    b_styles = [s for s in styles if s["st"] == "b"]
    assert len(b_styles) == 3
    big_styles = [s for s in styles if s["st"] == "f_18"]
    assert len(big_styles) == 1


def test_format_bold_italic_strike() -> None:
    md = "Đây là **đậm** và *nghiêng* cùng ~~gạch~~ và ***cả hai***."
    text, styles = format_for_zalo(md)

    assert "**" not in text
    assert "~~" not in text
    assert "Đây là đậm và nghiêng cùng gạch và cả hai." == text

    # Check bold style for "đậm"
    bold_spans = [s for s in styles if s["st"] == "b"]
    assert any(s["len"] == utf16_len("đậm") for s in bold_spans)

    # Check italic style for "nghiêng"
    italic_spans = [s for s in styles if s["st"] == "i"]
    assert any(s["len"] == utf16_len("nghiêng") for s in italic_spans)

    # Check strike style for "gạch"
    strike_spans = [s for s in styles if s["st"] == "s"]
    assert any(s["len"] == utf16_len("gạch") for s in strike_spans)


def test_format_lists_and_blockquotes() -> None:
    md = "- Item 1\n* Item 2\n+ Item 3\n\n> Trích dẫn quan trọng"
    text, styles = format_for_zalo(md)

    assert "• Item 1" in text
    assert "• Item 2" in text
    assert "• Item 3" in text
    assert "▎ Trích dẫn quan trọng" in text

    # Blockquote should have italic style
    i_styles = [s for s in styles if s["st"] == "i"]
    assert len(i_styles) >= 1


def test_format_tables() -> None:
    md = """| Sản phẩm | Giá trị |
| --- | --- |
| Protein | 25g |
| BCAA | 5g |"""
    text, styles = format_for_zalo(md)

    assert "• Sản phẩm: Protein · Giá trị: 25g" in text
    assert "• Sản phẩm: BCAA · Giá trị: 5g" in text
    assert "|" not in text


def test_format_code_block() -> None:
    md = "```python\ndef hello():\n    return 'world'\n```"
    text, styles = format_for_zalo(md)

    assert "[Mã nguồn: python]" in text
    assert "  def hello():" in text
    assert "  return 'world'" in text
    assert "```" not in text


def test_format_links_and_images() -> None:
    md = "Xem tại [nanobot](https://nanobot.ai) hoặc [https://link.com](https://link.com) và ![Logo](https://img.png)"
    text, styles = format_for_zalo(md)

    assert "nanobot (https://nanobot.ai)" in text
    assert "https://link.com" in text
    assert "[Hình ảnh: Logo] (https://img.png)" in text


def test_utf16_offsets_with_emojis() -> None:
    # Emojis take 2 UTF-16 code units
    md = "📌 Chào **bạn**"
    text, styles = format_for_zalo(md)

    assert text == "📌 Chào bạn"
    # '📌' (2) + ' ' (1) + 'Chào' (4) + ' ' (1) = 8 UTF-16 code units
    b_style = next(s for s in styles if s["st"] == "b")
    assert b_style["start"] == 8
    assert b_style["len"] == utf16_len("bạn")


def test_format_br_tags() -> None:
    # 1. Plain text with <br>, <br/>, <br /> and case insensitivity
    md = "Dòng 1<br>Dòng 2<br/>Dòng 3<br />Dòng 4<BR>Dòng 5"
    text, styles = format_for_zalo(md)
    assert text == "Dòng 1\nDòng 2\nDòng 3\nDòng 4\nDòng 5"

    # 2. Consecutive <br><br> creates empty line separation
    md_consecutive = "Đoạn 1<br><br>Đoạn 2"
    text_c, _ = format_for_zalo(md_consecutive)
    assert text_c == "Đoạn 1\n\nĐoạn 2"

    # 3. <br> inside lists
    md_list = "- Mục 1<br>- Mục 2"
    text_l, _ = format_for_zalo(md_list)
    assert "• Mục 1\n• Mục 2" in text_l

    # 4. <br> inside tables
    md_table = """| Cột A | Cột B |
| --- | --- |
| Giá trị 1 | Chi tiết A<br>Chi tiết B |"""
    text_t, _ = format_for_zalo(md_table)
    assert "• Cột A: Giá trị 1 · Cột B: Chi tiết A\n  Chi tiết B" in text_t
    assert "<br>" not in text_t

    # 5. <br> inside code block should remain verbatim
    md_code = "```html\n<div><br>Nội dung</div>\n```"
    text_code, _ = format_for_zalo(md_code)
    assert "<div><br>Nội dung</div>" in text_code


def test_format_and_split_short_content() -> None:
    md = "# Tiêu đề ngắn\nĐây là **nội dung ngắn**."
    chunks = format_and_split_for_zalo(md, max_len=1200)
    assert len(chunks) == 1
    text, styles = chunks[0]
    assert "📌 Tiêu đề ngắn" in text
    assert "nội dung ngắn" in text
    assert len(styles) >= 2


def test_format_and_split_long_content_with_tables() -> None:
    table_rows = "\n".join(
        f"| Chỉ số {i} | {40 + i} kg | 45-55 kg | Đánh giá {i} | Gợi ý định hướng cụ thể số {i} |"
        for i in range(15)
    )
    md = (
        "# Báo cáo phân tích chỉ số\n\n"
        "Chào bạn, dưới đây là bảng phân tích toàn diện các chỉ số sức khỏe:\n\n"
        "| Chỉ số | Kết quả | Chuẩn | Đánh giá | Gợi ý |\n"
        "| :--- | :--- | :--- | :--- | :--- |\n"
        f"{table_rows}\n\n"
        "### Lời khuyên chung\n"
        "- Hãy uống đủ **nước** mỗi ngày.\n"
        "- Tập thể dục ít nhất *30 phút* mỗi ngày.\n"
    )

    chunks = format_and_split_for_zalo(md, max_len=600)
    assert len(chunks) > 1

    for idx, (text, styles) in enumerate(chunks):
        assert len(text) <= 650, f"Chunk {idx} len {len(text)} exceeds max_len"
        t_utf16 = utf16_len(text)
        for s in styles:
            assert s["start"] >= 0, f"Negative start in chunk {idx}: {s}"
            assert (
                s["start"] + s["len"] <= t_utf16
            ), f"Style overflow in chunk {idx}: {s} vs text utf16_len {t_utf16}"

    combined = " ".join(t for t, _ in chunks)
    for i in range(15):
        assert f"Chỉ số {i}" in combined


def test_format_and_split_giant_line() -> None:
    long_line = "Đây là một câu rất dài " * 50  # ~1200 chars
    chunks = format_and_split_for_zalo(long_line, max_len=300)
    assert len(chunks) > 1
    for text, _ in chunks:
        assert len(text) <= 350


def test_format_math_latex_cleaned() -> None:
    md = "Mức calo mục tiêu (ước tính): $\\sim 1150 - 1250\\text{ kcal/ngày}$"
    text, styles = format_for_zalo(md)
    assert "\\sim" not in text
    assert "\\text" not in text
    assert "~ 1150 - 1250 kcal/ngày" in text


def test_format_inequalities_and_percentages() -> None:
    md = "Kéo tỷ lệ nước lên $\\ge 50\\%$, duy trì $\\le 9.5$ và tăng nhẹ $0.5 - 1\\text{ kg}$ cơ nạc."
    text, styles = format_for_zalo(md)
    assert "\\ge" not in text
    assert "\\le" not in text
    assert "\\%" not in text
    assert "≥ 50%" in text
    assert "≤ 9.5" in text
    assert "0.5 - 1 kg cơ nạc" in text


def test_format_standalone_latex_without_delimiters() -> None:
    md = "Mức calo: \\sim 1150 - 1250\\text{ kcal/ngày} với tỷ lệ \\ge 50\\%"
    text, styles = format_for_zalo(md)
    assert "\\sim" not in text
    assert "\\text" not in text
    assert "\\ge" not in text
    assert "~ 1150 - 1250 kcal/ngày" in text
    assert "≥ 50%" in text


def test_format_math_symbols_and_greek() -> None:
    md = "Phương trình: $x^2 + y^2 = r^2$, $\\alpha = 30^\\circ$, $a \\times b \\pm c \\approx d$, $\\frac{x}{y}$"
    text, styles = format_for_zalo(md)
    assert "x² + y² = r²" in text
    assert "α = 30°" in text
    assert "a × b ± c ≈ d" in text
    assert "(x)/(y)" in text or "x/y" in text


def test_format_html_tags_cleaned() -> None:
    md = "Xin chào <b>bạn</b> và <i>đồng nghiệp</i> <span class='highlight'>chú ý</span>."
    text, styles = format_for_zalo(md)
    assert "<span" not in text
    assert "<b>" not in text
    assert "Xin chào bạn và đồng nghiệp chú ý." == text
    b_styles = [s for s in styles if s["st"] == "b"]
    assert len(b_styles) >= 1


def test_code_blocks_preserve_latex_verbatim() -> None:
    md = "```python\nval = '\\text{do not touch}'\n```\nNgoài mã: $\\ge 50\\%$"
    text, styles = format_for_zalo(md)
    assert "\\text{do not touch}" in text
    assert "≥ 50%" in text
