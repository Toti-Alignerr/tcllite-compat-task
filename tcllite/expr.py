"""The expr command: expression parsing and evaluation."""

import math
import re

from .errors import TclError

_NUM = re.compile(r"""
    0[xX][0-9a-fA-F]+ |
    0[bB][01]+ |
    0[oO][0-7]+ |
    (?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?
""", re.X)

_BOOL_TRUE = {"true", "yes", "on"}
_BOOL_FALSE = {"false", "no", "off"}

# binary operators: precedence (higher binds tighter)
_BINARY = {
    "||": 1, "&&": 2, "|": 3, "^": 4, "&": 5,
    "==": 6, "!=": 6, "eq": 6, "ne": 6, "in": 6, "ni": 6,
    "<": 7, ">": 7, "<=": 7, ">=": 7,
    "<<": 8, ">>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10, "**": 11,
}
_OPS = sorted([k for k in _BINARY if not k.isalpha()] + ["!", "~", "(", ")", "?", ":", ","], key=len, reverse=True)


def parse_number(s):
    """Return an int or float for a numeric string, or None."""
    t = s.strip()
    if not t:
        return None
    sign = 1
    if t[0] in "+-":
        if t[0] == "-":
            sign = -1
        t = t[1:]
    low = t.lower()
    try:
        if low.startswith("0x"):
            return sign * int(t[2:], 16)
        if low.startswith("0b"):
            return sign * int(t[2:], 2)
        if low.startswith("0o"):
            return sign * int(t[2:], 8)
        if t.isdigit():
            return sign * int(t, 10)
        if low in ("inf", "infinity"):
            return sign * math.inf
        if low == "nan":
            return math.nan
        if re.fullmatch(r"(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", t):
            return sign * float(t)
    except ValueError:
        return None
    return None


