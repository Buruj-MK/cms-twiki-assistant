#!/usr/bin/env python3
"""
TWiki to GFM (GitHub Flavored Markdown) Converter
==================================================
A rule-based converter that transforms TWiki markup into GitHub Flavored
Markdown, following the comprehensive conversion table developed for the
CMS Documentation Modernisation project at CERN.

Usage:
    python twiki2gfm.py input.txt -o output.md
    python twiki2gfm.py ./twiki_files/ -o ./output/ --batch
    python twiki2gfm.py input.txt -o output.md --validate
"""

import re
import os
import sys
import argparse
from pathlib import Path


# ─── Icon → Emoji Mapping ───────────────────────────────────────────────

ICON_MAP = {
    # LED status icons
    'led-red': '🔴', 'led-green': '🟢', 'led-blue': '🔵',
    'led-yellow': '🟡', 'led-orange': '🟠',
    'led-gray': '⚪', 'led-grey': '⚪',
    # Standard icons
    'tip': '💡', 'warning': '⚠️', 'help': '❓', 'info': 'ℹ️',
    'checked': '✅', 'unchecked': '⬜',
    'choice-yes': '✅', 'choice-no': '❌',
    'stop': '🛑', 'new': '🆕', 'updated': '🔄',
    'todo': '📝', 'done': '✅', 'closed': '🔒',
    'flag': '🚩', 'star': '⭐', 'home': '🏠',
    'mail': '✉️', 'search': '🔍',
    'person': '👤', 'group': '👥',
    'wrench': '🔧', 'gear': '⚙️', 'plugin': '🔌',
    'arrowright': '→', 'arrowleft': '←',
}

# Color names recognized by TWiki
COLOR_NAMES = (
    'RED', 'GREEN', 'BLUE', 'YELLOW', 'ORANGE', 'PURPLE',
    'PINK', 'AQUA', 'MAROON', 'NAVY', 'TEAL', 'LIME',
    'OLIVE', 'SILVER', 'GRAY', 'BLACK', 'WHITE',
)

COLOR_EMOJI = {
    'RED': '🔴', 'GREEN': '🟢', 'BLUE': '🔵', 'YELLOW': '🟡',
    'ORANGE': '🟠', 'PURPLE': '🟣', 'PINK': '🩷',
    'AQUA': '💠', 'MAROON': '🟤', 'NAVY': '🔵', 'TEAL': '🟢',
    'LIME': '🟢', 'OLIVE': '🟤', 'SILVER': '⚪',
    'GRAY': '⚪', 'BLACK': '⚫', 'WHITE': '⚪',
}

COLOR_PATTERN = '|'.join(COLOR_NAMES)


# ═══════════════════════════════════════════════════════════════════════════
#  Core Converter
# ═══════════════════════════════════════════════════════════════════════════

