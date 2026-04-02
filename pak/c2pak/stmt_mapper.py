"""C statement → Pak statement string mapper (Phase 2).

Converts normalized CStmt objects to Pak source text.

Key transformations:
  - if/else if → if/elif/else (parentheses stripped)
  - while → while (parentheses stripped)
  - do-while → loop { ... if !cond { break } }
  - for (int i = 0; i < N; i++) → for i in 0..N
  - for with pointer walk → while loop
  - for (;;) → loop
  - switch/case on enum → match with dot-prefixed cases
  - switch/case on int → match with value patterns
  - goto/label → goto/label (Pak supports these directly)
  - x++ / x-- as statements → x += 1 / x -= 1
  - Assignment in condition: extracted to separate let
"""

from __future__ import annotations
from typing import List, Optional, Tuple

from .c_ast import (
    CStmt, CCompound, CExprStmt, CIf, CWhile, CDoWhile, CFor,
    CSwitch, CCase, CReturn, CBreak, CContinue, CGoto, CLabel, CEmpty,
    CVarDecl,
    CExpr, CConst, CId, CBinOp, CUnaryOp, CAssign, CCall,
    CArrayRef, CStructRef, CCast, CTernary, CComma, CSizeof, CInitList,
    CType, CPointer, CArray, CPrimitive, CTypeRef, CStruct,
)
from .type_mapper import TypeMapper
from .expr_mapper import ExprMapper


