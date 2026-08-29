"""Code transformation utilities for LLM-generated python-pptx code.

Handles:
- Extracting code from LLM responses
- Sanitizing common LLM code mistakes
- Injecting image height-capping wrappers
- Stripping/analyzing code content
"""

import logging
import re

logger = logging.getLogger(__name__)


def extract_code(response: str) -> str | None:
    """Extract Python code from LLM response.

    Handles:
    - Standard ```python ... ``` blocks
    - Unclosed code fences (LLM output truncated)
    - Multiple code blocks (picks the one with build_slide)
    - Bare function definitions without fences
    - ``` (no language) code blocks
    """
    # Strategy 1: Standard ```python ... ``` blocks
    pattern = r"```python\s*\n(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        # Prefer the block containing build_slide
        for match in matches:
            if "def build_slide" in match:
                return match.strip()
        # Fall back to first block if it looks like code
        code = matches[0].strip()
        if "def build_slide" in code:
            return code

    # Strategy 2: ``` (no language tag) blocks
    pattern_plain = r"```\s*\n(.*?)```"
    matches_plain = re.findall(pattern_plain, response, re.DOTALL)
    for match in matches_plain:
        if "def build_slide" in match:
            return match.strip()

    # Strategy 3: Unclosed code fence (LLM output truncated mid-code)
    # Look for ```python followed by code but no closing ```
    unclosed = re.search(r"```python\s*\n(.*)", response, re.DOTALL)
    if unclosed:
        candidate = unclosed.group(1).strip()
        if "def build_slide" in candidate:
            # Remove any trailing ``` that might be partial
            candidate = re.sub(r'```\s*$', '', candidate).strip()
            # Verify we have a reasonable amount of code
            if len(candidate) > 100:
                logger.info("extract_code: recovered code from unclosed fence (%d chars)", len(candidate))
                return candidate

    # Strategy 4: Try without code fences — extract from "def build_slide" to end
    if "def build_slide" in response:
        lines = response.split("\n")
        in_func = False
        func_lines = []
        func_indent = 0
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("def build_slide"):
                in_func = True
                func_indent = len(line) - len(line.lstrip())
            if in_func:
                # Stop if we hit a markdown fence or non-code content
                if stripped.startswith("```"):
                    break
                # Stop if we hit a line with less indentation that isn't blank
                # (indicates end of function in a markdown context)
                if stripped and not stripped.startswith("#") and not stripped.startswith("def "):
                    current_indent = len(line) - len(line.lstrip())
                    if current_indent < func_indent and func_lines:
                        break
                func_lines.append(line)
        if func_lines:
            return "\n".join(func_lines)

    return None


