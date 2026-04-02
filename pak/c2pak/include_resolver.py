"""Include resolver for multi-file C-to-Pak conversion (Phase 4).

Scans a project directory, parses all .h files first to build a global
type table (typedefs, structs, enums), tracks which symbols come from
which header file, and provides 'use' declaration generation for
cross-file references.
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class IncludeResolver:
    """Scans a project directory and builds a global type table from headers.

    Usage:
        resolver = IncludeResolver(project_dir)
        resolver.scan()
        extra_types = resolver.get_type_table()
        use_decls = resolver.get_use_decls(source_file, used_names)
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        # symbol_name → header file that defines it
        self._symbol_origins: Dict[str, Path] = {}
        # module name (stem of file) → set of symbols
        self._module_symbols: Dict[str, Set[str]] = {}
        # typedef name → type string (raw C)
        self._typedefs: Dict[str, str] = {}
        # struct names
        self._structs: Set[str] = set()
        # enum names
        self._enums: Set[str] = set()
        # func decls
        self._func_decls: Set[str] = set()
        self._scanned = False

    def scan(self):
        """Scan all .h files in the project directory."""
        header_files = sorted(self.project_dir.rglob('*.h'))
        for h_file in header_files:
            try:
                self._scan_header(h_file)
            except Exception:
                pass  # Best-effort: skip headers that fail to parse
        self._scanned = True

    def _scan_header(self, h_file: Path):
        """Parse a single header file for type definitions."""
        try:
            source = h_file.read_text(encoding='utf-8', errors='replace')
        except Exception:
            return

        module_name = h_file.stem
        if module_name not in self._module_symbols:
            self._module_symbols[module_name] = set()

        symbols = self._module_symbols[module_name]

        # Strip comments
        source = _strip_comments(source)
        # Strip preprocessor guards and directives
        source = _strip_directives(source)

        # Find typedef struct { ... } Name;
        for m in re.finditer(
            r'typedef\s+struct\s*(?:\w+\s*)?\{[^}]*\}\s*(\w+)\s*;', source, re.DOTALL
        ):
            name = m.group(1)
            self._typedefs[name] = f'struct {name}'
            self._structs.add(name)
            self._symbol_origins[name] = h_file
            symbols.add(name)

        # Find typedef enum { ... } Name;
        for m in re.finditer(
            r'typedef\s+enum\s*(?:\w+\s*)?\{[^}]*\}\s*(\w+)\s*;', source, re.DOTALL
        ):
            name = m.group(1)
            self._typedefs[name] = f'enum {name}'
            self._enums.add(name)
            self._symbol_origins[name] = h_file
            symbols.add(name)

        # Find typedef T Name; (simple aliases)
        for m in re.finditer(
            r'typedef\s+((?:unsigned\s+|signed\s+|const\s+)?(?:int|char|short|long\s+long|long|float|double|void)\s*\*?)\s*(\w+)\s*;',
            source
        ):
            typ_str, name = m.group(1).strip(), m.group(2)
            self._typedefs[name] = typ_str
            self._symbol_origins[name] = h_file
            symbols.add(name)

        # Find struct Name (forward declarations or tag declarations)
        for m in re.finditer(r'struct\s+(\w+)\s*\{', source):
            name = m.group(1)
            self._structs.add(name)
            if name not in self._symbol_origins:
                self._symbol_origins[name] = h_file
                symbols.add(name)

        # Find function declarations
        for m in re.finditer(
            r'(?:extern\s+)?(?:static\s+)?(?:inline\s+)?'
            r'(?:const\s+)?(?:unsigned\s+|signed\s+)?(?:\w+\s*\*?\s+)'
            r'(\w+)\s*\([^;{]*\)\s*;',
            source
        ):
            name = m.group(1)
            if name not in ('if', 'while', 'for', 'return', 'else'):
                self._func_decls.add(name)
                if name not in self._symbol_origins:
                    self._symbol_origins[name] = h_file
                    symbols.add(name)

    def get_type_table(self) -> Dict[str, str]:
        """Return the collected typedef table (name → type string)."""
        return dict(self._typedefs)

    def get_struct_names(self) -> Set[str]:
        """Return all known struct names from headers."""
        return set(self._structs)

    def get_use_decls(self, source_file: Path, used_names: Set[str]) -> List[str]:
        """Generate 'use module.name' declarations for cross-file references.

        Args:
            source_file: the .c file being converted
            used_names: set of type/function names used in that file

        Returns:
            List of 'use module_stem' lines (deduplicated)
        """
        source_stem = source_file.stem
        needed_modules: Set[str] = set()

        for name in used_names:
            origin = self._symbol_origins.get(name)
            if origin is None:
                continue
            module_stem = origin.stem
            if module_stem != source_stem:
                needed_modules.add(module_stem)

        return [f'use {mod}' for mod in sorted(needed_modules)]

    def get_extra_types(self) -> Dict[str, str]:
        """Return type information for use in transpilation."""
        return dict(self._typedefs)


def _strip_comments(source: str) -> str:
    """Remove C-style block and line comments."""
    result = []
    i = 0
    n = len(source)
    while i < n:
        if source[i] == '/' and i + 1 < n and source[i + 1] == '*':
            i += 2
            while i < n:
                if source[i] == '*' and i + 1 < n and source[i + 1] == '/':
                    i += 2
                    break
                elif source[i] == '\n':
                    result.append('\n')
                i += 1
        elif source[i] == '/' and i + 1 < n and source[i + 1] == '/':
            i += 2
            while i < n and source[i] != '\n':
                i += 1
        else:
            result.append(source[i])
            i += 1
    return ''.join(result)


def _strip_directives(source: str) -> str:
    """Remove #preprocessor directives from source."""
    lines = []
    for line in source.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith('#'):
            lines.append('\n')
        else:
            lines.append(line)
    return ''.join(lines)
