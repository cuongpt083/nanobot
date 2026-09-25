"""Markdown to Zalo text and style formatter."""

from __future__ import annotations

import re
from typing import Any

_INLINE_RE = re.compile(
    r"(?P<bold_italic>(?:\*\*\*|___)(?P<bi_txt1>.+?)(?:\*\*\*|___)|(?:\*\*_|__\*)(?P<bi_txt2>.+?)(?:_\*\*|\*__))"
    r"|(?P<bold>(?:\*\*|__)(?P<b_txt1>.+?)(?:\*\*|__))"
    r"|(?P<italic>\*(?P<i_txt1>[^\*\n]+?)\*|(?<!\w)_(?!\s)(?P<i_txt2>[^_\n]+?)(?<!\s)_(?!\w))"
    r"|(?P<strike>~~(?P<s_txt>.+?)~~)"
    r"|(?P<code>`(?P<c_txt>[^`\n]+)`)"
)

_SUP_MAP = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ",
    "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "i": "ⁱ", "j": "ʲ",
    "k": "ᵏ", "l": "ˡ", "m": "ᵐ", "n": "ⁿ", "o": "ᵒ",
    "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ",
    "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ",
}

_SUB_MAP = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ",
    "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ",
    "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ",
    "v": "ᵥ", "x": "ₓ",
}

_LATEX_SYMBOLS: list[tuple[str, str]] = [
    # Degree & temperature
    (r"\\degree([CF])\b", r"°\1"),
    (r"\^\{?\\circ\}?|\\degree(?![a-zA-Z])", "°"),
    # Relations & Operators
    (r"\\ge(?:q)?(?![a-zA-Z])", "≥"),
    (r"\\le(?:q)?(?![a-zA-Z])", "≤"),
    (r"\\sim(?![a-zA-Z])", "~"),
    (r"\\approx(?![a-zA-Z])", "≈"),
    (r"\\pm(?![a-zA-Z])", "±"),
    (r"\\mp(?![a-zA-Z])", "∓"),
    (r"\\times(?![a-zA-Z])", "×"),
    (r"\\div(?![a-zA-Z])", "÷"),
    (r"\\ne(?:q)?(?![a-zA-Z])", "≠"),
    (r"\\equiv(?![a-zA-Z])", "≡"),
    (r"\\cdot(?![a-zA-Z])", "·"),
    (r"\\bullet(?![a-zA-Z])", "•"),
    (r"\\(?:dots|ldots|cdots|vdots|ddots)(?![a-zA-Z])", "..."),
    # Arrows
    (r"\\(?:to|rightarrow)(?![a-zA-Z])", "→"),
    (r"\\leftarrow(?![a-zA-Z])", "←"),
    (r"\\Rightarrow(?![a-zA-Z])", "⇒"),
    (r"\\Leftarrow(?![a-zA-Z])", "⇐"),
    (r"\\leftrightarrow(?![a-zA-Z])", "↔"),
    (r"\\iff(?![a-zA-Z])", "⇔"),
    (r"\\implies(?![a-zA-Z])", "⇒"),
    # Math sets & logic
    (r"\\infty(?![a-zA-Z])", "∞"),
    (r"\\sum(?![a-zA-Z])", "∑"),
    (r"\\prod(?![a-zA-Z])", "∏"),
    (r"\\int(?![a-zA-Z])", "∫"),
    (r"\\iint(?![a-zA-Z])", "∬"),
    (r"\\partial(?![a-zA-Z])", "∂"),
    (r"\\nabla(?![a-zA-Z])", "∇"),
    (r"\\in(?![a-zA-Z])", "∈"),
    (r"\\notin(?![a-zA-Z])", "∉"),
    (r"\\subset(?![a-zA-Z])", "⊂"),
    (r"\\subseteq(?![a-zA-Z])", "⊆"),
    (r"\\cup(?![a-zA-Z])", "∪"),
    (r"\\cap(?![a-zA-Z])", "∩"),
    (r"\\emptyset(?![a-zA-Z])", "∅"),
    (r"\\forall(?![a-zA-Z])", "∀"),
    (r"\\exists(?![a-zA-Z])", "∃"),
    # Greek letters (lowercase)
    (r"\\alpha(?![a-zA-Z])", "α"),
    (r"\\beta(?![a-zA-Z])", "β"),
    (r"\\gamma(?![a-zA-Z])", "γ"),
    (r"\\delta(?![a-zA-Z])", "δ"),
    (r"\\(?:epsilon|varepsilon)(?![a-zA-Z])", "ε"),
    (r"\\zeta(?![a-zA-Z])", "ζ"),
    (r"\\eta(?![a-zA-Z])", "η"),
    (r"\\(?:theta|vartheta)(?![a-zA-Z])", "θ"),
    (r"\\iota(?![a-zA-Z])", "ι"),
    (r"\\kappa(?![a-zA-Z])", "κ"),
    (r"\\lambda(?![a-zA-Z])", "λ"),
    (r"\\mu(?![a-zA-Z])", "μ"),
    (r"\\nu(?![a-zA-Z])", "ν"),
    (r"\\xi(?![a-zA-Z])", "ξ"),
    (r"\\pi(?![a-zA-Z])", "π"),
    (r"\\rho(?![a-zA-Z])", "ρ"),
    (r"\\sigma(?![a-zA-Z])", "σ"),
    (r"\\tau(?![a-zA-Z])", "τ"),
    (r"\\upsilon(?![a-zA-Z])", "υ"),
    (r"\\(?:phi|varphi)(?![a-zA-Z])", "φ"),
    (r"\\chi(?![a-zA-Z])", "χ"),
    (r"\\psi(?![a-zA-Z])", "ψ"),
    (r"\\omega(?![a-zA-Z])", "ω"),
    # Greek letters (uppercase)
    (r"\\Gamma(?![a-zA-Z])", "Γ"),
    (r"\\Delta(?![a-zA-Z])", "Δ"),
    (r"\\Theta(?![a-zA-Z])", "Θ"),
    (r"\\Lambda(?![a-zA-Z])", "Λ"),
    (r"\\Xi(?![a-zA-Z])", "Ξ"),
    (r"\\Pi(?![a-zA-Z])", "Π"),
    (r"\\Sigma(?![a-zA-Z])", "Σ"),
    (r"\\Phi(?![a-zA-Z])", "Φ"),
    (r"\\Psi(?![a-zA-Z])", "Ψ"),
    (r"\\Omega(?![a-zA-Z])", "Ω"),
]