def inject_image_height_cap(code: str) -> str:
    """Inject height-capping logic into generated code.

    The LLM often computes `display_h = display_w * aspect` without
    capping the result to the available vertical space. For portrait
    images (aspect > 1), this produces images extending far below
    the slide boundary (e.g. 11 inches on a 7.5-inch slide).

    Strategy: inject a wrapper function `_add_pic` into the code
    that intercepts add_picture calls and caps the height.
    """
    _helper = (
        'def _add_pic(_shapes, img_file, left, top, width=None, height=None):\n'
        '    import os as _os, struct as _struct\n'
        '    if not _os.path.exists(str(img_file)):\n'
        '        return None  # silently skip missing images\n'
        '    slide_w = 12192000\n'
        '    slide_h = 6858000\n'
        '    margin = 274320\n'
        '    # --- Contain mode: fit image within box preserving aspect ratio ---\n'
        '    if width is not None and height is not None:\n'
        '        try:\n'
        '            real_w, real_h = 0, 0\n'
        '            fname = str(img_file).lower()\n'
        '            if fname.endswith(".png"):\n'
        '                with open(str(img_file), "rb") as _f:\n'
        '                    _f.read(8)  # signature\n'
        '                    _f.read(4)  # IHDR length\n'
        '                    _f.read(4)  # chunk type\n'
        '                    _d = _f.read(8)\n'
        '                    real_w = _struct.unpack(">I", _d[0:4])[0]\n'
        '                    real_h = _struct.unpack(">I", _d[4:8])[0]\n'
        '            elif fname.endswith((".jpg", ".jpeg")):\n'
        '                with open(str(img_file), "rb") as _f:\n'
        '                    _f.read(2)  # SOI\n'
        '                    while True:\n'
        '                        marker = _f.read(2)\n'
        '                        if not marker or marker[0] != 0xFF: break\n'
        '                        if marker[1] in (0xC0, 0xC2):\n'
        '                            _f.read(3)  # length + precision\n'
        '                            real_h = _struct.unpack(">H", _f.read(2))[0]\n'
        '                            real_w = _struct.unpack(">H", _f.read(2))[0]\n'
        '                            break\n'
        '                        else:\n'
        '                            seg_len = _struct.unpack(">H", _f.read(2))[0]\n'
        '                            _f.read(seg_len - 2)\n'
        '            if real_w > 0 and real_h > 0:\n'
        '                real_aspect = real_h / real_w\n'
        '                box_w = int(width)\n'
        '                box_h = int(height)\n'
        '                # Contain mode: fit image within the box, preserving aspect ratio\n'
        '                # Try fitting by width first\n'
        '                fit_w = box_w\n'
        '                fit_h = int(box_w * real_aspect)\n'
        '                if fit_h > box_h:\n'
        '                    # Image is taller than box — fit by height instead\n'
        '                    fit_h = box_h\n'
        '                    fit_w = int(box_h / real_aspect)\n'
        '                width = fit_w\n'
        '                height = fit_h\n'
        '                # Center within original box\n'
        '                left = int(left) + (box_w - fit_w) // 2\n'
        '                top = int(top) + (box_h - fit_h) // 2\n'
        '        except Exception:\n'
        '            pass  # fall back to LLM-provided dimensions\n'
        '        t = int(top); h = int(height); w = int(width); l = int(left)\n'
        '        # Cap height to available vertical space\n'
        '        max_h = slide_h - t - margin\n'
        '        if max_h < 914400: max_h = 914400\n'
        '        if h > max_h and h > 0:\n'
        '            scale = max_h / h\n'
        '            width = int(w * scale); height = max_h\n'
        '            w = int(width); h = int(height)\n'
        '        # Cap width to available horizontal space\n'
        '        max_w = slide_w - l - margin\n'
        '        if max_w < 914400: max_w = 914400\n'
        '        if w > max_w and w > 0:\n'
        '            scale = max_w / w\n'
        '            width = int(w * scale); height = int(h * scale)\n'
        '    return _shapes.add_picture(img_file, left, top, width=width, height=height)\n'
    )

    # Insert helper at top of function body (after docstring if present)
    lines = code.split('\n')
    insert_idx = 0
    for i, line in enumerate(lines):
        if 'def build_slide' in line:
            insert_idx = i + 1
            # Skip docstring — look for triple quotes
            rest = '\n'.join(lines[i+1:])
            stripped_rest = rest.lstrip()
            if stripped_rest.startswith('"""') or stripped_rest.startswith("'''"):
                quote = '"""' if stripped_rest.startswith('"""') else "'''"
                # Find closing quote
                first_line_after_def = lines[i+1].strip()
                if first_line_after_def.count(quote) >= 2:
                    # Single-line docstring
                    insert_idx = i + 2
                else:
                    for j in range(i + 2, len(lines)):
                        if quote in lines[j]:
                            insert_idx = j + 1
                            break
            break

    indented = '\n'.join(
        '    ' + ln if ln.strip() else ''
        for ln in _helper.strip().split('\n')
    )
    lines.insert(insert_idx, indented)

    # Replace slide.shapes.add_picture( -> _add_pic(slide.shapes,
    result = '\n'.join(lines)
    result = re.sub(
        r'slide\.shapes\.add_picture\(',
        '_add_pic(slide.shapes, ',
        result,
    )
    return result


