"""Pak language parser."""

from typing import List, Optional, Any
from .lexer import Token, TT, Lexer, KEYWORDS
from . import ast


class ParseError(Exception):
    def __init__(self, msg, token: Token):
        super().__init__(f'{token.line}:{token.col}: {msg} (got {token.type.name} {token.value!r})')
        self.token = token


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self, offset=0) -> Token:
        i = self.pos + offset
        if i < len(self.tokens):
            return self.tokens[i]
        return self.tokens[-1]  # EOF

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def check(self, *types) -> bool:
        return self.peek().type in types

    def match(self, *types) -> Optional[Token]:
        if self.check(*types):
            return self.advance()
        return None

    def expect_name(self) -> Token:
        """Accept IDENT or any keyword used as a name."""
        tok = self.peek()
        if tok.type == TT.IDENT or tok.type in KEYWORDS.values():
            return self.advance()
        raise ParseError('Expected identifier', tok)

    def expect(self, tt: TT, msg: str = None) -> Token:
        if self.check(tt):
            return self.advance()
        tok = self.peek()
        raise ParseError(msg or f'Expected {tt.name}', tok)

    def loc(self) -> tuple:
        t = self.peek()
        return t.line, t.col

    def node(self, cls, *args, **kwargs):
        line, col = self.loc()
        obj = cls(*args, **kwargs)
        obj.line = line
        obj.col = col
        return obj

    # ── Entry point ──────────────────────────────────────────────────────────

    def parse(self) -> ast.Program:
        decls = []
        while not self.check(TT.EOF):
            d = self.parse_top_level()
            if d is not None:
                decls.append(d)
        return ast.Program(decls=decls)

    def parse_top_level(self):
        # Collect annotations
        annotations = []
        while self.check(TT.ANNOTATION):
            annotations.append(self.advance().value)

        tok = self.peek()

        if tok.type == TT.USE:
            return self.parse_use()
        elif tok.type == TT.ASSET:
            return self.parse_asset()
        elif tok.type == TT.MODULE:
            return self.parse_module()
        elif tok.type == TT.STRUCT:
            return self.parse_struct(annotations)
        elif tok.type == TT.ENUM:
            return self.parse_enum(annotations)
        elif tok.type == TT.VARIANT:
            return self.parse_variant(annotations)
        elif tok.type == TT.FN:
            return self.parse_fn(annotations)
        elif tok.type == TT.ENTRY:
            return self.parse_entry()
        elif tok.type == TT.EXTERN:
            return self.parse_extern()
        elif tok.type == TT.STATIC:
            return self.parse_static(annotations)
        elif tok.type == TT.LET:
            return self.parse_let(annotations)
        else:
            raise ParseError(f'Unexpected token at top level', tok)

    # ── Top-level declarations ────────────────────────────────────────────────

    def parse_use(self) -> ast.UseDecl:
        line, col = self.loc()
        self.expect(TT.USE)
        path = self.parse_dotted_name()
        return ast.UseDecl(path=path, line=line, col=col)

    def parse_dotted_name(self) -> str:
        parts = [self.expect(TT.IDENT).value]
        while self.check(TT.DOT):
            self.advance()
            parts.append(self.expect(TT.IDENT).value)
        return '.'.join(parts)

    def parse_asset(self) -> ast.AssetDecl:
        line, col = self.loc()
        self.expect(TT.ASSET)
        name = self.expect(TT.IDENT).value
        asset_type = None
        if self.match(TT.COLON):
            asset_type = self.expect(TT.IDENT).value
        self.expect(TT.FROM)
        path = self.expect(TT.STRING).value
        return ast.AssetDecl(name=name, asset_type=asset_type, path=path, line=line, col=col)

    def parse_module(self) -> ast.ModuleDecl:
        line, col = self.loc()
        self.expect(TT.MODULE)
        path = self.parse_dotted_name()
        return ast.ModuleDecl(path=path, line=line, col=col)

    def parse_struct(self, annotations=None) -> ast.StructDecl:
        line, col = self.loc()
        self.expect(TT.STRUCT)
        name = self.expect(TT.IDENT).value
        self.expect(TT.LBRACE)
        fields = []
        while not self.check(TT.RBRACE) and not self.check(TT.EOF):
            f_annotations = []
            while self.check(TT.ANNOTATION):
                f_annotations.append(self.advance().value)
            fname = self.expect(TT.IDENT).value
            self.expect(TT.COLON)
            ftype = self.parse_type()
            self.match(TT.COMMA)
            fields.append(ast.StructField(name=fname, type=ftype, annotations=f_annotations, line=line, col=col))
        self.expect(TT.RBRACE)
        return ast.StructDecl(name=name, fields=fields, annotations=annotations or [], line=line, col=col)

    def parse_enum(self, annotations=None) -> ast.EnumDecl:
        line, col = self.loc()
        self.expect(TT.ENUM)
        name = self.expect(TT.IDENT).value
        base_type = None
        if self.match(TT.COLON):
            base_type = self.expect(TT.IDENT).value
        self.expect(TT.LBRACE)
        variants = []
        while not self.check(TT.RBRACE) and not self.check(TT.EOF):
            vname = self.expect_name().value
            val = None
            if self.match(TT.EQ):
                val = self.parse_expr()
            self.match(TT.COMMA)
            variants.append(ast.EnumVariant(name=vname, value=val, line=line, col=col))
        self.expect(TT.RBRACE)
        return ast.EnumDecl(name=name, base_type=base_type, variants=variants,
                            annotations=annotations or [], line=line, col=col)

    def parse_variant(self, annotations=None) -> ast.VariantDecl:
        line, col = self.loc()
        self.expect(TT.VARIANT)
        name = self.expect(TT.IDENT).value
        self.expect(TT.LBRACE)
        cases = []
        while not self.check(TT.RBRACE) and not self.check(TT.EOF):
            cname = self.expect_name().value
            fields = []
            if self.match(TT.LPAREN):
                while not self.check(TT.RPAREN) and not self.check(TT.EOF):
                    fields.append(self.parse_type())
                    self.match(TT.COMMA)
                self.expect(TT.RPAREN)
            elif self.check(TT.LBRACE):
                self.advance()
                while not self.check(TT.RBRACE) and not self.check(TT.EOF):
                    fname = self.expect(TT.IDENT).value
                    self.expect(TT.COLON)
                    ftype = self.parse_type()
                    self.match(TT.COMMA)
                    fields.append((fname, ftype))
                self.expect(TT.RBRACE)
            self.match(TT.COMMA)
            cases.append(ast.VariantCase(name=cname, fields=fields, line=line, col=col))
        self.expect(TT.RBRACE)
        return ast.VariantDecl(name=name, cases=cases, annotations=annotations or [], line=line, col=col)

    def parse_fn(self, annotations=None) -> ast.FnDecl:
        line, col = self.loc()
        self.expect(TT.FN)
        name = self.expect(TT.IDENT).value
        self.expect(TT.LPAREN)
        params = []
        while not self.check(TT.RPAREN) and not self.check(TT.EOF):
            mut = bool(self.match(TT.MUT))
            pname = self.expect(TT.IDENT).value
            self.expect(TT.COLON)
            ptype = self.parse_type()
            params.append(ast.Param(name=pname, type=ptype, mutable=mut, line=line, col=col))
            self.match(TT.COMMA)
        self.expect(TT.RPAREN)
        ret_type = None
        if self.match(TT.ARROW):
            ret_type = self.parse_type()
        body = None
        if self.check(TT.LBRACE):
            body = self.parse_block()
        return ast.FnDecl(name=name, params=params, ret_type=ret_type, body=body,
                          annotations=annotations or [], line=line, col=col)

    def parse_entry(self) -> ast.EntryBlock:
        line, col = self.loc()
        self.expect(TT.ENTRY)
        body = self.parse_block()
        return ast.EntryBlock(body=body, line=line, col=col)

    def parse_extern(self) -> ast.ExternBlock:
        line, col = self.loc()
        self.expect(TT.EXTERN)
        abi = self.expect(TT.STRING).value
        self.expect(TT.LBRACE)
        decls = []
        while not self.check(TT.RBRACE) and not self.check(TT.EOF):
            ann = []
            while self.check(TT.ANNOTATION):
                ann.append(self.advance().value)
            if self.check(TT.FN):
                decls.append(self.parse_fn(ann))
        self.expect(TT.RBRACE)
        return ast.ExternBlock(abi=abi, decls=decls, line=line, col=col)

    # ── Types ─────────────────────────────────────────────────────────────────

    def parse_type(self) -> Any:
        line, col = self.loc()
        tok = self.peek()

        # ?*Type  or  ?Type
        if self.match(TT.QUESTION):
            if self.check(TT.STAR):
                self.advance()
                inner = self.parse_type()
                return ast.TypePointer(inner=inner, nullable=True, line=line, col=col)
            inner = self.parse_type()
            return ast.TypeOption(inner=inner, line=line, col=col)

        # *Type or *mut Type
        if self.match(TT.STAR):
            mut = bool(self.match(TT.MUT))
            inner = self.parse_type()
            return ast.TypePointer(inner=inner, nullable=False, mutable=mut, line=line, col=col)

        # []Type
        if self.check(TT.LBRACKET):
            self.advance()
            if self.check(TT.RBRACKET):
                self.advance()
                inner = self.parse_type()
                return ast.TypeSlice(inner=inner, line=line, col=col)
            # [N]Type
            size = self.parse_expr()
            self.expect(TT.RBRACKET)
            inner = self.parse_type()
            return ast.TypeArray(size=size, inner=inner, line=line, col=col)

        # fn(A, B) -> R
        if self.check(TT.FN):
            self.advance()
            self.expect(TT.LPAREN)
            params = []
            while not self.check(TT.RPAREN) and not self.check(TT.EOF):
                params.append(self.parse_type())
                self.match(TT.COMMA)
            self.expect(TT.RPAREN)
            ret = None
            if self.match(TT.ARROW):
                ret = self.parse_type()
            return ast.TypeFn(params=params, ret=ret, line=line, col=col)

        # Named type (possibly with generic args like Result(T, E))
        name = self.expect(TT.IDENT).value
        # Handle dotted type names
        while self.check(TT.DOT):
            self.advance()
            name += '.' + self.expect(TT.IDENT).value

        if name == 'Result' and self.check(TT.LPAREN):
            self.advance()
            ok = self.parse_type()
            self.expect(TT.COMMA)
            err = self.parse_type()
            self.expect(TT.RPAREN)
            return ast.TypeResult(ok=ok, err=err, line=line, col=col)
        if name == 'Option' and self.check(TT.LPAREN):
            self.advance()
            inner = self.parse_type()
            self.expect(TT.RPAREN)
            return ast.TypeOption(inner=inner, line=line, col=col)

        return ast.TypeName(name=name, line=line, col=col)

    # ── Statements ────────────────────────────────────────────────────────────

    def parse_block(self) -> ast.Block:
        line, col = self.loc()
        self.expect(TT.LBRACE)
        stmts = []
        while not self.check(TT.RBRACE) and not self.check(TT.EOF):
            s = self.parse_stmt()
            if s is not None:
                stmts.append(s)
        self.expect(TT.RBRACE)
        return ast.Block(stmts=stmts, line=line, col=col)

    def parse_stmt(self) -> Any:
        line, col = self.loc()
        annotations = []
        while self.check(TT.ANNOTATION):
            annotations.append(self.advance().value)

        tok = self.peek()

        if tok.type == TT.LET:
            return self.parse_let(annotations)
        elif tok.type == TT.STATIC:
            return self.parse_static(annotations)
        elif tok.type == TT.RETURN:
            self.advance()
            val = None
            if not self.check(TT.RBRACE) and not self.check(TT.EOF):
                val = self.parse_expr()
            return ast.Return(value=val, line=line, col=col)
        elif tok.type == TT.BREAK:
            self.advance()
            return ast.Break(line=line, col=col)
        elif tok.type == TT.CONTINUE:
            self.advance()
            return ast.Continue(line=line, col=col)
        elif tok.type == TT.IF:
            return self.parse_if()
        elif tok.type == TT.LOOP:
            self.advance()
            body = self.parse_block()
            return ast.LoopStmt(body=body, line=line, col=col)
        elif tok.type == TT.WHILE:
            self.advance()
            cond = self.parse_expr()
            body = self.parse_block()
            return ast.WhileStmt(condition=cond, body=body, line=line, col=col)
        elif tok.type == TT.FOR:
            return self.parse_for()
        elif tok.type == TT.MATCH:
            return self.parse_match()
        elif tok.type == TT.DEFER:
            self.advance()
            body = self.parse_block()
            return ast.DeferStmt(body=body, line=line, col=col)
        elif tok.type in (TT.STRUCT, TT.ENUM, TT.VARIANT):
            # local type decl
            if tok.type == TT.STRUCT:
                return self.parse_struct(annotations)
            elif tok.type == TT.ENUM:
                return self.parse_enum(annotations)
            else:
                return self.parse_variant(annotations)
        else:
            expr = self.parse_expr()
            return ast.ExprStmt(expr=expr, line=line, col=col)

    def parse_let(self, annotations=None) -> ast.LetDecl:
        line, col = self.loc()
        self.expect(TT.LET)
        name = self.expect(TT.IDENT).value
        typ = None
        if self.match(TT.COLON):
            typ = self.parse_type()
        val = None
        if self.match(TT.EQ):
            val = self.parse_expr()
        return ast.LetDecl(name=name, type=typ, value=val, annotations=annotations or [], line=line, col=col)

    def parse_static(self, annotations=None) -> ast.StaticDecl:
        line, col = self.loc()
        self.expect(TT.STATIC)
        name = self.expect(TT.IDENT).value
        typ = None
        if self.match(TT.COLON):
            typ = self.parse_type()
        val = None
        if self.match(TT.EQ):
            val = self.parse_expr()
        return ast.StaticDecl(name=name, type=typ, value=val, annotations=annotations or [], line=line, col=col)

    def parse_if(self) -> Any:
        line, col = self.loc()
        self.expect(TT.IF)

        # Nullable check: if expr -> binding { }
        # We need to detect this: parse the expr, then check for ->
        # But -> after an ident could mean this
        cond = self.parse_expr()

        if self.match(TT.ARROW):
            binding = self.expect(TT.IDENT).value
            then = self.parse_block()
            else_b = None
            if self.match(TT.ELSE):
                else_b = self.parse_block()
            return ast.NullCheckStmt(expr=cond, binding=binding, then=then,
                                     else_branch=else_b, line=line, col=col)

        then = self.parse_block()
        elif_branches = []
        else_b = None
        while self.check(TT.ELSE):
            self.advance()
            if self.check(TT.IF):
                self.advance()
                ec = self.parse_expr()
                eb = self.parse_block()
                elif_branches.append((ec, eb))
            else:
                else_b = self.parse_block()
                break
        return ast.IfStmt(condition=cond, then=then, elif_branches=elif_branches,
                          else_branch=else_b, line=line, col=col)

    def parse_for(self) -> ast.ForStmt:
        line, col = self.loc()
        self.expect(TT.FOR)
        # for i, item in ... or for item in ...
        first = self.expect(TT.IDENT).value
        index = None
        binding = first
        if self.match(TT.COMMA):
            index = first
            binding = self.expect(TT.IDENT).value
        self.expect(TT.IN)
        iterable = self.parse_expr()
        body = self.parse_block()
        return ast.ForStmt(index=index, binding=binding, iterable=iterable, body=body, line=line, col=col)

    def parse_match(self) -> ast.MatchStmt:
        line, col = self.loc()
        self.expect(TT.MATCH)
        expr = self.parse_expr()
        self.expect(TT.LBRACE)
        arms = []
        while not self.check(TT.RBRACE) and not self.check(TT.EOF):
            arm = self.parse_match_arm()
            arms.append(arm)
            self.match(TT.COMMA)
        self.expect(TT.RBRACE)
        return ast.MatchStmt(expr=expr, arms=arms, line=line, col=col)

    def parse_match_arm(self) -> ast.MatchArm:
        line, col = self.loc()
        pattern = self.parse_pattern()
        self.expect(TT.FAT_ARROW)
        body = self.parse_block()
        return ast.MatchArm(pattern=pattern, guard=None, body=body, line=line, col=col)

    def parse_pattern(self) -> Any:
        line, col = self.loc()
        # .variant or _ or literal or ident
        if self.check(TT.DOT):
            self.advance()
            name = self.expect(TT.IDENT).value
            return ast.EnumVariantAccess(name=name, line=line, col=col)
        elif self.check(TT.UNDERSCORE):
            self.advance()
            return ast.Ident(name='_', line=line, col=col)
        elif self.check(TT.INT):
            t = self.advance()
            raw = t.value
            val = int(t.value, 16) if t.value.startswith('0x') or t.value.startswith('0X') else int(t.value)
            return ast.IntLit(value=val, raw=raw, line=line, col=col)
        elif self.check(TT.STRING):
            return ast.StringLit(value=self.advance().value, line=line, col=col)
        elif self.check(TT.IDENT):
            name = self.advance().value
            # Could be EnumName.variant
            if self.check(TT.DOT):
                self.advance()
                variant = self.expect(TT.IDENT).value
                return ast.DotAccess(obj=ast.Ident(name=name, line=line, col=col),
                                     field=variant, line=line, col=col)
            return ast.Ident(name=name, line=line, col=col)
        elif self.check(TT.TRUE):
            self.advance()
            return ast.BoolLit(value=True, line=line, col=col)
        elif self.check(TT.FALSE):
            self.advance()
            return ast.BoolLit(value=False, line=line, col=col)
        else:
            return self.parse_expr()

    # ── Expressions ───────────────────────────────────────────────────────────

    def parse_expr(self) -> Any:
        return self.parse_assign()

    def parse_assign(self) -> Any:
        line, col = self.loc()
        left = self.parse_catch()
        if self.check(TT.EQ) and not self.check(TT.EQEQ):
            # Check if it's = not ==
            if self.peek().type == TT.EQ:
                op = self.advance().value
                right = self.parse_assign()
                return ast.Assign(target=left, value=right, op=op, line=line, col=col)
        for op_tt, op_str in [
            (TT.PLUS_EQ, '+='), (TT.MINUS_EQ, '-='),
            (TT.STAR_EQ, '*='), (TT.SLASH_EQ, '/='),
            (TT.SHL_EQ, '<<='), (TT.SHR_EQ, '>>='),
            (TT.AMP_EQ, '&='), (TT.PIPE_EQ, '|='), (TT.CARET_EQ, '^='),
        ]:
            if self.match(op_tt):
                right = self.parse_assign()
                return ast.Assign(target=left, value=right, op=op_str, line=line, col=col)
        return left

    def parse_catch(self) -> Any:
        line, col = self.loc()
        expr = self.parse_or()
        if self.match(TT.CATCH):
            binding = None
            if self.check(TT.PIPE):
                self.advance()
                binding = self.expect(TT.IDENT).value
                self.expect(TT.PIPE)
            handler = self.parse_block()
            return ast.CatchExpr(expr=expr, binding=binding, handler=handler, line=line, col=col)
        return expr

    def parse_or(self) -> Any:
        line, col = self.loc()
        left = self.parse_and()
        while self.check(TT.OR):
            self.advance()
            right = self.parse_and()
            left = ast.BinaryOp(op='||', left=left, right=right, line=line, col=col)
        return left

    def parse_and(self) -> Any:
        line, col = self.loc()
        left = self.parse_bitor()
        while self.check(TT.AND):
            self.advance()
            right = self.parse_bitor()
            left = ast.BinaryOp(op='&&', left=left, right=right, line=line, col=col)
        return left

    def parse_bitor(self) -> Any:
        line, col = self.loc()
        left = self.parse_bitxor()
        while self.check(TT.PIPE):
            self.advance()
            right = self.parse_bitxor()
            left = ast.BinaryOp(op='|', left=left, right=right, line=line, col=col)
        return left

    def parse_bitxor(self) -> Any:
        line, col = self.loc()
        left = self.parse_bitand()
        while self.check(TT.CARET):
            self.advance()
            right = self.parse_bitand()
            left = ast.BinaryOp(op='^', left=left, right=right, line=line, col=col)
        return left

    def parse_bitand(self) -> Any:
        line, col = self.loc()
        left = self.parse_eq()
        while self.check(TT.AMP):
            self.advance()
            right = self.parse_eq()
            left = ast.BinaryOp(op='&', left=left, right=right, line=line, col=col)
        return left

    def parse_eq(self) -> Any:
        line, col = self.loc()
        left = self.parse_cmp()
        while self.check(TT.EQEQ, TT.NEQ):
            op = self.advance().value
            right = self.parse_cmp()
            left = ast.BinaryOp(op=op, left=left, right=right, line=line, col=col)
        return left

    def parse_cmp(self) -> Any:
        line, col = self.loc()
        left = self.parse_shift()
        while self.check(TT.LT, TT.GT, TT.LTE, TT.GTE):
            op = self.advance().value
            right = self.parse_shift()
            left = ast.BinaryOp(op=op, left=left, right=right, line=line, col=col)
        return left

    def parse_shift(self) -> Any:
        line, col = self.loc()
        left = self.parse_add()
        while self.check(TT.SHL, TT.SHR):
            op = self.advance().value
            right = self.parse_add()
            left = ast.BinaryOp(op=op, left=left, right=right, line=line, col=col)
        return left

    def parse_add(self) -> Any:
        line, col = self.loc()
        left = self.parse_mul()
        while self.check(TT.PLUS, TT.MINUS):
            op = self.advance().value
            right = self.parse_mul()
            left = ast.BinaryOp(op=op, left=left, right=right, line=line, col=col)
        return left

    def parse_mul(self) -> Any:
        line, col = self.loc()
        left = self.parse_unary()
        while self.check(TT.STAR, TT.SLASH, TT.PERCENT):
            op = self.advance().value
            right = self.parse_unary()
            left = ast.BinaryOp(op=op, left=left, right=right, line=line, col=col)
        return left

    def parse_unary(self) -> Any:
        line, col = self.loc()
        if self.match(TT.BANG) or (self.check(TT.NOT) and self.advance()):
            return ast.UnaryOp(op='!', operand=self.parse_unary(), line=line, col=col)
        if self.match(TT.MINUS):
            return ast.UnaryOp(op='-', operand=self.parse_unary(), line=line, col=col)
        if self.match(TT.AMP):
            mut = bool(self.match(TT.MUT))
            return ast.AddrOf(expr=self.parse_unary(), mutable=mut, line=line, col=col)
        if self.match(TT.STAR):
            return ast.Deref(expr=self.parse_unary(), line=line, col=col)
        return self.parse_cast()

    def parse_cast(self) -> Any:
        line, col = self.loc()
        expr = self.parse_postfix()
        if self.match(TT.AS):
            typ = self.parse_type()
            return ast.Cast(expr=expr, type=typ, line=line, col=col)
        return expr

    def parse_postfix(self) -> Any:
        line, col = self.loc()
        expr = self.parse_primary()
        while True:
            if self.check(TT.DOT):
                self.advance()
                field = self.expect(TT.IDENT).value
                expr = ast.DotAccess(obj=expr, field=field, line=line, col=col)
            elif self.check(TT.LPAREN):
                self.advance()
                args = []
                while not self.check(TT.RPAREN) and not self.check(TT.EOF):
                    # Named argument: name: value
                    if self.check(TT.IDENT) and self.peek(1).type == TT.COLON:
                        aname = self.advance().value
                        self.advance()  # consume :
                        aval = self.parse_expr()
                        args.append(ast.NamedArg(name=aname, value=aval, line=line, col=col))
                    else:
                        args.append(self.parse_expr())
                    self.match(TT.COMMA)
                self.expect(TT.RPAREN)
                expr = ast.Call(func=expr, args=args, line=line, col=col)
            elif self.check(TT.LBRACKET):
                self.advance()
                idx = self.parse_expr()
                # Check for slice: expr[start..end]
                if self.check(TT.DOTDOT):
                    self.advance()
                    end = None
                    if not self.check(TT.RBRACKET):
                        end = self.parse_expr()
                    self.expect(TT.RBRACKET)
                    expr = ast.SliceExpr(obj=expr, start=idx, end=end, line=line, col=col)
                else:
                    self.expect(TT.RBRACKET)
                    expr = ast.IndexAccess(obj=expr, index=idx, line=line, col=col)
            else:
                break
        return expr

    def parse_primary(self) -> Any:
        line, col = self.loc()
        tok = self.peek()

        if tok.type == TT.INT:
            self.advance()
            raw = tok.value
            val = int(tok.value, 16) if tok.value.startswith(('0x', '0X')) else int(tok.value)
            lit = ast.IntLit(value=val, raw=raw, line=line, col=col)
            if self.check(TT.DOTDOT):
                self.advance()
                end = None
                if not self.check(TT.RBRACE) and not self.check(TT.COMMA) and not self.check(TT.RPAREN) and not self.check(TT.RBRACKET):
                    end = self.parse_primary()
                return ast.RangeExpr(start=lit, end=end, line=line, col=col)
            return lit

        if tok.type == TT.FLOAT:
            self.advance()
            return ast.FloatLit(value=float(tok.value), line=line, col=col)

        if tok.type == TT.STRING:
            self.advance()
            return ast.StringLit(value=tok.value, line=line, col=col)

        if tok.type == TT.TRUE:
            self.advance()
            return ast.BoolLit(value=True, line=line, col=col)

        if tok.type == TT.FALSE:
            self.advance()
            return ast.BoolLit(value=False, line=line, col=col)

        if tok.type == TT.NONE:
            self.advance()
            return ast.NoneLit(line=line, col=col)

        if tok.type == TT.UNDEFINED:
            self.advance()
            return ast.UndefinedLit(line=line, col=col)

        if tok.type == TT.UNDERSCORE:
            self.advance()
            return ast.Ident(name='_', line=line, col=col)

        # Grouped expression or tuple
        if tok.type == TT.LPAREN:
            self.advance()
            expr = self.parse_expr()
            self.expect(TT.RPAREN)
            return expr

        # Array literal: [a, b, c] or [val; N]
        if tok.type == TT.LBRACKET:
            self.advance()
            if self.check(TT.RBRACKET):
                self.advance()
                return ast.ArrayLit(elements=[], line=line, col=col)
            first = self.parse_expr()
            if self.match(TT.SEMICOLON):
                count = self.parse_expr()
                self.expect(TT.RBRACKET)
                return ast.ArrayLit(elements=[first], repeat=count, line=line, col=col)
            elements = [first]
            while self.match(TT.COMMA):
                if self.check(TT.RBRACKET):
                    break
                elements.append(self.parse_expr())
            self.expect(TT.RBRACKET)
            return ast.ArrayLit(elements=elements, line=line, col=col)

        # .variant_name (enum dot access)
        if tok.type == TT.DOT:
            self.advance()
            name = self.expect(TT.IDENT).value
            return ast.EnumVariantAccess(name=name, line=line, col=col)

        # Range: 0..10
        # (Handled in binary ops above, but start..end as primary)

        # Identifier or struct literal
        if tok.type == TT.IDENT:
            name = self.advance().value
            # Look ahead: if next is { and previous token doesn't suggest we're inside a block
            # Struct literal: TypeName { field: val, ... }
            if self.check(TT.LBRACE) and self._is_struct_literal_context():
                self.advance()
                fields = []
                while not self.check(TT.RBRACE) and not self.check(TT.EOF):
                    fname = self.expect(TT.IDENT).value
                    self.expect(TT.COLON)
                    fval = self.parse_expr()
                    fields.append((fname, fval))
                    self.match(TT.COMMA)
                self.expect(TT.RBRACE)
                return ast.StructLit(type_name=name, fields=fields, line=line, col=col)

            # Range: name..end (if name is numeric ident - unlikely, but handle)
            if self.check(TT.DOTDOT):
                self.advance()
                end = None
                if not self.check(TT.RBRACE) and not self.check(TT.COMMA) and not self.check(TT.RPAREN):
                    end = self.parse_primary()
                return ast.RangeExpr(start=ast.Ident(name=name, line=line, col=col), end=end, line=line, col=col)

            return ast.Ident(name=name, line=line, col=col)

        if tok.type == TT.INT:
            t = self.advance()
            raw = t.value
            ival = int(t.value, 16) if t.value.startswith(('0x', '0X')) else int(t.value)
            if self.check(TT.DOTDOT):
                self.advance()
                end = None
                if not self.check(TT.RBRACE) and not self.check(TT.COMMA) and not self.check(TT.RPAREN) and not self.check(TT.RBRACKET):
                    end = self.parse_primary()
                return ast.RangeExpr(start=ast.IntLit(value=ival, raw=raw, line=line, col=col), end=end, line=line, col=col)
            return ast.IntLit(value=ival, raw=raw, line=line, col=col)

        raise ParseError(f'Unexpected token in expression', tok)

    def _is_struct_literal_context(self) -> bool:
        """Heuristic: look ahead to see if { ... } looks like a struct literal."""
        # Look for pattern: { ident: ...
        i = self.pos
        if i >= len(self.tokens) or self.tokens[i].type != TT.LBRACE:
            return False
        i += 1
        if i >= len(self.tokens):
            return False
        # Empty struct literal
        if self.tokens[i].type == TT.RBRACE:
            return True
        # If next after { is an ident followed by :, it's a struct literal
        if self.tokens[i].type == TT.IDENT and i + 1 < len(self.tokens) and self.tokens[i+1].type == TT.COLON:
            return True
        return False


def parse(source: str, filename: str = '<unknown>') -> ast.Program:
    lexer = Lexer(source, filename)
    tokens = lexer.tokenize()
    parser = Parser(tokens)
    return parser.parse()