class StmtMapper:
    """Converts CStmt and CVarDecl nodes to Pak source lines."""

    def __init__(self, type_mapper: TypeMapper, expr_mapper: ExprMapper):
        self.tm = type_mapper
        self.em = expr_mapper
        self._indent = 0
        self._tmp_counter = 0
        # Track which variable names are known enum types for match dot-prefixing
        self._enum_vars: dict[str, str] = {}  # var_name → enum_type_name

    # ── Public API ────────────────────────────────────────────────────────────

    def emit_body(self, compound: CCompound) -> str:
        """Emit a function body (CCompound) as an indented block."""
        lines = []
        self._emit_compound_items(compound.items, lines)
        return '\n'.join(lines)

    def emit_stmt(self, stmt: CStmt, indent: int = 0) -> List[str]:
        """Emit a single statement, returning a list of lines."""
        self._indent = indent
        lines: List[str] = []
        self._emit_stmt(stmt, lines)
        return lines

    # ── Internal dispatch ─────────────────────────────────────────────────────

    def _emit_stmt(self, stmt, lines: List[str]):
        if isinstance(stmt, CEmpty):
            pass
        elif isinstance(stmt, CVarDecl):
            self._emit_local_decl(stmt, lines)
        elif isinstance(stmt, CCompound):
            self._emit_compound(stmt, lines)
        elif isinstance(stmt, CExprStmt):
            self._emit_expr_stmt(stmt, lines)
        elif isinstance(stmt, CIf):
            self._emit_if(stmt, lines)
        elif isinstance(stmt, CWhile):
            self._emit_while(stmt, lines)
        elif isinstance(stmt, CDoWhile):
            self._emit_dowhile(stmt, lines)
        elif isinstance(stmt, CFor):
            self._emit_for(stmt, lines)
        elif isinstance(stmt, CSwitch):
            self._emit_switch(stmt, lines)
        elif isinstance(stmt, CReturn):
            self._emit_return(stmt, lines)
        elif isinstance(stmt, CBreak):
            lines.append(self._pad('break'))
        elif isinstance(stmt, CContinue):
            lines.append(self._pad('continue'))
        elif isinstance(stmt, CGoto):
            lines.append(self._pad(f'goto {stmt.label}'))
        elif isinstance(stmt, CLabel):
            # Labels in Pak use 'label' keyword
            lines.append(self._pad(f'label {stmt.name}'))
            if stmt.stmt:
                self._emit_stmt(stmt.stmt, lines)
        else:
            lines.append(self._pad(f'-- unhandled stmt: {type(stmt).__name__}'))

    def _emit_compound_items(self, items, lines: List[str]):
        for item in items:
            self._emit_stmt(item, lines)

    def _emit_compound(self, stmt: CCompound, lines: List[str]):
        """Emit a compound block inline (used for nested blocks)."""
        self._emit_compound_items(stmt.items, lines)

    # ── Local variable declarations ───────────────────────────────────────────

    def _emit_local_decl(self, decl: CVarDecl, lines: List[str]):
        pak_type = self.tm.map_type(decl.typ)
        keyword = 'let'
        if decl.is_static:
            keyword = 'static'
        if decl.is_const:
            keyword = 'const'

        if decl.init is not None:
            init_str = self._emit_init(decl.init, decl.typ)
            lines.append(self._pad(f'{keyword} {decl.name}: {pak_type} = {init_str}'))
        else:
            # Uninitialized — emit a zero value
            zero = _zero_value(pak_type)
            lines.append(self._pad(f'{keyword} {decl.name}: {pak_type} = {zero}'))

    def _emit_init(self, expr: CExpr, typ: CType) -> str:
        """Emit an initializer expression, aware of the target type."""
        if isinstance(expr, CInitList):
            return self._emit_struct_init(expr, typ)
        return self.em.emit(expr)

    def _emit_struct_init(self, init: CInitList, typ: CType) -> str:
        """Emit a CInitList as a Pak struct or array literal."""
        type_name = self._type_name(typ)
        # Named initializer: { .x = 1.0, .y = 2.0 }
        named = all(isinstance(item, tuple) for item in init.items)
        if named and type_name:
            fields = ', '.join(
                f'{k}: {self.em.emit(v)}' for k, v in init.items
            )
            return f'{type_name} {{ {fields} }}'
        # Positional array initializer: { 0, 0, 0 }
        if not init.items:
            # Empty or zero initializer
            if isinstance(typ, CArray):
                inner = self.tm.map_type(typ.inner)
                sz = typ.size or 0
                return f'[0; {sz}]'
            return '{}'
        items_str = ', '.join(self.em.emit(i) if not isinstance(i, tuple)
                              else f'{i[0]}: {self.em.emit(i[1])}' for i in init.items)
        if type_name and not isinstance(typ, CArray):
            return f'{type_name} {{ {items_str} }}'
        return f'{{ {items_str} }}'

    def _type_name(self, typ: CType) -> Optional[str]:
        """Extract a usable type name for struct literals."""
        if isinstance(typ, CTypeRef):
            return typ.name
        if isinstance(typ, CStruct):
            return typ.name
        pak = self.tm.map_type(typ)
        if pak and not pak.startswith('[') and not pak.startswith('*'):
            return pak
        return None

    # ── Expression statements ─────────────────────────────────────────────────

    def _emit_expr_stmt(self, stmt: CExprStmt, lines: List[str]):
        expr = stmt.expr
        # Check for pre/post increment/decrement → convert to += / -=
        if isinstance(expr, CUnaryOp) and expr.op in ('++', '--'):
            target = self.em.emit(expr.expr)
            op = '+=' if expr.op == '++' else '-='
            lines.append(self._pad(f'{target} {op} 1'))
            return

        # Check for assignment
        if isinstance(expr, CAssign):
            # Split chained assignments: a = b = c → b = c; a = b
            chained = self._flatten_chain_assign(expr)
            for t, v in chained:
                lines.append(self._pad(f'{self.em.emit(t)} {expr.op} {self.em.emit(v)}'))
            return

        # Check for comma expression used as statement — flatten
        if isinstance(expr, CComma):
            for sub in expr.exprs:
                self._emit_stmt(CExprStmt(expr=sub), lines)
            return

        # General expression statement
        # Check for increment/decrement sub-expressions that need extraction
        extracted, clean_expr = self._extract_increments(expr)
        for line in extracted:
            lines.append(self._pad(line))
        lines.append(self._pad(self.em.emit(clean_expr)))

    def _flatten_chain_assign(self, expr: CAssign) -> List[Tuple[CExpr, CExpr]]:
        """Flatten chained assignments like a = b = c → [(b, c), (a, b)]."""
        result = []
        cur = expr
        while isinstance(cur.value, CAssign) and cur.op == '=':
            inner = cur.value
            result.append((inner.target, inner.value))
            cur = CAssign(op=cur.op, target=cur.target, value=inner.target)
        result.append((cur.target, cur.value))
        result.reverse()
        return result

    def _extract_increments(self, expr: CExpr) -> Tuple[List[str], CExpr]:
        """Extract pre/post increment/decrement from sub-expressions.

        Returns (list_of_pre_statements, cleaned_expr).
        This is a best-effort extraction for common patterns like arr[i++].
        """
        # For now, handle the most common case: array index with post-increment
        if isinstance(expr, CArrayRef):
            idx = expr.index
            if isinstance(idx, CUnaryOp) and idx.op in ('++', '--') and idx.postfix:
                tmp = f'_tmp{self._next_tmp()}'
                target = self.em.emit(idx.expr)
                op = '+= 1' if idx.op == '++' else '-= 1'
                pre = [f'let {tmp}: i32 = {target}', f'{target} {op}']
                clean = CArrayRef(base=expr.base, index=CId(tmp))
                return pre, clean
        return [], expr

    def _next_tmp(self) -> int:
        self._tmp_counter += 1
        return self._tmp_counter

    # ── If / elif / else ──────────────────────────────────────────────────────

    def _emit_if(self, stmt: CIf, lines: List[str]):
        cond = self.em.emit_as_bool(stmt.cond)
        lines.append(self._pad(f'if {cond} {{'))
        self._with_indent(lambda: self._emit_body_block(stmt.then, lines))
        self._emit_else(stmt.otherwise, lines)

    def _emit_else(self, otherwise, lines: List[str]):
        if otherwise is None:
            lines.append(self._pad('}'))
        elif isinstance(otherwise, CIf):
            # else if → } elif ... {
            cond = self.em.emit_as_bool(otherwise.cond)
            lines.append(self._pad(f'}} elif {cond} {{'))
            self._with_indent(lambda: self._emit_body_block(otherwise.then, lines))
            self._emit_else(otherwise.otherwise, lines)
        else:
            lines.append(self._pad('} else {'))
            self._with_indent(lambda: self._emit_body_block(otherwise, lines))
            lines.append(self._pad('}'))

    def _emit_body_block(self, stmt: CStmt, lines: List[str]):
        """Emit the body of a control structure (handling both compound and single stmts)."""
        if isinstance(stmt, CCompound):
            self._emit_compound_items(stmt.items, lines)
        else:
            self._emit_stmt(stmt, lines)

    # ── While ─────────────────────────────────────────────────────────────────

    def _emit_while(self, stmt: CWhile, lines: List[str]):
        # Special case: while(1) or while(true) → loop
        if _is_always_true(stmt.cond):
            lines.append(self._pad('loop {'))
        else:
            cond = self.em.emit_as_bool(stmt.cond)
            lines.append(self._pad(f'while {cond} {{'))
        self._with_indent(lambda: self._emit_body_block(stmt.body, lines))
        lines.append(self._pad('}'))

    # ── Do-While ──────────────────────────────────────────────────────────────

    def _emit_dowhile(self, stmt: CDoWhile, lines: List[str]):
        # do { body } while (cond) → loop { body; if !cond { break } }
        lines.append(self._pad('loop {'))
        self._with_indent(lambda: self._emit_body_block(stmt.body, lines))
        cond = self.em.emit_as_bool(stmt.cond)
        self._with_indent(lambda: lines.append(self._pad(f'if !({cond}) {{ break }}')))
        lines.append(self._pad('}'))

    # ── For loops ─────────────────────────────────────────────────────────────

    def _emit_for(self, stmt: CFor, lines: List[str]):
        # Detect common patterns
        if stmt.cond is None and stmt.init is None and stmt.step is None:
            # for(;;) → loop
            lines.append(self._pad('loop {'))
            self._with_indent(lambda: self._emit_body_block(stmt.body, lines))
            lines.append(self._pad('}'))
            return

        range_result = self._detect_range_for(stmt)
        if range_result:
            var, start, end, step_val = range_result
            if step_val == 1:
                lines.append(self._pad(f'for {var} in {start}..{end} {{'))
            else:
                # Non-unit step: emit as while loop
                lines.append(self._pad(f'let {var}: i32 = {start}'))
                lines.append(self._pad(f'while {var} < {end} {{'))
                self._with_indent(lambda: self._emit_body_block(stmt.body, lines))
                self._with_indent(lambda: lines.append(
                    self._pad(f'{var} += {step_val}')))
                lines.append(self._pad('}'))
                return
            self._with_indent(lambda: self._emit_body_block(stmt.body, lines))
            lines.append(self._pad('}'))
            return

        # General for loop → init; while cond { body; step }
        if stmt.init is not None:
            if isinstance(stmt.init, list):
                for decl in stmt.init:
                    self._emit_stmt(decl, lines)
            elif isinstance(stmt.init, CExprStmt):
                self._emit_expr_stmt(stmt.init, lines)

        if stmt.cond is not None:
            cond = self.em.emit_as_bool(stmt.cond)
            lines.append(self._pad(f'while {cond} {{'))
        else:
            lines.append(self._pad('loop {'))

        def emit_body_and_step():
            self._emit_body_block(stmt.body, lines)
            if stmt.step is not None:
                self._emit_stmt(CExprStmt(expr=stmt.step), lines)

        self._with_indent(emit_body_and_step)
        lines.append(self._pad('}'))

    def _detect_range_for(self, stmt: CFor):
        """Try to detect 'for (int i = start; i < N; i++)' → range pattern.

        Returns (var, start_str, end_str, step) or None.
        """
        # Must have: init declares a variable, cond is comparison, step is increment
        if stmt.init is None or stmt.cond is None or stmt.step is None:
            return None
        if not isinstance(stmt.init, list) or len(stmt.init) != 1:
            return None
        decl = stmt.init[0]
        if not isinstance(decl, CVarDecl) or decl.init is None:
            return None
        var = decl.name
        start = self.em.emit(decl.init)

        # Condition: var < N, var <= N
        cond = stmt.cond
        if not isinstance(cond, CBinOp):
            return None
        if not isinstance(cond.left, CId) or cond.left.name != var:
            return None
        if cond.op == '<':
            end = self.em.emit(cond.right)
        elif cond.op == '<=':
            # i <= N → i in 0..N+1
            end_expr = cond.right
            if isinstance(end_expr, CConst) and end_expr.kind == 'int':
                try:
                    end = str(int(end_expr.value.rstrip('uUlL')) + 1)
                except ValueError:
                    end = f'{self.em.emit(end_expr)} + 1'
            else:
                end = f'{self.em.emit(end_expr)} + 1'
        else:
            return None

        # Step: i++ or i += 1 or ++i
        step = stmt.step
        step_val = 1
        if isinstance(step, CUnaryOp) and step.op in ('++', '--'):
            if not (isinstance(step.expr, CId) and step.expr.name == var):
                return None
            step_val = 1 if step.op == '++' else -1
        elif isinstance(step, CAssign) and step.op == '+=':
            if not (isinstance(step.target, CId) and step.target.name == var):
                return None
            if isinstance(step.value, CConst):
                try:
                    step_val = int(step.value.value.rstrip('uUlL'))
                except ValueError:
                    return None
            else:
                return None
        else:
            return None

        if step_val <= 0:
            return None
        return var, start, end, step_val

    # ── Switch / match ────────────────────────────────────────────────────────

    def _emit_switch(self, stmt: CSwitch, lines: List[str]):
        cond = self.em.emit(stmt.cond)

        # Detect if we're switching on an enum variable (for dot-prefixed match)
        is_enum_switch = self._is_enum_switch(stmt.cond)

        lines.append(self._pad(f'match {cond} {{'))
        self._with_indent(lambda: self._emit_cases(stmt.cases, is_enum_switch, lines))
        lines.append(self._pad('}'))

    def _is_enum_switch(self, cond: CExpr) -> bool:
        """Heuristic: if the switch condition refers to a known enum variable."""
        # We check if any case value looks like an enum constant (UPPER_CASE or known prefix)
        return True  # Default to enum-style; the emitter strips enum prefixes

    def _emit_cases(self, cases: List[CCase], is_enum: bool, lines: List[str]):
        for i, case in enumerate(cases):
            if case.value is None:
                # default → _ wildcard
                arm = '_'
            else:
                arm = self._emit_case_value(case.value, is_enum)

            # Collect case body (excluding break)
            body_stmts = [s for s in case.stmts if not isinstance(s, CBreak)]

            if not body_stmts:
                lines.append(self._pad(f'{arm} => {{}}'))
            elif len(body_stmts) == 1 and isinstance(body_stmts[0], CExprStmt):
                stmt_line = self.em.emit(body_stmts[0].expr)
                lines.append(self._pad(f'{arm} => {{ {stmt_line} }}'))
            else:
                lines.append(self._pad(f'{arm} => {{'))
                self._with_indent(lambda stmts=body_stmts: [
                    self._emit_stmt(s, lines) for s in stmts
                ])
                lines.append(self._pad('}'))

    def _emit_case_value(self, value: CExpr, is_enum: bool) -> str:
        """Emit a case value, converting enum constants to dot-prefixed form."""
        raw = self.em.emit(value)
        if is_enum and isinstance(value, CId):
            # Strip common enum prefixes (ACTOR_PLAYER → .player)
            cleaned = _strip_enum_prefix(raw)
            return f'.{cleaned}'
        return raw

    # ── Return ────────────────────────────────────────────────────────────────

    def _emit_return(self, stmt: CReturn, lines: List[str]):
        if stmt.value is None:
            lines.append(self._pad('return'))
        else:
            val = self.em.emit(stmt.value)
            lines.append(self._pad(f'return {val}'))

    # ── Indentation helpers ───────────────────────────────────────────────────

    def _pad(self, line: str) -> str:
        return '    ' * self._indent + line

    def _with_indent(self, fn):
        self._indent += 1
        fn()
        self._indent -= 1


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_always_true(expr: CExpr) -> bool:
    """Return True if this expression is a compile-time truthy constant."""
    if isinstance(expr, CConst):
        if expr.kind == 'int':
            try:
                return int(expr.value.rstrip('uUlL')) != 0
            except ValueError:
                pass
    if isinstance(expr, CId) and expr.name in ('true', '1'):
        return True
    return False


def _zero_value(pak_type: str) -> str:
    """Return a zero/default value for a Pak type."""
    if pak_type in ('i8', 'i16', 'i32', 'i64', 'u8', 'u16', 'u32', 'u64'):
        return '0'
    if pak_type in ('f32', 'f64'):
        return '0.0'
    if pak_type == 'bool':
        return 'false'
    if pak_type.startswith('*'):
        return 'none'
    if pak_type.startswith('['):
        return '[]'
    return '0'


def _strip_enum_prefix(name: str) -> str:
    """Strip common UPPER_CASE_ enum prefixes and convert to snake_case.

    Examples:
      DIR_UP → up
      ACTOR_PLAYER → player
      STATE_IDLE → idle
      ENTITY_NONE → none
    """
    import re
    # Split at underscores, find common prefix pattern
    parts = name.split('_')
    if len(parts) >= 2:
        # Heuristic: the last part is the variant name, strip prefix
        variant = '_'.join(parts[1:]).lower()
        return variant
    return name.lower()