def sanitize_code(code: str) -> str:
    """Fix common LLM code mistakes before execution.

    Minimal sanitization — only safety-critical transforms:
    - Strip markdown **bold** from string literals (renders as literal asterisks)
    - Strip redundant pptx/stdlib imports (already in exec namespace)
    - Block slide creation (generated code must not add slides)
    - Fix font.color.rgb for PPTAgent pptx fork compatibility
    """
    # -- Strip markdown **bold** from string literals --
    # The LLM often writes p.text = "- **Bold text** normal" using markdown.
    # python-pptx renders ** as literal asterisks. Replace with plain text.
    def _strip_markdown_bold(match):
        """Remove ** pairs from a quoted string."""
        quote_char = match.group(1)  # ' or "
        content = match.group(2)
        cleaned = content.replace('**', '')
        return f'{quote_char}{cleaned}{quote_char}'

    # Match single-quoted or double-quoted strings containing **
    code = re.sub(
        r'''(["'])((?:(?!\1).)*\*\*(?:(?!\1).)*)\1''',
        _strip_markdown_bold,
        code,
    )

    # Remove inline imports ONLY for symbols already provided in exec_globals.
    _provided_pptx_symbols = {
        "Inches", "Pt", "Emu", "RGBColor", "PP_ALIGN",
        "MSO_ANCHOR", "MSO_AUTO_SIZE", "MSO_SHAPE",
        "CategoryChartData", "XL_CHART_TYPE",
    }
    _provided_stdlib = {"Path", "os"}

    def _should_strip_import(line: str) -> bool:
        """Return True only if every imported symbol is already provided."""
        stripped = line.strip()
        m = re.match(r'^from\s+pptx[\w.]*\s+import\s+(.+)$', stripped)
        if m:
            symbols = {s.strip().split(' as ')[-1].strip()
                       for s in m.group(1).split(',')}
            return symbols.issubset(_provided_pptx_symbols)
        if re.match(r'^import\s+pptx', stripped):
            return True
        m = re.match(r'^from\s+pathlib\s+import\s+(.+)$', stripped)
        if m:
            symbols = {s.strip().split(' as ')[-1].strip()
                       for s in m.group(1).split(',')}
            return symbols.issubset(_provided_stdlib)
        if re.match(r'^import\s+os\b', stripped):
            return True
        return False

    lines = code.split('\n')
    processed = []
    for line in lines:
        if _should_strip_import(line):
            indent = len(line) - len(line.lstrip())
            processed.append(' ' * indent + 'pass  # import handled by runtime')
        else:
            processed.append(line)
    code = '\n'.join(processed)

    # Block slide creation: generated code must NOT add new slides.
    if 'slides.add_slide' in code or 'add_slide(' in code:
        block_lines = code.split('\n')
        safe_lines = []
        skip_var = None
        for bl in block_lines:
            stripped_bl = bl.strip()
            m = re.match(r'^(\s*)(\w+)\s*=\s*.*\.slides\.add_slide\(', bl)
            if m or 'slides.add_slide(' in stripped_bl:
                if m:
                    skip_var = m.group(2)
                indent = len(bl) - len(bl.lstrip())
                safe_lines.append(' ' * indent + '# BLOCKED: slide creation removed by sanitizer')
                continue
            if skip_var and re.match(rf'^\s*{re.escape(skip_var)}\.', bl):
                continue
            safe_lines.append(bl)
        code = '\n'.join(safe_lines)
        logger.warning("Sanitizer: removed prs.slides.add_slide() calls from generated code")

    # -- Fix font.color.rgb for PPTAgent pptx fork compatibility --
    # The PPTAgent fork (python-pptx 1.0.4+PPTAgent) changed Font.color to
    # return str|None instead of ColorFormat, breaking the standard pattern:
    #   p.font.color.rgb = RGBColor(...)
    # Replace with the two-line pattern that works in both standard and fork:
    #   p.font.fill.solid()
    #   p.font.fill.fore_color.rgb = RGBColor(...)
    if '.font.color.rgb' in code:
        fc_lines = code.split('\n')
        fc_fixed = []
        for fcl in fc_lines:
            m = re.match(
                r'^(\s*)([\w.\[\]()]+)\.font\.color\.rgb\s*=\s*(.+)$',
                fcl,
            )
            if m:
                indent = m.group(1)
                accessor = m.group(2)
                rgb_value = m.group(3)
                fc_fixed.append(f'{indent}{accessor}.font.fill.solid()')
                fc_fixed.append(f'{indent}{accessor}.font.fill.fore_color.rgb = {rgb_value}')
            else:
                fc_fixed.append(fcl)
        code = '\n'.join(fc_fixed)

    return code