def format_number(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return v


def to_bool(v):
    if isinstance(v, (int, float)):
        return v != 0
    n = parse_number(v)
    if n is not None:
        return n != 0
    low = v.lower()
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    raise TclError('expected boolean value but got "%s"' % v)


class _Parser:
    def __init__(self, interp, text):
        self.interp = interp
        self.s = text
        self.i = 0
        self.tok = None
        self.advance()

    def error(self, msg):
        raise TclError(msg)

    def advance(self):
        s = self.s
        while self.i < len(s) and s[self.i] in " \t\n\r":
            self.i += 1
        if self.i >= len(s):
            self.tok = ("end", None)
            return
        c = s[self.i]
        m = _NUM.match(s, self.i)
        if m and (c.isdigit() or c == "."):
            self.i = m.end()
            self.tok = ("num", m.group())
            return
        if c == "$":
            from .parser import Parser
            p = Parser(s)
            p.i = self.i
            v = p.parse_variable()
            if v is None:
                self.error("invalid character \"$\"")
            self.i = p.i
            self.tok = ("var", v)
            return
        if c == "[":
            from .parser import Parser
            p = Parser(s)
            p.i = self.i
            text = p.parse_bracket()
            self.i = p.i
            self.tok = ("cmd", text)
            return
        if c == '"':
            from .parser import Parser
            p = Parser(s)
            p.i = self.i + 1
            parts = p.parse_parts(quoted=True)
            self.i = p.i
            self.tok = ("quoted", parts)
            return
        if c == "{":
            from .parser import Parser
            p = Parser(s)
            p.i = self.i
            text = p.parse_braces()
            self.i = p.i
            self.tok = ("str", text)
            return
        for op in _OPS:
            if s.startswith(op, self.i):
                self.i += len(op)
                self.tok = ("op", op)
                return
        m = re.compile(r"[A-Za-z_][A-Za-z0-9_]*").match(s, self.i)
        if m:
            self.i = m.end()
            word = m.group()
            if word in ("eq", "ne", "in", "ni"):
                self.tok = ("op", word)
            else:
                self.tok = ("ident", word)
            return
        self.error('invalid character "%s"' % c)

    # -- grammar ---------------------------------------------------------
    def parse(self):
        node = self.ternary()
        if self.tok[0] != "end":
            self.error('syntax error in expression "%s"' % self.s)
        return node

    def ternary(self):
        cond = self.binary(1)
        if self.tok == ("op", "?"):
            self.advance()
            a = self.ternary()
            if self.tok != ("op", ":"):
                self.error('syntax error in expression "%s"' % self.s)
            self.advance()
            b = self.ternary()
            return ("?", cond, a, b)
        return cond

    def binary(self, minprec):
        left = self.unary()
        while self.tok[0] == "op" and self.tok[1] in _BINARY and _BINARY[self.tok[1]] >= minprec:
            op = self.tok[1]
            prec = _BINARY[op]
            self.advance()
            right = self.binary(prec if op == "**" else prec + 1)
            left = ("bin", op, left, right)
        return left

    def unary(self):
        if self.tok[0] == "op" and self.tok[1] in ("-", "+", "!", "~"):
            op = self.tok[1]
            self.advance()
            return ("un", op, self.unary())
        return self.primary()

    def primary(self):
        kind, val = self.tok
        if kind == "num":
            self.advance()
            return ("lit", val)
        if kind in ("var", "cmd", "quoted", "str"):
            self.advance()
            return (kind, val)
        if kind == "op" and val == "(":
            self.advance()
            node = self.ternary()
            if self.tok != ("op", ")"):
                self.error('syntax error in expression "%s"' % self.s)
            self.advance()
            return node
        if kind == "ident":
            self.advance()
            if self.tok == ("op", "("):
                self.advance()
                args = []
                if self.tok != ("op", ")"):
                    while True:
                        args.append(self.ternary())
                        if self.tok == ("op", ","):
                            self.advance()
                            continue
                        break
                if self.tok != ("op", ")"):
                    self.error('syntax error in expression "%s"' % self.s)
                self.advance()
                return ("call", val, args)
            low = val.lower()
            if low in _BOOL_TRUE or low in _BOOL_FALSE or low in ("inf", "nan"):
                return ("lit", val)
            self.error('invalid bareword "%s"' % val)
        self.error('syntax error in expression "%s"' % self.s)


def _num(v, op):
    if isinstance(v, (int, float)):
        return v
    n = parse_number(v)
    if n is None:
        raise TclError('can\'t use non-numeric string as operand of "%s"' % op)
    return n


def _int(v, op):
    n = _num(v, op)
    if isinstance(n, float):
        raise TclError('can\'t use floating-point value as operand of "%s"' % op)
    return n


def _compare(a, b):
    na = a if isinstance(a, (int, float)) else parse_number(a)
    nb = b if isinstance(b, (int, float)) else parse_number(b)
    if na is not None and nb is not None:
        return (na > nb) - (na < nb)
    sa, sb = format_number(a), format_number(b)
    return (sa > sb) - (sa < sb)


def _func(name, args):
    def one():
        if len(args) != 1:
            raise TclError('wrong # args for math function "%s"' % name)
        return _num(args[0], name)

    simple = {"sqrt": math.sqrt, "exp": math.exp, "log": math.log, "log10": math.log10, "sin": math.sin,
              "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
              "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh, "ceil": math.ceil, "floor": math.floor}
    if name in simple:
        try:
            return float(simple[name](one()))
        except (ValueError, OverflowError):
            raise TclError("domain error: argument not in valid range")
    if name == "abs":
        return abs(one())
    if name == "double":
        return float(one())
    if name in ("int", "wide", "entier"):
        v = int(one())
        if name != "entier" and not -2 ** 63 <= v < 2 ** 63:
            raise TclError("integer value too large to represent")
        return v
    if name == "round":
        return int(round(one()))
    if name == "isqrt":
        return math.isqrt(int(one()))
    if name == "bool":
        return 1 if to_bool(args[0]) else 0
    if name in ("pow", "atan2", "fmod", "hypot"):
        if len(args) != 2:
            raise TclError('wrong # args for math function "%s"' % name)
        a, b = _num(args[0], name), _num(args[1], name)
        return float({"pow": math.pow, "atan2": math.atan2, "fmod": math.fmod, "hypot": math.hypot}[name](a, b))
    if name in ("min", "max"):
        vals = [_num(a, name) for a in args]
        return min(vals) if name == "min" else max(vals)
    raise TclError('invalid command name "tcl::mathfunc::%s"' % name)


class Evaluator:
    def __init__(self, interp):
        self.interp = interp

    def eval(self, node):
        kind = node[0]
        if kind == "lit":
            n = parse_number(node[1])
            return n if n is not None else node[1]
        if kind == "var":
            return self.interp.read_var_part(node[1])
        if kind == "cmd":
            return self.interp.eval(node[1])
        if kind == "quoted":
            return self.interp.subst_parts(node[1])
        if kind == "str":
            return node[1]
        if kind == "un":
            op, v = node[1], self.eval(node[2])
            if op == "!":
                return 0 if to_bool(v) else 1
            if op == "~":
                return ~_int(v, op)
            n = _num(v, op)
            return -n if op == "-" else n
        if kind == "?":
            return self.eval(node[2]) if to_bool(self.eval(node[1])) else self.eval(node[3])
        if kind == "call":
            return _func(node[1], [self.eval(a) for a in node[2]])
        op = node[1]
        if op == "&&":
            return 1 if to_bool(self.eval(node[2])) and to_bool(self.eval(node[3])) else 0
        if op == "||":
            return 1 if to_bool(self.eval(node[2])) or to_bool(self.eval(node[3])) else 0
        a, b = self.eval(node[2]), self.eval(node[3])
        if op in ("eq", "ne"):
            r = format_number(a) == format_number(b)
            return int(r if op == "eq" else not r)
        if op in ("in", "ni"):
            from .lists import parse_list
            r = format_number(a) in parse_list(format_number(b))
            return int(r if op == "in" else not r)
        if op in ("==", "!=", "<", ">", "<=", ">="):
            c = _compare(a, b)
            return int({"==": c == 0, "!=": c != 0, "<": c < 0, ">": c > 0, "<=": c <= 0, ">=": c >= 0}[op])
        if op in ("&", "|", "^", "<<", ">>"):
            x, y = _int(a, op), _int(b, op)
            return {"&": x & y, "|": x | y, "^": x ^ y, "<<": x << y if op == "<<" else 0, ">>": x >> y}[op]
        x, y = _num(a, op), _num(b, op)
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            if y == 0:
                if isinstance(x, float) or isinstance(y, float):
                    return math.copysign(math.inf, x) if x else math.nan
                raise TclError("divide by zero")
            if isinstance(x, int) and isinstance(y, int):
                return int(x / y)
            return x / y
        if op == "%":
            if y == 0:
                raise TclError("divide by zero")
            if isinstance(x, float) or isinstance(y, float):
                raise TclError('can\'t use floating-point value as operand of "%"')
            return int(math.fmod(x, y))
        if op == "**":
            return x ** y
        raise TclError("unknown operator %s" % op)


def expr(interp, text):
    node = _Parser(interp, text).parse()
    return Evaluator(interp).eval(node)