class TWikiConverter:
    """Converts TWiki markup to GitHub Flavored Markdown."""

    def __init__(self):
        self.verbatim_blocks = []  # protected code blocks
        self.warnings = []         # issues found during conversion

    def convert(self, text: str) -> str:
        """
        Main conversion pipeline.
        Applies rules in the priority order defined in the conversion table
        (Section 13) to avoid conflicts between rules.
        """
        self.verbatim_blocks = []
        self.warnings = []

        # ── Pipeline ──────────────────────────────────────────────────
        text = self._phase01_extract_verbatim(text)
        text = self._phase02_strip_meta(text)
        text = self._phase03_convert_color_blocks(text)
        text = self._phase04_convert_variables(text)
        text = self._phase05_convert_headings(text)
        text = self._phase06_convert_tables(text)
        text = self._phase07_convert_lists(text)
        text = self._phase08_convert_links(text)
        text = self._phase09_convert_inline_formatting(text)
        text = self._phase10_strip_wikiword_escapes(text)
        text = self._phase11_convert_html_tags(text)
        text = self._phase12_convert_signatures(text)
        text = self._phase13_restore_verbatim(text)
        text = self._phase14_convert_horizontal_rules(text)
        text = self._phase15_final_cleanup(text)

        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 1: Protect verbatim / pre blocks
    # ══════════════════════════════════════════════════════════════════

    def _phase01_extract_verbatim(self, text: str) -> str:
        """
        Extract <verbatim> and <pre> blocks and replace with placeholders.
        Content inside these blocks must NOT be processed by any other rule.
        """
        def _replace(match):
            idx = len(self.verbatim_blocks)
            attrs = match.group(2) or ''
            content = match.group(3)
            # Extract language hint from class attribute
            lang = ''
            lang_match = re.search(r'class="(\w+)"', attrs)
            if lang_match:
                lang = lang_match.group(1)
            self.verbatim_blocks.append((content, lang))
            return f'%%VERBATIM_{idx}%%'

        text = re.sub(
            r'<(verbatim|pre)(\s[^>]*)?>(.+?)</\1>',
            _replace, text, flags=re.DOTALL
        )
        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 2: Strip META lines
    # ══════════════════════════════════════════════════════════════════

    def _phase02_strip_meta(self, text: str) -> str:
        """Remove all %META:...% lines (topic metadata)."""
        return re.sub(r'^%META:.*%\s*$\n?', '', text, flags=re.MULTILINE)

    # ══════════════════════════════════════════════════════════════════
    #  Phase 3: Convert color blocks to blockquotes
    # ══════════════════════════════════════════════════════════════════

    def _phase03_convert_color_blocks(self, text: str) -> str:
        """
        Convert TWiki color markup blocks to GFM blockquotes with emoji.
        Pattern: %ICON{led-color}% %COLOR% ... %ENDCOLOR%
        Result:  > 🔴 text line 1
                 > text line 2
        """
        def _replace(match):
            full_prefix = match.group(0)[:match.start(2) - match.start(0)]
            color = match.group(2)
            content = match.group(3).strip()

            # Determine emoji: prefer ICON emoji, fallback to color emoji
            emoji = COLOR_EMOJI.get(color, '')
            icon_match = re.search(r'%ICON\{["\']?([\w-]+)["\']?\}%', match.group(1) or '')
            if icon_match and icon_match.group(1) in ICON_MAP:
                emoji = ICON_MAP[icon_match.group(1)]

            # Convert %BR% inside the block before wrapping
            content = re.sub(r'%BR%', '<br>', content)

            # Build blockquote lines
            lines = content.split('\n')
            result_lines = []
            first_content = True
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    result_lines.append('>')
                elif first_content and emoji:
                    result_lines.append(f'> {emoji} {stripped}')
                    first_content = False
                else:
                    result_lines.append(f'> {stripped}')
                    first_content = False

            return '\n'.join(result_lines)

        # Match: optional ICON + %COLOR% ... %ENDCOLOR%
        pattern = (
            r'((?:%ICON\{["\']?[\w-]+["\']?\}%\s*)?)'  # group 1: optional icon
            r'%(' + COLOR_PATTERN + r')%'                # group 2: color name
            r'\s*'                                        # whitespace after %COLOR%
            r'(.*?)'                                      # group 3: content
            r'\s*%ENDCOLOR%'                              # closing tag
        )
        text = re.sub(pattern, _replace, text, flags=re.DOTALL)
        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 4: Convert / strip TWiki variables
    # ══════════════════════════════════════════════════════════════════

    def _phase04_convert_variables(self, text: str) -> str:
        """Convert known TWiki variables, strip the rest."""

        # ── Specific conversions (order matters) ──

        # %BR% → <br>
        text = re.sub(r'%BR%', '<br>', text)

        # %VBAR% → escaped pipe
        text = re.sub(r'%VBAR%', r'\\|', text)

        # %CARET% → ^
        text = re.sub(r'%CARET%', '^', text)

        # %ICON{"name"}% or %ICON{name}% → emoji
        def _replace_icon(m):
            name = m.group(1)
            return ICON_MAP.get(name, '')
        text = re.sub(r'%ICON\{["\']?([\w-]+)["\']?\}%', _replace_icon, text)

        # %ATTACHURL%/filename → filename
        text = re.sub(r'%ATTACHURL%/', '', text)

        # %PUBURL%/.../filename → filename
        text = re.sub(r'%PUBURL%(?:/[^\s]*?)?/([^\s/]+)', r'\1', text)

        # ── Remove entire lines ──

        # %TOC%, %TABLE{...}%, %STARTINCLUDE%, %STOPINCLUDE%
        text = re.sub(r'^%TOC(\{[^}]*\})?%\s*$\n?', '', text, flags=re.MULTILINE)
        text = re.sub(r'^%TABLE\{[^}]*\}%\s*$\n?', '', text, flags=re.MULTILINE)
        text = re.sub(r'^%(STARTINCLUDE|STOPINCLUDE)%\s*$\n?', '', text, flags=re.MULTILINE)

        # ── Strip wrappers, keep content ──

        # %TWISTY{...}% ... %ENDTWISTY%
        text = re.sub(r'%TWISTY\{[^}]*\}%\s*\n?', '', text)
        text = re.sub(r'%ENDTWISTY%\s*\n?', '', text)

        # %INCLUDE{"..."}%, %SEARCH{...}%
        text = re.sub(r'%INCLUDE\{[^}]*\}%', '', text)
        text = re.sub(r'%SEARCH\{[^}]*\}%', '', text)

        # ── Simple variable stripping ──

        for var in ('WEB', 'TOPIC', 'USERSWEB', 'DATE', 'WIKINAME',
                    'WIKITOOLNAME', 'MAINWEB', 'SYSTEMWEB', 'HOMETOPIC'):
            text = re.sub(rf'%{var}%', '', text)

        # ── Remaining color tags (not caught by Phase 3) ──
        color_vars = '|'.join(COLOR_NAMES + ('ENDCOLOR',))
        text = re.sub(rf'%({color_vars})%', '', text)

        # ── Generic catch-all: %VARIABLE% or %VARIABLE{...}% ──
        text = re.sub(r'%[A-Z_]+(\{[^}]*\})?%', '', text)

        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 5: Convert headings
    # ══════════════════════════════════════════════════════════════════

    def _phase05_convert_headings(self, text: str) -> str:
        """
        Convert TWiki headings to GFM headings.
        ---+   → #
        ---++  → ##
        ----++ → ## (extra dashes OK, only + count matters)
        ---++!! → ## (!! = exclude from TOC, strip it)
        ---#   → # (auto-numbered, treat same as +)
        """
        # Handle ---+++ style headings
        def _replace_plus(m):
            level = min(len(m.group(1)), 6)
            title = m.group(3).strip()
            return f'{"#" * level} {title}'

        text = re.sub(
            r'^-{3,}\s*(\++)\s*(!!)?\s*(.*)$',
            _replace_plus, text, flags=re.MULTILINE
        )

        # Handle ---### auto-numbered headings (rare)
        def _replace_hash(m):
            level = min(len(m.group(1)), 6)
            title = m.group(3).strip()
            return f'{"#" * level} {title}'

        text = re.sub(
            r'^-{3,}\s*(#+)\s*(!!)?\s*(.*)$',
            _replace_hash, text, flags=re.MULTILINE
        )

        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 6: Convert tables
    # ══════════════════════════════════════════════════════════════════

    def _phase06_convert_tables(self, text: str) -> str:
        """Convert TWiki tables to GFM tables with header separators."""
        lines = text.split('\n')
        result = []
        i = 0

        while i < len(lines):
            # Detect start of a table block
            if self._is_table_line(lines[i]):
                table_lines = []
                while i < len(lines) and self._is_table_line(lines[i]):
                    table_lines.append(lines[i])
                    i += 1
                result.extend(self._process_table_block(table_lines))
            else:
                result.append(lines[i])
                i += 1

        return '\n'.join(result)

    def _is_table_line(self, line: str) -> bool:
        """Check if a line is a table row."""
        stripped = line.strip()
        return stripped.startswith('|') and stripped.endswith('|') and len(stripped) > 1

    def _split_table_cells(self, line: str) -> list:
        """Split a table row into individual cell contents."""
        stripped = line.strip()
        # Remove leading and trailing |
        if stripped.startswith('|'):
            stripped = stripped[1:]
        if stripped.endswith('|'):
            stripped = stripped[:-1]
        # Split on | (not escaped \|)
        cells = re.split(r'(?<!\\)\|', stripped)
        return cells

    def _process_table_block(self, table_lines: list) -> list:
        """Process a group of table lines into a GFM table."""
        if not table_lines:
            return []

        # Handle line continuation: backslash at end of row
        merged = []
        buf = ''
        for line in table_lines:
            if line.rstrip().endswith('\\'):
                buf += line.rstrip()[:-1]
            else:
                buf += line
                merged.append(buf)
                buf = ''
        if buf:
            merged.append(buf)
        table_lines = merged

        # Parse first row to detect header
        first_cells = self._split_table_cells(table_lines[0])
        non_empty = [c.strip() for c in first_cells if c.strip()]
        is_header = (
            len(non_empty) > 0
            and all(re.match(r'^\s*\*.*\*\s*$', c) for c in non_empty)
        )

        output = []
        for idx, line in enumerate(table_lines):
            cells = self._split_table_cells(line)
            processed = []

            for cell in cells:
                cell = cell.strip()

                # Handle rowspan marker ^
                if cell == '^':
                    cell = ''

                # Strip bold from header cells
                if idx == 0 and is_header:
                    cell = re.sub(r'^\*(.+)\*$', r'\1', cell.strip()).strip()

                # Normalize internal whitespace (alignment spaces)
                cell = ' '.join(cell.split())

                processed.append(cell)

            # Handle colspan: empty cells from consecutive ||
            # (they show up as empty strings in the split)

            row = '| ' + ' | '.join(processed) + ' |'
            output.append(row)

            # Insert separator after header row
            if idx == 0:
                sep = '|' + '|'.join(' --- ' for _ in processed) + '|'
                output.append(sep)

        return output

    # ══════════════════════════════════════════════════════════════════
    #  Phase 7: Convert lists
    # ══════════════════════════════════════════════════════════════════

    def _phase07_convert_lists(self, text: str) -> str:
        """
        Convert TWiki lists to GFM lists.
        Bullet:     3n spaces + * → (n-1)*2 spaces + -
        Numbered:   3n spaces + 1./A./a./I./i. → 1.
        Definition: 3n spaces + $ Term: text → **Term:** text
        """
        lines = text.split('\n')
        result = []

        for line in lines:
            # ── Bulleted list ──
            m = re.match(r'^( {3,})\*\s(.*)$', line)
            if m:
                spaces = len(m.group(1))
                level = max((spaces // 3) - 1, 0)
                indent = '  ' * level
                result.append(f'{indent}- {m.group(2)}')
                continue

            # ── Numbered list (any type: 1. A. a. I. i.) ──
            m = re.match(
                r'^( {3,})(?:\d+\.|[A-Z]\.|[a-z]\.|[IVXLCDM]+\.|[ivxlcdm]+\.)\s(.*)$',
                line
            )
            if m:
                spaces = len(m.group(1))
                level = max((spaces // 3) - 1, 0)
                indent = '  ' * level
                result.append(f'{indent}1. {m.group(2)}')
                continue

            # ── Definition list ──
            m = re.match(r'^( {3,})\$\s+(.*?):\s+(.*)$', line)
            if m:
                term = m.group(2).strip()
                definition = m.group(3).strip()
                result.append(f'**{term}:** {definition}')
                continue

            result.append(line)

        return '\n'.join(result)

    # ══════════════════════════════════════════════════════════════════
    #  Phase 8: Convert links
    # ══════════════════════════════════════════════════════════════════

    def _phase08_convert_links(self, text: str) -> str:
        """Convert TWiki link syntax to GFM links."""

        # Step 1: Protect escaped links with placeholders
        escaped_links = []

        def _protect_escaped(m):
            idx = len(escaped_links)
            escaped_links.append(m.group(1))
            return f'%%ESCAPED_LINK_{idx}%%'

        text = re.sub(r'!\[\[([^\]]+)\]\]', _protect_escaped, text)

        # Step 2: [[URL or Topic][Label]] → [Label](URL)
        def _replace_link_with_label(m):
            target = m.group(1)
            label = m.group(2)
            if target.startswith('#'):
                target = target.lower()
            return f'[{label}]({target})'

        text = re.sub(
            r'\[\[([^\]]+)\]\[([^\]]+)\]\]',
            _replace_link_with_label, text
        )

        # Step 3: [[URL or Topic]] → appropriate format
        def _replace_simple_link(m):
            target = m.group(1)
            if target.startswith(('http://', 'https://', 'ftp://', 'mailto:')):
                return f'[{target}]({target})'
            elif target.startswith('#'):
                return f'[{target}]({target.lower()})'
            else:
                return target
        text = re.sub(r'\[\[([^\]]+)\]\]', _replace_simple_link, text)

        # Step 4: Restore escaped links as literal text
        for i, content in enumerate(escaped_links):
            text = text.replace(f'%%ESCAPED_LINK_{i}%%', f'\\[\\[{content}\\]\\]')

        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 9: Convert inline formatting
    # ══════════════════════════════════════════════════════════════════

    def _phase09_convert_inline_formatting(self, text: str) -> str:
        """
        Convert TWiki inline formatting to GFM.
        CRITICAL: TWiki *text* = bold → must become **text** in GFM
                  (in Markdown, *text* = italic — this is the #1 gotcha)

        Order matters: double-char markers before single-char.
        """
        lines = text.split('\n')
        result = []

        for line in lines:
            # ==bold fixed font== → **`bold fixed font`**
            line = re.sub(
                r'(^|\s)==([^\s=](?:.*?[^\s=])?)==(?=[\s.,;:!?\)\]}>]|$)',
                r'\1**`\2`**', line
            )

            # =fixed font= → `fixed font`
            line = re.sub(
                r'(^|\s)=([^\s=](?:[^=]*?[^\s=])?)=(?=[\s.,;:!?\)\]}>]|$)',
                r'\1`\2`', line
            )

            # __bold italic__ → ***bold italic***
            line = re.sub(
                r'(^|\s)__([^\s_](?:.*?[^\s_])?)__(?=[\s.,;:!?\)\]}>]|$)',
                r'\1***\2***', line
            )

            # *bold* → **bold** (TWiki bold, NOT Markdown italic!)
            # [^\s*] prevents matching inside existing **markdown** bold
            line = re.sub(
                r'(^|\s)\*([^\s*](?:[^*]*?[^\s*])?)\*(?=[\s.,;:!?\)\]}>]|$)',
                r'\1**\2**', line
            )

            # _italic_ → *italic*
            line = re.sub(
                r'(^|\s)_([^\s_](?:[^_]*?[^\s_])?)_(?=[\s.,;:!?\)\]}>]|$)',
                r'\1*\2*', line
            )

            result.append(line)

        return '\n'.join(result)

    # ══════════════════════════════════════════════════════════════════
    #  Phase 10: Strip WikiWord auto-link escapes
    # ══════════════════════════════════════════════════════════════════

    def _phase10_strip_wikiword_escapes(self, text: str) -> str:
        """
        !WikiWord → WikiWord  (strip the ! escape)
        Main.UserName → UserName  (strip web prefix)
        """
        # !WikiWord (CamelCase: uppercase, lowercase, then uppercase again)
        text = re.sub(r'!([A-Z][a-z]+[A-Z]\w*)', r'\1', text)

        # Also handle: !TopicName where topic starts with uppercase
        # but might not have a second uppercase (e.g., !TeV)
        # More general: ! before a capitalized word that follows no space
        text = re.sub(r'(?<!\w)!([A-Z][a-zA-Z]+)', r'\1', text)

        # Web.TopicName → TopicName
        text = re.sub(
            r'\b(?:Main|TWiki|Sandbox|CMS|CMSPublic|System|Trash)\.'
            r'([A-Z]\w+)',
            r'\1', text
        )

        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 11: Convert HTML tags
    # ══════════════════════════════════════════════════════════════════

    def _phase11_convert_html_tags(self, text: str) -> str:
        """Convert or strip HTML tags found in TWiki content."""

        # Normalize <br /> variants → <br>
        text = re.sub(r'<br\s*/?>', '<br>', text)

        # <b>text</b> / <strong> → **text**
        text = re.sub(r'<b>(.*?)</b>', r'**\1**', text, flags=re.DOTALL)
        text = re.sub(r'<strong>(.*?)</strong>', r'**\1**', text, flags=re.DOTALL)

        # <i>text</i> / <em> → *text*
        text = re.sub(r'<i>(.*?)</i>', r'*\1*', text, flags=re.DOTALL)
        text = re.sub(r'<em>(.*?)</em>', r'*\1*', text, flags=re.DOTALL)

        # <strike> / <del> → ~~text~~
        text = re.sub(r'<strike>(.*?)</strike>', r'~~\1~~', text, flags=re.DOTALL)
        text = re.sub(r'<del>(.*?)</del>', r'~~\1~~', text, flags=re.DOTALL)

        # <code>text</code> (inline) → `text`
        text = re.sub(r'<code>(.*?)</code>', r'`\1`', text)

        # <blockquote> → >
        def _replace_bq(m):
            content = m.group(1).strip()
            return '\n'.join(f'> {l.strip()}' for l in content.split('\n'))
        text = re.sub(r'<blockquote>(.*?)</blockquote>', _replace_bq, text, flags=re.DOTALL)

        # <nop> / <nop/> → remove
        text = re.sub(r'<nop\s*/?>', '', text)

        # Strip wrapper tags (keep inner content)
        for tag in ('noautolink', 'literal', 'sticky'):
            text = re.sub(rf'<{tag}>(.*?)</{tag}>', r'\1', text, flags=re.DOTALL)

        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 12: Convert signatures
    # ══════════════════════════════════════════════════════════════════

    def _phase12_convert_signatures(self, text: str) -> str:
        """
        Convert TWiki signatures to clean format.
        -- Main.UserName - 2012-07-11  →  — UserName, 2012-07-11
        """
        text = re.sub(
            r'^--\s+(?:(?:Main|CMS|CMSPublic)\.)?(\w+)\s*-\s*(.+?)\s*$',
            r'— \1, \2',
            text, flags=re.MULTILINE
        )
        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 13: Restore verbatim blocks
    # ══════════════════════════════════════════════════════════════════

    def _phase13_restore_verbatim(self, text: str) -> str:
        """Replace placeholders with fenced code blocks."""
        for i, (content, lang) in enumerate(self.verbatim_blocks):
            placeholder = f'%%VERBATIM_{i}%%'
            fence = f'```{lang}\n{content}\n```'
            text = text.replace(placeholder, fence)
        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 14: Convert horizontal rules
    # ══════════════════════════════════════════════════════════════════

    def _phase14_convert_horizontal_rules(self, text: str) -> str:
        """
        Convert remaining --- lines (that are NOT headings) to GFM hr.
        Headings are already converted in Phase 5, so any remaining
        line of 3+ dashes is a horizontal rule.
        """
        text = re.sub(r'^-{3,}\s*$', '---', text, flags=re.MULTILINE)
        return text

    # ══════════════════════════════════════════════════════════════════
    #  Phase 15: Final cleanup
    # ══════════════════════════════════════════════════════════════════

    def _phase15_final_cleanup(self, text: str) -> str:
        """Normalize whitespace, decode HTML entities, clean artifacts."""

        # Decode common HTML entities
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&#124;', '\\|')
        text = text.replace('&#94;', '^')

        # Collapse runs of 3+ blank lines into 2
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Remove trailing whitespace per line
        text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)

        # Remove leading/trailing blank lines but preserve indentation
        text = text.strip('\n') + '\n'

        return text

    # ══════════════════════════════════════════════════════════════════
    #  Validation
    # ══════════════════════════════════════════════════════════════════

    def validate(self, gfm_text: str) -> list:
        """
        Check converted output for common issues.
        Returns a list of diagnostic strings.
        """
        issues = []

        # Strip code blocks before checking (avoid false positives)
        no_code = re.sub(r'```.*?```', '', gfm_text, flags=re.DOTALL)
        no_code = re.sub(r'`[^`]+`', '', no_code)

        if re.search(r'^%META:', no_code, re.MULTILINE):
            issues.append('❌ Raw %META: lines still present')

        if re.search(r'%[A-Z_]+(\{[^}]*\})?%', no_code):
            issues.append('⚠️  Possible unconverted TWiki variable')

        if '<nop' in no_code:
            issues.append('❌ <nop> tags still present')

        if '<noautolink>' in no_code:
            issues.append('❌ <noautolink> tags still present')

        if '<verbatim>' in no_code:
            issues.append('❌ Unconverted <verbatim> tags')

        if re.search(r'<br\s*/>', no_code):
            issues.append('⚠️  <br /> not normalized to <br>')

        if not issues:
            issues.append('✅ All validation checks passed')

        return issues


# ═══════════════════════════════════════════════════════════════════════════
#  CLI Interface
# ═══════════════════════════════════════════════════════════════════════════

def convert_file(input_path: str, output_path: str, validate: bool = False) -> dict:
    """Convert a single TWiki file to GFM."""
    converter = TWikiConverter()

    with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
        twiki_text = f.read()

    gfm_text = converter.convert(twiki_text)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(gfm_text)

    result = {
        'input': input_path,
        'output': output_path,
        'warnings': converter.warnings,
    }
    if validate:
        result['validation'] = converter.validate(gfm_text)

    return result


def convert_batch(input_dir: str, output_dir: str, validate: bool = False) -> list:
    """Convert all TWiki files in a directory."""
    results = []
    in_path = Path(input_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    files = sorted(in_path.glob('*.txt')) + sorted(in_path.glob('*.twiki'))
    if not files:
        print(f'No .txt or .twiki files found in {input_dir}')
        return results

    total = len(files)
    print(f'Converting {total} files...\n')

    passed = 0
    warned = 0

    for idx, fpath in enumerate(files, 1):
        out_file = out_path / (fpath.stem + '.md')
        result = convert_file(str(fpath), str(out_file), validate)
        results.append(result)

        has_issues = any('❌' in v for v in result.get('validation', []))
        has_warnings = any('⚠️' in v for v in result.get('validation', []))

        if has_issues:
            icon = '❌'
            warned += 1
        elif has_warnings:
            icon = '⚠️'
            warned += 1
        else:
            icon = '✅'
            passed += 1

        print(f'  [{idx:>{len(str(total))}}/{total}] {icon} {fpath.name} → {out_file.name}')

    print(f'\n{"═" * 50}')
    print(f'Done! {passed} passed, {warned} need review, {total} total.')
    return results


def main():
    parser = argparse.ArgumentParser(
        description='TWiki → GFM Converter (CMS Documentation Modernisation)',
        epilog=(
            'Examples:\n'
            '  python twiki2gfm.py page.txt -o page.md\n'
            '  python twiki2gfm.py page.txt -o page.md --validate\n'
            '  python twiki2gfm.py ./twiki_pages/ -o ./markdown/ --batch\n'
            '  python twiki2gfm.py ./twiki_pages/ -o ./markdown/ --batch --validate'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('input', help='Input TWiki file or directory (with --batch)')
    parser.add_argument('-o', '--output', required=True, help='Output file or directory')
    parser.add_argument('--batch', action='store_true', help='Convert all files in directory')
    parser.add_argument('--validate', action='store_true', help='Run validation on output')

    args = parser.parse_args()

    if args.batch:
        results = convert_batch(args.input, args.output, args.validate)
    else:
        result = convert_file(args.input, args.output, args.validate)
        print(f'✅ {result["input"]} → {result["output"]}')
        if args.validate:
            print('\nValidation:')
            for v in result.get('validation', []):
                print(f'  {v}')


if __name__ == '__main__':
    main()