def strip_image_code(code: str) -> str:
    """Strip add_picture calls and associated blocks when no images are available.

    When no images are offered for a slide, the LLM sometimes still generates
    code that calls add_picture() with fabricated filenames.
    """
    # Remove entire if os.path.exists() blocks (image guard blocks)
    code = re.sub(
        r'^\s*if\s+os\.path\.exists\s*\([^)]+\)\s*:\s*\n(?:\s+.*\n)*',
        '',
        code,
        flags=re.MULTILINE,
    )

    lines = code.split('\n')
    cleaned = []

    for line in lines:
        stripped = line.strip()
        if any(pat in stripped for pat in [
            'add_picture(', '_add_pic(', 'add_picture (',
            'img_path =', 'img_path=',
        ]):
            continue
        if stripped.startswith('#') and any(kw in stripped.lower() for kw in [
            'image', 'figure', 'caption for image',
        ]):
            continue
        cleaned.append(line)

    return '\n'.join(cleaned)


def strip_comments(code: str) -> str:
    """Strip comment lines and inline comments from Python code to reduce tokens.

    Preserves string literals and blank lines are collapsed.
    """
    lines = code.split('\n')
    stripped = []
    for line in lines:
        stripped_line = line.lstrip()
        if stripped_line.startswith('#'):
            continue
        in_str = None
        result = []
        for i, ch in enumerate(line):
            if ch in ('"', "'") and (i == 0 or line[i-1] != '\\'):
                if in_str is None:
                    in_str = ch
                elif ch == in_str:
                    in_str = None
            if ch == '#' and in_str is None:
                break
            result.append(ch)
        clean = ''.join(result).rstrip()
        if clean or stripped:  # skip leading blank lines
            stripped.append(clean)
    while stripped and not stripped[-1]:
        stripped.pop()
    return '\n'.join(stripped)


def estimate_text_content(code: str) -> int:
    """Estimate the amount of text content in generated code.

    Sums the length of all string literals that look like slide content.
    """
    total = 0
    for m in re.finditer(r'\.text\s*=\s*["\'](.+?)["\']', code):
        total += len(m.group(1))
    for m in re.finditer(r'\.text\s*=\s*f["\'](.+?)["\']', code):
        total += len(m.group(1))
    for m in re.finditer(r'\.text\s*=\s*"""(.+?)"""', code, re.DOTALL):
        total += len(m.group(1))
    for m in re.finditer(r"\.text\s*=\s*'''(.+?)'''", code, re.DOTALL):
        total += len(m.group(1))
    return total


def extract_coordinates(code: str) -> tuple:
    """Extract all coordinate/size values from code for comparison.

    Returns a sorted tuple of (line_number, Inches/Pt values) so we can
    detect if a repair changed layout coordinates.
    """
    coords = []
    for i, line in enumerate(code.split('\n')):
        for m in re.finditer(r'Inches\(\s*([\d.]+)\s*\)', line):
            coords.append((i, 'Inches', m.group(1)))
        for m in re.finditer(r'Pt\(\s*([\d.]+)\s*\)', line):
            coords.append((i, 'Pt', m.group(1)))
        for m in re.finditer(r'Emu\(\s*([\d.]+)\s*\)', line):
            coords.append((i, 'Emu', m.group(1)))
    return tuple(sorted(coords))


