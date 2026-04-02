"""Minimal C preprocessor for the c2pak transpiler.

Handles the most common patterns found in N64 homebrew / decomp C files:
  - #define NAME value   → collected into a macro table
  - #define NAME(args)   → tracked as function-like macros
  - #include "file.h"    → optionally resolved for type information
  - #ifdef / #ifndef / #endif  → stripped (we assume a fixed target platform)
  - Line-continuation (backslash-newline) → joined

This is intentionally lightweight. For complex macro-heavy code use
`gcc -E` external preprocessing (see c_parser.py).
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ── Macro representation ──────────────────────────────────────────────────────

@dataclass
class SimpleMacro:
    """A #define NAME value constant macro."""
    name: str
    value: str          # raw text of the expansion


@dataclass
class FuncMacro:
    """A #define NAME(params) body function-like macro."""
    name: str
    params: List[str]
    body: str


# ── Preprocessor ──────────────────────────────────────────────────────────────

class Preprocessor:
    """Lightweight C preprocessor that strips directives and collects macros."""

    def __init__(self):
        self.simple_macros: Dict[str, SimpleMacro] = {}
        self.func_macros: Dict[str, FuncMacro] = {}
        # Types inferred from typedefs already known before this file
        self._ifdef_stack: List[bool] = []  # True = currently active branch

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, source: str) -> Tuple[str, Dict[str, SimpleMacro]]:
        """Process *source* text.

        Returns:
            (cleaned_source, simple_macros) where cleaned_source has all
            preprocessor directives removed/resolved and simple_macros is a
            dict of all #define NAME value macros collected.
        """
        source = self._join_line_continuations(source)
        lines = source.splitlines(keepends=True)
        out_lines: List[str] = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith('#'):
                self._handle_directive(stripped)
                # Emit a blank line to preserve line numbers approximately
                out_lines.append('\n')
            else:
                if self._is_active():
                    out_lines.append(line)
                else:
                    out_lines.append('\n')
        return ''.join(out_lines), dict(self.simple_macros)

    # ── Directive handling ────────────────────────────────────────────────────

    def _handle_directive(self, line: str):
        """Dispatch a # directive line."""
        line = line.rstrip()
        # Remove the leading '#' and optional spaces
        content = line[1:].lstrip()
        if not content:
            return

        # Split keyword from rest
        parts = content.split(None, 1)
        keyword = parts[0]
        rest = parts[1] if len(parts) > 1 else ''

        if keyword == 'define':
            self._handle_define(rest)
        elif keyword in ('ifdef', 'ifndef'):
            name = rest.strip().split()[0] if rest.strip() else ''
            defined = name in self.simple_macros or name in self.func_macros
            if keyword == 'ifdef':
                self._ifdef_stack.append(self._is_active() and defined)
            else:
                self._ifdef_stack.append(self._is_active() and not defined)
        elif keyword == 'if':
            # Simplified: treat #if 0 as inactive, everything else active
            val = rest.strip()
            self._ifdef_stack.append(self._is_active() and val != '0')
        elif keyword == 'elif':
            if self._ifdef_stack:
                # If the previous branch was active we deactivate, otherwise
                # attempt to evaluate the condition.
                prev = self._ifdef_stack.pop()
                val = rest.strip()
                self._ifdef_stack.append(not prev and val != '0')
        elif keyword == 'else':
            if self._ifdef_stack:
                self._ifdef_stack[-1] = not self._ifdef_stack[-1]
        elif keyword == 'endif':
            if self._ifdef_stack:
                self._ifdef_stack.pop()
        # #include, #pragma, #error, etc. — ignored

    def _handle_define(self, rest: str):
        """Parse a #define directive body."""
        if not rest:
            return
        # Function-like macro: NAME(params) body
        m = re.match(r'(\w+)\(([^)]*)\)\s*(.*)', rest, re.DOTALL)
        if m:
            name = m.group(1)
            params = [p.strip() for p in m.group(2).split(',') if p.strip()]
            body = m.group(3).strip()
            self.func_macros[name] = FuncMacro(name=name, params=params, body=body)
            return
        # Simple macro: NAME value (or just NAME)
        parts = rest.split(None, 1)
        name = parts[0]
        value = parts[1].strip() if len(parts) > 1 else '1'
        self.simple_macros[name] = SimpleMacro(name=name, value=value)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_active(self) -> bool:
        """Return True if we're in an active (non-skipped) branch."""
        return all(self._ifdef_stack) if self._ifdef_stack else True

    @staticmethod
    def _join_line_continuations(source: str) -> str:
        """Join lines ending with a backslash."""
        return re.sub(r'\\\n', ' ', source)


def strip_comments(source: str) -> str:
    """Remove C-style /* ... */ and // ... comments from *source*.

    Preserves line count by replacing comment content with spaces/newlines
    so that pycparser line numbers stay approximately correct.
    """
    result = []
    i = 0
    n = len(source)
    while i < n:
        # Block comment
        if source[i] == '/' and i + 1 < n and source[i + 1] == '*':
            i += 2
            while i < n:
                if source[i] == '*' and i + 1 < n and source[i + 1] == '/':
                    i += 2
                    result.append(' ')
                    break
                elif source[i] == '\n':
                    result.append('\n')
                i += 1
        # Line comment
        elif source[i] == '/' and i + 1 < n and source[i + 1] == '/':
            i += 2
            while i < n and source[i] != '\n':
                i += 1
            # Keep the newline
        # String literal — don't strip comments inside strings
        elif source[i] == '"':
            result.append(source[i])
            i += 1
            while i < n:
                if source[i] == '\\' and i + 1 < n:
                    result.append(source[i])
                    result.append(source[i + 1])
                    i += 2
                elif source[i] == '"':
                    result.append(source[i])
                    i += 1
                    break
                else:
                    result.append(source[i])
                    i += 1
        # Char literal
        elif source[i] == "'":
            result.append(source[i])
            i += 1
            while i < n:
                if source[i] == '\\' and i + 1 < n:
                    result.append(source[i])
                    result.append(source[i + 1])
                    i += 2
                elif source[i] == "'":
                    result.append(source[i])
                    i += 1
                    break
                else:
                    result.append(source[i])
                    i += 1
        else:
            result.append(source[i])
            i += 1
    return ''.join(result)


def preprocess(source: str) -> Tuple[str, Dict[str, SimpleMacro]]:
    """Convenience function: preprocess *source* and return cleaned text + macros."""
    # First strip comments (pycparser can't handle them)
    source = strip_comments(source)
    pp = Preprocessor()
    return pp.process(source)