def utf16_len(text: str) -> int:
    """Calculate the length of a string in UTF-16 code units (as expected by Zalo)."""
    return len(text.encode("utf-16-le")) // 2


def _extract_braced_group(text: str, start_idx: int) -> tuple[str, int] | None:
    """Extract content inside balanced { ... } starting at start_idx (which must be '{').

    Returns (content, end_idx) where end_idx is the index right after closing '}'.
    """
    if start_idx >= len(text) or text[start_idx] != "{":
        return None
    depth = 0
    content: list[str] = []
    for i in range(start_idx, len(text)):
        char = text[i]
        if char == "{":
            depth += 1
            if depth > 1:
                content.append(char)
        elif char == "}":
            depth -= 1
            if depth == 0:
                return "".join(content), i + 1
            content.append(char)
        else:
            content.append(char)
    return None


def clean_latex_math(text: str) -> str:
    """Convert LaTeX math constructs and symbols to clean, readable Unicode text."""
    if not text:
        return ""

    # 0. Environments & linebreaks inside math
    text = re.sub(r"\\(?:begin|end)\{[a-zA-Z*]+\}", "", text)
    text = re.sub(r"\\\\", "\n", text)

    # Ensure space between number and unit wrapper: e.g. 100\text{kg} -> 100 kg
    text = re.sub(
        r"(\d)\s*\\(?:text|mathrm|mathbf|mathit|operatorname|textbf|textit|bm|boldsymbol)\{([a-zA-Z])",
        r"\1 \2",
        text,
    )

    # 1. Strip wrappers: \text{...}, \mathrm{...}, etc. with balanced braces
    wrapper_re = re.compile(
        r"\\(?:text|mathrm|mathbf|mathit|operatorname|textbf|textit|bm|boldsymbol|underline)\b"
    )
    while True:
        m = wrapper_re.search(text)
        if not m:
            break
        idx = m.start()
        after = m.end()
        while after < len(text) and text[after] in " \t":
            after += 1
        arg_res = _extract_braced_group(text, after)
        if not arg_res:
            break
        arg, end_idx = arg_res
        text = text[:idx] + arg + text[end_idx:]

    # 2. Fractions: \frac{a}{b} -> (a)/(b) with balanced braces
    while True:
        idx = text.find(r"\frac")
        if idx == -1:
            break
        after_frac = idx + len(r"\frac")
        while after_frac < len(text) and text[after_frac] in " \t":
            after_frac += 1
        num_res = _extract_braced_group(text, after_frac)
        if not num_res:
            break
        num, den_start = num_res
        while den_start < len(text) and text[den_start] in " \t":
            den_start += 1
        den_res = _extract_braced_group(text, den_start)
        if not den_res:
            break
        den, end_idx = den_res
        num_clean = clean_latex_math(num)
        den_clean = clean_latex_math(den)
        text = text[:idx] + f"({num_clean})/({den_clean})" + text[end_idx:]

    # 3. Square roots: \sqrt[n]{x} -> (n)√(x), \sqrt{x} -> √(x) with balanced braces
    while True:
        m = re.search(r"\\sqrt\[([^\]]+)\]", text)
        if not m:
            break
        deg = m.group(1)
        idx = m.start()
        after = m.end()
        while after < len(text) and text[after] in " \t":
            after += 1
        arg_res = _extract_braced_group(text, after)
        if not arg_res:
            break
        arg, end_idx = arg_res
        arg_clean = clean_latex_math(arg)
        text = text[:idx] + f"({deg})√({arg_clean})" + text[end_idx:]

    while True:
        idx = text.find(r"\sqrt")
        if idx == -1:
            break
        after = idx + len(r"\sqrt")
        while after < len(text) and text[after] in " \t":
            after += 1
        arg_res = _extract_braced_group(text, after)
        if not arg_res:
            break
        arg, end_idx = arg_res
        arg_clean = clean_latex_math(arg)
        text = text[:idx] + f"√({arg_clean})" + text[end_idx:]

    # 4. Symbol replacements
    for pattern, repl in _LATEX_SYMBOLS:
        text = re.sub(pattern, repl, text)

    # 5. Sizing & delimiters: \left, \right, \big, etc.
    text = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)\b", "", text)

    # 6. Spacing: \, \: \; \! \quad \qquad \enspace
    text = re.sub(r"\\[,;:!]", " ", text)
    text = re.sub(r"\\(?:quad|qquad|enspace)\b", " ", text)

    # 7. Superscripts and subscripts
    def _replace_sup(m: re.Match[str]) -> str:
        chars = m.group(1)
        if all(c in _SUP_MAP for c in chars):
            return "".join(_SUP_MAP[c] for c in chars)
        return f"^({chars})"

    def _replace_sub(m: re.Match[str]) -> str:
        chars = m.group(1)
        if all(c in _SUB_MAP for c in chars):
            return "".join(_SUB_MAP[c] for c in chars)
        return f"_({chars})"

    text = re.sub(r"\^\{([^{}]+)\}", _replace_sup, text)
    text = re.sub(
        r"\^([0-9a-zA-Z+-=()])",
        lambda m: _SUP_MAP.get(m.group(1), f"^{m.group(1)}"),
        text,
    )
    text = re.sub(r"_\{([^{}]+)\}", _replace_sub, text)
    text = re.sub(
        r"_([0-9a-zA-Z+-=()])",
        lambda m: _SUB_MAP.get(m.group(1), f"_{m.group(1)}"),
        text,
    )

    # 8. Escaped characters: \%, \$, \&, \#, \_, \{, \}
    text = re.sub(r"\\([%&#${}_])", r"\1", text)

    # 9. Clean any remaining lone curly braces
    while re.search(r"\{([^{}]*)\}", text):
        text = re.sub(r"\{([^{}]*)\}", r"\1", text)

    # 10. Clean lone backslashes before words
    text = re.sub(r"\\([a-zA-Z]+)", r"\1", text)

    # 11. Normalize horizontal spaces
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def clean_html_tags(text: str) -> str:
    """Convert inline HTML formatting tags to Markdown syntax or strip unneeded tags."""
    # Convert formatting tags to Markdown
    text = re.sub(r"(?i)<(?:b|strong)>(.*?)</(?:b|strong)>", r"**\1**", text)
    text = re.sub(r"(?i)<(?:i|em)>(.*?)</(?:i|em)>", r"*\1*", text)
    text = re.sub(r"(?i)<(?:del|s|strike)>(.*?)</(?:del|s|strike)>", r"~~\1~~", text)
    text = re.sub(r"(?i)<code>(.*?)</code>", r"`\1`", text)
    text = re.sub(r"(?i)<(?:u|ins)>(.*?)</(?:u|ins)>", r"\1", text)

    # Strip span, div, p, center, font, etc.
    text = re.sub(
        r"(?i)</?(?:span|div|p|center|font|small|big|header|footer|section|article)[^>]*>",
        "",
        text,
    )

    # Strip any remaining stray tags except <br>
    text = re.sub(r"(?i)<(?!/?br\s*/?>)[^>]+>", "", text)
    return text