def build_shape_name_map(code: str) -> str:
    """Parse generated code to build shape-name -> code-variable map.

    python-pptx auto-names shapes using a global counter (starting from 1)
    shared across all shape types on each slide.

    Returns a formatted string block for injection into the repair prompt.
    """
    patterns = [
        (r'^(\s*(\w+)\s*=\s*)?slide\.shapes\.add_textbox\((.+?)\)',
         "add_textbox"),
        (r'^(\s*(\w+)\s*=\s*)?slide\.shapes\.add_shape\(\s*MSO_SHAPE\.(\w+)',
         "add_shape"),
        (r'^(\s*(\w+)\s*=\s*)?slide\.shapes\.add_picture\((.+?)\)',
         "add_picture"),
        (r'^(\s*(\w+)\s*=\s*)?slide\.shapes\.add_table\((.+?)\)',
         "add_table"),
        (r'^(\s*(\w+)\s*=\s*)?slide\.shapes\.add_chart\((.+?)\)',
         "add_chart"),
    ]

    mso_to_name = {
        "RECTANGLE": "Rectangle",
        "ROUNDED_RECTANGLE": "Rounded Rectangle",
        "OVAL": "Oval",
        "DIAMOND": "Diamond",
        "RIGHT_ARROW": "Right Arrow",
        "DOWN_ARROW": "Down Arrow",
        "LEFT_ARROW": "Left Arrow",
        "UP_ARROW": "Up Arrow",
        "CHEVRON": "Chevron",
        "PENTAGON": "Pentagon",
        "HEXAGON": "Hexagon",
        "ISOSCELES_TRIANGLE": "Isosceles Triangle",
    }

    entries = []
    counter = 1

    lines = code.split("\n")
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for pattern, call_type in patterns:
            match = re.search(pattern, stripped)
            if not match:
                continue

            var_name = match.group(2) if match.group(2) else "(inline)"

            if call_type == "add_textbox":
                shape_name = f"TextBox {counter}"
            elif call_type == "add_shape":
                mso_type = match.group(3)
                base_name = mso_to_name.get(mso_type, mso_type.replace("_", " ").title())
                shape_name = f"{base_name} {counter}"
            elif call_type == "add_picture":
                shape_name = f"Picture {counter}"
            elif call_type == "add_table":
                shape_name = f"Table {counter}"
            elif call_type == "add_chart":
                shape_name = f"Chart {counter}"
            else:
                shape_name = f"Shape {counter}"

            text_hint = ""
            for look_ahead in range(1, min(8, len(lines) - line_num)):
                la_line = lines[line_num - 1 + look_ahead].strip()
                text_match = re.search(r'\.text\s*=\s*["\'](.+?)["\']', la_line)
                if text_match:
                    text_hint = text_match.group(1)[:60]
                    break
                comment_match = re.search(r'#\s*(.+)', la_line)
                if comment_match and not text_hint:
                    text_hint = comment_match.group(1).strip()[:40]

            inline_comment = ""
            comment_pos = stripped.find("#")
            if comment_pos > 0:
                inline_comment = stripped[comment_pos + 1:].strip()[:40]

            hint = text_hint or inline_comment or ""
            hint_str = f'  text: "{hint}"' if hint else ""

            entries.append(
                f'- "{shape_name}" -> line {line_num}: '
                f'variable `{var_name}`{hint_str}'
            )
            counter += 1
            break

    if not entries:
        return ""

    header = (
        "## Shape Name Map (auto-generated shape names -> code locations)\n"
        "The evaluator uses python-pptx auto-assigned shape names. "
        "Use this map to identify which code variable creates each named shape:\n"
    )
    return header + "\n".join(entries)
