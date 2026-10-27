"""Converting between strings and Tcl lists."""

from .errors import TclError
from .parser import backslash

_SPACE = " \t\n\r\f\v"
_SPECIAL = set('"[]$;\\{}')


def parse_list(s):
    """Split a string into list elements."""
    if isinstance(s, list):
        return s
    out = []
    i, n = 0, len(s)
    while True:
        while i < n and s[i] in _SPACE:
            i += 1
        if i >= n:
            return out
        c = s[i]
        if c == "{":
            depth = 1
            j = i + 1
            while j < n and depth:
                if s[j] == "\\":
                    j += 2
                    continue
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                j += 1
            if depth:
                raise TclError("unmatched open brace in list")
            out.append(s[i + 1:j - 1])
            i = j
            if i < n and s[i] not in _SPACE:
                raise TclError("list element in braces followed by \"%s\" instead of space" % s[i:].split()[0])
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and s[j] != '"':
                if s[j] == "\\":
                    t, j = backslash(s, j)
                    buf.append(t)
                else:
                    buf.append(s[j])
                    j += 1
            if j >= n:
                raise TclError("unmatched open quote in list")
            out.append("".join(buf))
            i = j + 1
            if i < n and s[i] not in _SPACE:
                raise TclError("list element in quotes followed by \"%s\" instead of space" % s[i:].split()[0])
        else:
            buf = []
            while i < n and s[i] not in _SPACE:
                if s[i] == "\\":
                    t, i = backslash(s, i)
                    buf.append(t)
                else:
                    buf.append(s[i])
                    i += 1
            out.append("".join(buf))


def quote_element(e):
    if e == "":
        return "{}"
    if any(c in _SPACE for c in e):
        return "{" + e + "}"
    if any(c in _SPECIAL for c in e):
        return "".join("\\" + c if c in _SPECIAL else c for c in e)
    return e


def format_list(items):
    return " ".join(quote_element(str(x)) for x in items)
