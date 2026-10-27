"""Parsing of Tcl scripts into commands and words.

A script is parsed into a list of commands. Each command is a list of words,
and each word is a list of parts:

* ("text", s)      literal text
* ("var", name, index_parts_or_None)
* ("cmd", script_text)
* ("expand", word_parts)   a word that started with {*}
"""

from .errors import TclError

_BACKSLASH = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
_HEX = "0123456789abcdefABCDEF"


def backslash(s, i):
    """Interpret the backslash sequence at s[i] (s[i] == '\\'). Returns (text, next index)."""
    if i + 1 >= len(s):
        return "\\", i + 1
    c = s[i + 1]
    if c in _BACKSLASH:
        return _BACKSLASH[c], i + 2
    if c == "\n":
        j = i + 2
        while j < len(s) and s[j] in " \t":
            j += 1
        return " ", j
    if c == "x":
        j = i + 2
        while j < len(s) and s[j] in _HEX:
            j += 1
        if j == i + 2:
            return "x", i + 2
        return chr(int(s[i + 2:j], 16) & 0xFF), j
    if c == "u":
        j = i + 2
        while j < len(s) and j < i + 6 and s[j] in _HEX:
            j += 1
        if j == i + 2:
            return "u", i + 2
        return chr(int(s[i + 2:j], 16)), j
    if c in "01234567":
        j = i + 1
        while j < len(s) and j < i + 4 and s[j] in "01234567":
            j += 1
        return chr(int(s[i + 1:j], 8) & 0xFF), j
    return c, i + 2


def subst_backslashes(s):
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\":
            t, i = backslash(s, i)
            out.append(t)
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


class Parser:
    def __init__(self, text):
        self.s = text
        self.i = 0
        self.n = len(text)
        self.term = None  # "]" while parsing a command substitution

    # -- helpers ---------------------------------------------------------
    def error(self, msg):
        raise TclError(msg)

    def skip_space(self):
        """Skip spaces and tabs (and backslash-newline) between words."""
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\f\v\r":
                self.i += 1
            elif c == "\\" and self.i + 1 < self.n and s[self.i + 1] == "\n":
                self.i += 2
            else:
                break

    # -- script ----------------------------------------------------------
    def parse_script(self):
        commands = []
        s = self.s
        while True:
            # skip blank lines, separators and comments
            while self.i < self.n:
                c = s[self.i]
                if c in " \t\n\r\f\v;":
                    self.i += 1
                elif c == "#":
                    while self.i < self.n and s[self.i] != "\n":
                        if s[self.i] == "\\" and self.i + 1 < self.n:
                            self.i += 1
                        self.i += 1
                else:
                    break
            if self.i >= self.n or s[self.i] == self.term:
                return commands
            words = self.parse_command()
            if words:
                commands.append(words)

    def parse_command(self):
        words = []
        s = self.s
        while True:
            self.skip_space()
            if self.i >= self.n:
                return words
            c = s[self.i]
            if c == self.term:
                return words
            if c in "\n;":
                self.i += 1
                return words
            words.append(self.parse_word())

    def at_word_end(self):
        return self.i >= self.n or self.s[self.i] in " \t\n\r\f\v;" or self.s[self.i] == self.term

    def parse_word(self):
        s = self.s
        if s.startswith("{*}", self.i) and self.i + 3 < self.n and s[self.i + 3] not in " \t\n\r;":
            self.i += 3
            return [("expand", self.parse_word())]
        c = s[self.i]
        if c == "{":
            text = self.parse_braces()
            if not self.at_word_end():
                self.error("extra characters after close-brace")
            return [("text", text)]
        if c == '"':
            self.i += 1
            parts = self.parse_parts(quoted=True)
            if not self.at_word_end():
                self.error('extra characters after close-quote')
            return parts
        return self.parse_parts(quoted=False)

    def parse_braces(self):
        s = self.s
        start = self.i + 1
        depth = 1
        i = start
        while i < self.n:
            c = s[i]
            if c == "\\":
                i += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    self.i = i + 1
                    return s[start:i].replace("\\\n", " ")
            i += 1
        self.error("missing close-brace")

    def parse_parts(self, quoted):
        s = self.s
        parts = []
        buf = []

        def flush():
            if buf:
                parts.append(("text", "".join(buf)))
                buf.clear()

        while True:
            if self.i >= self.n:
                if quoted:
                    self.error('missing "')
                break
            c = s[self.i]
            if quoted and c == '"':
                self.i += 1
                break
            if not quoted and (c in " \t\n\r\f\v;" or c == self.term):
                break
            if c == "\\":
                t, self.i = backslash(s, self.i)
                buf.append(t)
            elif c == "$":
                v = self.parse_variable()
                if v is None:
                    buf.append("$")
                else:
                    flush()
                    parts.append(v)
            elif c == "[":
                flush()
                parts.append(("cmd", self.parse_bracket()))
            else:
                buf.append(c)
                self.i += 1
        flush()
        if not parts:
            parts.append(("text", ""))
        return parts

    def parse_bracket(self):
        """Return the text of a [command] substitution (without brackets)."""
        start = self.i + 1
        sub = Parser(self.s)
        sub.i = start
        sub.term = "]"
        sub.parse_script()
        if sub.i >= self.n:
            self.error("missing close-bracket")
        self.i = sub.i + 1
        return self.s[start:sub.i]

    def parse_variable(self):
        s = self.s
        i = self.i + 1
        if i < self.n and s[i] == "{":
            j = s.find("}", i)
            if j < 0:
                self.error("missing close-brace for variable name")
            self.i = j + 1
            return ("var", s[i + 1:j], None)
        j = i
        while j < self.n and (s[j].isalnum() or s[j] == "_" or (s[j] == ":" and j + 1 < self.n and s[j + 1] == ":")):
            j += 2 if s[j] == ":" else 1
        if j == i:
            return None
        name = s[i:j]
        self.i = j
        if self.i < self.n and s[self.i] == "(":
            self.i += 1
            index = []
            buf = []
            while True:
                if self.i >= self.n:
                    self.error("missing )")
                c = s[self.i]
                if c == ")":
                    self.i += 1
                    break
                if c == "\\":
                    t, self.i = backslash(s, self.i)
                    buf.append(t)
                elif c == "$":
                    v = self.parse_variable()
                    if v is None:
                        buf.append("$")
                    else:
                        if buf:
                            index.append(("text", "".join(buf)))
                            buf = []
                        index.append(v)
                elif c == "[":
                    if buf:
                        index.append(("text", "".join(buf)))
                        buf = []
                    index.append(("cmd", self.parse_bracket()))
                else:
                    buf.append(c)
                    self.i += 1
            if buf:
                index.append(("text", "".join(buf)))
            return ("var", name, index or [("text", "")])
        return ("var", name, None)


def parse_script(text):
    return Parser(text).parse_script()
