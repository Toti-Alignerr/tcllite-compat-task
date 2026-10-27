"""The interpreter: variables, call frames, procedures and command dispatch."""

from .errors import BreakException, ContinueException, ReturnException, TclError
from .expr import format_number
from .lists import format_list, parse_list
from .parser import parse_script


class Array(dict):
    """An array variable: element name -> value."""


class Link:
    """A variable that refers to a variable in another frame (upvar/global)."""

    def __init__(self, frame, name):
        self.frame = frame
        self.name = name


class Frame:
    def __init__(self, parent=None, level=0, proc=None, args=None):
        self.vars = {}
        self.parent = parent
        self.level = level
        self.proc = proc
        self.args = args or []


class Proc:
    def __init__(self, name, params, body):
        self.name = name
        self.params = params  # list of (name, default or None)
        self.body = body


def split_varname(name):
    """Split 'a(b)' into ('a', 'b'); other names give (name, None)."""
    if name.endswith(")"):
        k = name.find("(")
        if k > 0:
            return name[:k], name[k + 1:-1]
    return name, None


class Interp:
    def __init__(self, stdout, stderr):
        self.stdout = stdout
        self.stderr = stderr
        self.globals = Frame()
        self.frame = self.globals
        self.procs = {}
        self.commands = {}
        self._parsed = {}
        from . import commands
        commands.register(self)

    # -- variables -------------------------------------------------------
    def _resolve(self, name):
        """Return (frame, base name) after following ::names and links."""
        frame = self.frame
        if name.startswith("::"):
            frame = self.globals
            name = name[2:]
        while True:
            v = frame.vars.get(name)
            if isinstance(v, Link):
                frame, name = v.frame, v.name
                continue
            return frame, name

    def get_var(self, name, index=None):
        if index is None:
            name, index = split_varname(name)
        frame, base = self._resolve(name)
        if base not in frame.vars:
            if index is None:
                raise TclError('can\'t read "%s": no such variable' % name)
            raise TclError('can\'t read "%s(%s)": no such variable' % (name, index))
        v = frame.vars[base]
        if isinstance(v, Array):
            if index is None:
                raise TclError('can\'t read "%s": variable is array' % name)
            if index not in v:
                raise TclError('can\'t read "%s(%s)": no such element in array' % (name, index))
            return v[index]
        if index is not None:
            raise TclError('can\'t read "%s(%s)": variable isn\'t array' % (name, index))
        return v

    def set_var(self, name, value, index=None):
        if index is None:
            name, index = split_varname(name)
        frame, base = self._resolve(name)
        value = format_number(value) if not isinstance(value, str) else value
        cur = frame.vars.get(base)
        if index is None:
            if isinstance(cur, Array):
                raise TclError('can\'t set "%s": variable is array' % name)
            frame.vars[base] = value
        else:
            if cur is None:
                cur = frame.vars[base] = Array()
            elif not isinstance(cur, Array):
                raise TclError('can\'t set "%s(%s)": variable isn\'t array' % (name, index))
            cur[index] = value
        return value

    def var_exists(self, name):
        name, index = split_varname(name)
        frame, base = self._resolve(name)
        if base not in frame.vars:
            return False
        v = frame.vars[base]
        if index is None:
            return True
        return isinstance(v, Array) and index in v

    def unset_var(self, name, complain=True):
        name, index = split_varname(name)
        frame, base = self._resolve(name)
        if base not in frame.vars:
            if complain:
                raise TclError('can\'t unset "%s": no such variable' % name)
            return
        v = frame.vars[base]
        if index is None:
            del frame.vars[base]
        elif isinstance(v, Array) and index in v:
            del v[index]
        elif complain:
            raise TclError('can\'t unset "%s(%s)": no such element in array' % (name, index))

    def get_array(self, name, create=False):
        frame, base = self._resolve(name)
        v = frame.vars.get(base)
        if v is None and create:
            v = frame.vars[base] = Array()
        return v if isinstance(v, Array) else None

    def link_var(self, local, frame, other):
        if local in self.frame.vars and not isinstance(self.frame.vars[local], Link):
            raise TclError('variable "%s" already exists' % local)
        self.frame.vars[local] = Link(frame, other)

    def read_var_part(self, part):
        _, name, index = part
        if index is None:
            return self.get_var(name)
        return self.get_var(name, self.subst_parts(index))

    # -- evaluation ------------------------------------------------------
    def parse(self, script):
        cmds = self._parsed.get(script)
        if cmds is None:
            cmds = parse_script(script)
            if len(self._parsed) > 5000:
                self._parsed.clear()
            self._parsed[script] = cmds
        return cmds

    def subst_parts(self, parts):
        if len(parts) == 1 and parts[0][0] == "text":
            return parts[0][1]
        out = []
        for p in parts:
            kind = p[0]
            if kind == "text":
                out.append(p[1])
            elif kind == "var":
                out.append(format_number(self.read_var_part(p)))
            elif kind == "cmd":
                out.append(format_number(self.eval(p[1])))
        return "".join(out)

    def eval(self, script):
        result = ""
        for words in self.parse(script):
            argv = []
            for w in words:
                if w[0][0] == "expand":
                    argv.extend(parse_list(self.subst_parts(w[0][1])))
                else:
                    argv.append(self.subst_parts(w))
            if not argv:
                continue
            result = self.invoke(argv)
        return result

    def invoke(self, argv):
        name = argv[0]
        if name.startswith("::"):
            name = name[2:]
        proc = self.procs.get(name)
        if proc is not None:
            return self.call_proc(proc, argv)
        cmd = self.commands.get(name)
        if cmd is None:
            raise TclError('invalid command name "%s"' % argv[0])
        r = cmd(self, argv)
        return "" if r is None else r

    def call_proc(self, proc, argv):
        args = argv[1:]
        frame = Frame(self.frame, self.frame.level + 1, proc, argv)
        params = proc.params
        i = 0
        for k, (pname, default) in enumerate(params):
            if pname == "args" and k == len(params) - 1:
                frame.vars["args"] = format_list(args[i:])
                i = len(args)
                break
            if i < len(args):
                frame.vars[pname] = args[i]
                i += 1
            elif default is not None:
                frame.vars[pname] = default
            else:
                raise TclError('%s: missing argument %s' % (proc.name, pname))
        if i < len(args):
            raise TclError('%s: too many arguments' % proc.name)
        if frame.level > 1000:
            raise TclError("too many nested evaluations (infinite loop?)")
        saved = self.frame
        self.frame = frame
        try:
            return format_number(self.eval(proc.body))
        except ReturnException as r:
            if r.code == 1:
                raise TclError(r.value)
            if r.code == 3:
                raise BreakException()
            if r.code == 4:
                raise ContinueException()
            return r.value
        except BreakException:
            raise TclError('invoked "break" outside of a loop')
        except ContinueException:
            raise TclError('invoked "continue" outside of a loop')
        finally:
            self.frame = saved

    def write(self, text, channel="stdout"):
        if channel == "stderr":
            self.stderr.write(text)
        else:
            self.stdout.write(text.encode("latin-1", "replace"))