def split_markdown_table_row(line: str) -> list[str]:
    """Split one Markdown pipe-table row into stripped cells."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def is_markdown_table_separator_row(cells: list[str]) -> bool:
    """True if cells look like a markdown table separator row."""
    return bool(any(c for c in cells)) and all(re.match(r"^:?-+:?$", c) for c in cells if c)


def convert_markdown_table_to_labeled_rows(table_text: str) -> str:
    """Convert a Markdown pipe table to labeled rows."""
    lines = [ln.strip() for ln in table_text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return table_text
    headers = split_markdown_table_row(lines[0])
    start = 2 if is_markdown_table_separator_row(split_markdown_table_row(lines[1])) else 1
    rows: list[str] = []
    for line in lines[start:]:
        cells = split_markdown_table_row(line)
        cells = (cells + [""] * len(headers))[: len(headers)]
        parts = [f"**{headers[i]}**: {cells[i]}" for i in range(len(headers))]
        if parts:
            rows.append(" · ".join(parts))
    return "\n".join(rows)


def _parse_lines(content: str) -> list[dict[str, Any]]:
    """Parse Markdown content into structured lines with table, math, and code expansions."""
    text = content.replace("\r\n", "\n").replace("\r", "\n")

    # 1. Protect code blocks from HTML and math transformations
    code_blocks: list[str] = []

    def _save_code(m: re.Match[str]) -> str:
        code_blocks.append(m.group(0))
        return f"\x00C{len(code_blocks) - 1}C\x00"

    text = re.sub(r"```[^\n]*\n[\s\S]*?```", _save_code, text)

    inline_codes: list[str] = []

    def _save_inline_code(m: re.Match[str]) -> str:
        inline_codes.append(m.group(0))
        return f"\x00I{len(inline_codes) - 1}I\x00"

    text = re.sub(r"`[^`\n]+`", _save_inline_code, text)

    # 2. Clean HTML tags
    text = clean_html_tags(text)

    # 3. Clean math blocks $$...$$ and $...$
    text = re.sub(r"\\\$", "\x00DOLLAR\x00", text)
    text = re.sub(r"\$\$([\s\S]+?)\$\$", lambda m: clean_latex_math(m.group(1)), text)
    text = re.sub(r"\$([^\$\n]+)\$", lambda m: clean_latex_math(m.group(1)), text)
    text = text.replace("\x00DOLLAR\x00", "$")

    # 4. Clean standalone LaTeX math commands/symbols
    text = clean_latex_math(text)

    # 5. Clean images: ![alt](url) -> [Hình ảnh: alt] (url) or [Hình ảnh] (url)
    text = re.sub(
        r"!\[([^\]]*)\]\((https?://[^\s)]+)\)",
        lambda m: f"[Hình ảnh: {m.group(1)}] ({m.group(2)})"
        if m.group(1)
        else f"[Hình ảnh] ({m.group(2)})",
        text,
    )

    # 6. Convert hyperlinks: [label](url) -> label (url) or url if label == url
    def _sub_link(m: re.Match[str]) -> str:
        label = m.group(1).strip()
        url = m.group(2).strip()
        return url if label == url else f"{label} ({url})"

    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", _sub_link, text)

    # 7. Restore protected code blocks and inline code
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00I{i}I\x00", code)
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00C{i}C\x00", block)

    raw_lines = text.split("\n")
    processed_lines: list[dict[str, Any]] = []

    in_code = False
    table_buffer: list[str] = []

    def flush_table() -> None:
        nonlocal table_buffer
        if not table_buffer:
            return
        tbl_text = "\n".join(table_buffer)
        table_buffer = []
        converted = convert_markdown_table_to_labeled_rows(tbl_text)
        for row in converted.split("\n"):
            if row.strip():
                clean_row = re.sub(r"(?i)[ \t]*<br\s*/?>[ \t]*", "\n  ", row.strip())
                for subline in clean_row.split("\n"):
                    if subline.strip():
                        if not subline.startswith("  ") and not subline.startswith("•"):
                            processed_lines.append(
                                {"text": f"• {subline.strip()}", "line_styles": [], "verbatim": False}
                            )
                        else:
                            processed_lines.append(
                                {"text": subline, "line_styles": [], "verbatim": False}
                            )

    for line in raw_lines:
        stripped = line.strip()

        # Fenced code block delimiter
        if stripped.startswith("```"):
            flush_table()
            if not in_code:
                in_code = True
                lang = stripped[3:].strip()
                header = f"[Mã nguồn: {lang}]" if lang else "[Mã nguồn]"
                processed_lines.append(
                    {"text": header, "line_styles": ["b"], "verbatim": True}
                )
            else:
                in_code = False
            continue

        if in_code:
            processed_lines.append(
                {"text": f"  {line}", "line_styles": [], "verbatim": True}
            )
            continue

        # Markdown table row
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 2:
            table_buffer.append(line)
            continue
        else:
            flush_table()

        # Convert <br> tags in non-code, non-table lines into multiple lines
        sublines = (
            re.split(r"(?i)[ \t]*<br\s*/?>[ \t]*", line)
            if re.search(r"(?i)<br\s*/?>", line)
            else [line]
        )

        for subline in sublines:
            # Horizontal rule (---, ***, ___)
            if re.match(r"^\s*[-*_]{3,}\s*$", subline):
                processed_lines.append(
                    {"text": "───────────────────", "line_styles": [], "verbatim": True}
                )
                continue

            # Headings
            h1_m = re.match(r"^#\s+(.*)$", subline)
            if h1_m:
                processed_lines.append(
                    {
                        "text": f"📌 {h1_m.group(1).strip()}",
                        "line_styles": ["b", "f_18"],
                        "verbatim": False,
                    }
                )
                continue

            h2_m = re.match(r"^##\s+(.*)$", subline)
            if h2_m:
                processed_lines.append(
                    {
                        "text": f"📌 {h2_m.group(1).strip()}",
                        "line_styles": ["b"],
                        "verbatim": False,
                    }
                )
                continue

            h3_m = re.match(r"^###+\s+(.*)$", subline)
            if h3_m:
                processed_lines.append(
                    {
                        "text": f"🔹 {h3_m.group(1).strip()}",
                        "line_styles": ["b"],
                        "verbatim": False,
                    }
                )
                continue

            # Blockquote (> quote)
            bq_m = re.match(r"^>\s*(.*)$", subline)
            if bq_m:
                processed_lines.append(
                    {"text": f"▎ {bq_m.group(1)}", "line_styles": ["i"], "verbatim": False}
                )
                continue

            # Bullet lists (-, *, +)
            li_m = re.match(r"^(\s*)[*+-]\s+(.*)$", subline)
            if li_m:
                indent = li_m.group(1)
                item = li_m.group(2)
                task_m = re.match(r"^\[([ xX])\]\s+(.*)$", item)
                if task_m:
                    check = "✅ " if task_m.group(1).lower() == "x" else "◻️ "
                    item = check + task_m.group(2)
                processed_lines.append(
                    {"text": f"{indent}• {item}", "line_styles": [], "verbatim": False}
                )
                continue

            # Standard line
            processed_lines.append({"text": subline, "line_styles": [], "verbatim": False})

    flush_table()
    return processed_lines


def _split_long_lines(
    processed_lines: list[dict[str, Any]], max_len: int
) -> list[dict[str, Any]]:
    """Split any single line exceeding max_len into smaller chunks."""
    result: list[dict[str, Any]] = []
    for pline in processed_lines:
        text = pline["text"]
        if len(text) <= max_len:
            result.append(pline)
            continue

        start = 0
        while start < len(text):
            if len(text) - start <= max_len:
                sub = text[start:]
                start = len(text)
            else:
                cut = text.rfind(" ", start, start + max_len)
                if cut == -1 or cut <= start:
                    cut = start + max_len
                sub = text[start:cut]
                start = cut + 1 if cut < len(text) and text[cut] == " " else cut

            result.append(
                {
                    "text": sub,
                    "line_styles": pline.get("line_styles", []),
                    "verbatim": pline.get("verbatim", False),
                }
            )
    return result


def _render_lines_group(
    lines_group: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Render a sequence of structured lines into Zalo-compatible text and style spans."""
    out_parts: list[str] = []
    styles: list[dict[str, Any]] = []

    for i, pline in enumerate(lines_group):
        if i > 0:
            out_parts.append("\n")

        line_start = utf16_len("".join(out_parts))

        if pline["verbatim"]:
            out_parts.append(pline["text"])
        else:
            line_text = pline["text"]
            last_idx = 0
            for m in _INLINE_RE.finditer(line_text):
                m_start, m_end = m.span()
                out_parts.append(line_text[last_idx:m_start])
                curr_offset = utf16_len("".join(out_parts))

                if m.group("bold_italic"):
                    txt = m.group("bi_txt1") or m.group("bi_txt2")
                    out_parts.append(txt)
                    t_len = utf16_len(txt)
                    styles.append({"start": curr_offset, "len": t_len, "st": "b"})
                    styles.append({"start": curr_offset, "len": t_len, "st": "i"})
                elif m.group("bold"):
                    txt = m.group("b_txt1") or m.group("b_txt2")
                    out_parts.append(txt)
                    t_len = utf16_len(txt)
                    styles.append({"start": curr_offset, "len": t_len, "st": "b"})
                elif m.group("italic"):
                    txt = m.group("i_txt1") or m.group("i_txt2")
                    out_parts.append(txt)
                    t_len = utf16_len(txt)
                    styles.append({"start": curr_offset, "len": t_len, "st": "i"})
                elif m.group("strike"):
                    txt = m.group("s_txt")
                    out_parts.append(txt)
                    t_len = utf16_len(txt)
                    styles.append({"start": curr_offset, "len": t_len, "st": "s"})
                elif m.group("code"):
                    txt = m.group("c_txt")
                    out_parts.append(txt)
                last_idx = m_end

            out_parts.append(line_text[last_idx:])

        line_len = utf16_len("".join(out_parts)) - line_start
        for st in pline["line_styles"]:
            if line_len > 0:
                styles.append({"start": line_start, "len": line_len, "st": st})

    final_str = "".join(out_parts)
    return final_str, styles


def format_for_zalo(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Format Markdown content for clean display on Zalo with native text styling.

    Returns:
        tuple[str, list[dict[str, Any]]]: A tuple containing:
            - The cleaned, readable text stripped of raw Markdown tokens.
            - An array of Zalo style objects: `{"start": int, "len": int, "st": str}`.
    """
    if not content:
        return "", []

    lines = _parse_lines(content)
    return _render_lines_group(lines)


def format_and_split_for_zalo(
    content: str, max_len: int = 1200
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Format Markdown content and split into chunks of at most `max_len` characters.

    Each chunk contains clean text and corresponding relative style offsets,
    guaranteeing that neither text length nor style payload overflows Zalo limits.

    Returns:
        list[tuple[str, list[dict[str, Any]]]]: Chunks of (text, styles).
    """
    if not content:
        return [("", [])]

    raw_lines = _parse_lines(content)
    processed_lines = _split_long_lines(raw_lines, max_len=max_len)

    chunks: list[tuple[str, list[dict[str, Any]]]] = []
    curr_group: list[dict[str, Any]] = []
    curr_len = 0

    for pline in processed_lines:
        line_len = len(pline["text"]) + 1
        if curr_group and (curr_len + line_len > max_len):
            txt, st = _render_lines_group(curr_group)
            if txt.strip():
                chunks.append((txt, st))
            curr_group = [pline]
            curr_len = line_len
        else:
            curr_group.append(pline)
            curr_len += line_len

    if curr_group:
        txt, st = _render_lines_group(curr_group)
        if txt.strip() or not chunks:
            chunks.append((txt, st))

    return chunks or [("", [])]


__all__ = [
    "clean_html_tags",
    "clean_latex_math",
    "convert_markdown_table_to_labeled_rows",
    "format_and_split_for_zalo",
    "format_for_zalo",
    "is_markdown_table_separator_row",
    "split_markdown_table_row",
    "utf16_len",
]
