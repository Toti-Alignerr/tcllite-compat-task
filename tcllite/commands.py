"""Built-in commands."""

import decimal
import re

from .errors import BreakException, ContinueException, ExitException, ReturnException, TclError
from .expr import expr, format_number, parse_number, to_bool
from .interp import Array, Frame, Proc
from .lists import format_list, parse_list
from .parser import subst_backslashes

COMMANDS = {}


def command(name):
    def deco(fn):
        COMMANDS[name] = fn
        return fn
    return deco


def register(interp):
    interp.commands.update(COMMANDS)


def wrong_args(usage):
    raise TclError('wrong # args: should be "%s"' % usage)


def get_int(s):
    n = parse_number(s) if isinstance(s, str) else s
    if not isinstance(n, int):
        raise TclError('expected an integer but got "%s"' % s)
    return n


def get_index(s, length):
    s = s.strip()
    if s == "end":
        return length - 1
    if s.startswith("end-"):
        return length - 1 - get_int(s[4:])
    return get_int(s)


def glob_match(pattern, s, nocase=False):
    if nocase:
        pattern, s = pattern.lower(), s.lower()
    rx = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            rx.append(".*")
        elif c == "?":
            rx.append(".")
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j < 0:
                rx.append(re.escape(c))
            else:
                body = pattern[i + 1:j]
                rx.append("[" + body.replace("\\", "\\\\") + "]")
                i = j
        elif c == "\\" and i + 1 < len(pattern):
            i += 1
            rx.append(re.escape(pattern[i]))
        else:
            rx.append(re.escape(c))
        i += 1
    return re.fullmatch("".join(rx), s, re.S) is not None


# -- variables ----------------------------------------------------------------

@command("set")
def cmd_set(interp, argv):
    if len(argv) == 2:
        return interp.get_var(argv[1])
    if len(argv) == 3:
        return interp.set_var(argv[1], argv[2])
    wrong_args("set varName ?newValue?")


@command("unset")
def cmd_unset(interp, argv):
    args = argv[1:]
    complain = True
    while args and args[0].startswith("-"):
        if args[0] == "-nocomplain":
            complain = False
            args = args[1:]
        elif args[0] == "--":
            args = args[1:]
            break
        else:
            break
    for name in args:
        interp.unset_var(name, complain)


@command("incr")
def cmd_incr(interp, argv):
    if len(argv) not in (2, 3):
        wrong_args("incr varName ?increment?")
    amount = get_int(argv[2]) if len(argv) == 3 else 1
    cur = interp.get_var(argv[1]) if interp.var_exists(argv[1]) else "0"
    return interp.set_var(argv[1], str(get_int(cur) + amount))


@command("append")
def cmd_append(interp, argv):
    if len(argv) < 2:
        wrong_args("append varName ?value value ...?")
    cur = interp.get_var(argv[1]) if interp.var_exists(argv[1]) else ""
    return interp.set_var(argv[1], cur + "".join(argv[2:]))


@command("lappend")
def cmd_lappend(interp, argv):
    if len(argv) < 2:
        wrong_args("lappend varName ?value value ...?")
    cur = parse_list(interp.get_var(argv[1])) if interp.var_exists(argv[1]) else []
    return interp.set_var(argv[1], format_list(cur + argv[2:]))


@command("global")
def cmd_global(interp, argv):
    if interp.frame is interp.globals:
        return
    for name in argv[1:]:
        interp.link_var(name.lstrip(":"), interp.globals, name.lstrip(":"))


def _level_frame(interp, spec):
    if spec.startswith("#"):
        target = get_int(spec[1:])
    else:
        target = interp.frame.level - get_int(spec)
    f = interp.frame
    while f is not None and f.level != target:
        f = f.parent
    if f is None:
        raise TclError('bad level "%s"' % spec)
    return f


@command("upvar")
def cmd_upvar(interp, argv):
    args = argv[1:]
    level = "1"
    if len(args) % 2 == 1:
        level, args = args[0], args[1:]
    if not args:
        wrong_args("upvar ?level? otherVar localVar ?otherVar localVar ...?")
    frame = _level_frame(interp, level)
    for i in range(0, len(args), 2):
        interp.link_var(args[i + 1], frame, args[i])


@command("uplevel")
def cmd_uplevel(interp, argv):
    args = argv[1:]
    level = "1"
    if len(args) > 1 and (args[0].startswith("#") or args[0].isdigit()):
        level, args = args[0], args[1:]
    if not args:
        wrong_args("uplevel ?level? command ?arg ...?")
    frame = _level_frame(interp, level)
    saved = interp.frame
    interp.frame = frame
    try:
        return interp.eval(" ".join(args))
    finally:
        interp.frame = saved


# -- procedures and control flow ---------------------------------------------

@command("proc")
def cmd_proc(interp, argv):
    if len(argv) != 4:
        wrong_args("proc name args body")
    params = []
    for p in parse_list(argv[2]):
        parts = parse_list(p)
        if len(parts) == 1:
            params.append((parts[0], None))
        elif len(parts) == 2:
            params.append((parts[0], parts[1]))
        else:
            raise TclError('too many fields in argument specifier "%s"' % p)
    name = argv[1].lstrip(":")
    interp.procs[name] = Proc(name, params, argv[3])


@command("apply")
def cmd_apply(interp, argv):
    if len(argv) < 2:
        wrong_args("apply lambdaExpr ?arg1 arg2 ...?")
    parts = parse_list(argv[1])
    if len(parts) not in (2, 3):
        raise TclError('can\'t interpret "%s" as a lambda expression' % argv[1])
    params = []
    for p in parse_list(parts[0]):
        q = parse_list(p)
        params.append((q[0], q[1] if len(q) > 1 else None))
    return interp.call_proc(Proc("apply", params, parts[1]), argv[1:])


@command("return")
def cmd_return(interp, argv):
    args = argv[1:]
    code = 2
    while len(args) >= 2 and args[0].startswith("-"):
        opt, val = args[0], args[1]
        if opt == "-code":
            codes = {"ok": 0, "error": 1, "return": 2, "break": 3, "continue": 4}
            code = codes[val] if val in codes else get_int(val)
            if code == 0:
                code = 2
        args = args[2:]
    raise ReturnException(args[0] if args else "", code)


@command("break")
def cmd_break(interp, argv):
    raise BreakException()


@command("continue")
def cmd_continue(interp, argv):
    raise ContinueException()


@command("error")
def cmd_error(interp, argv):
    if len(argv) < 2 or len(argv) > 4:
        wrong_args("error message ?errorInfo? ?errorCode?")
    raise TclError(argv[1])


@command("exit")
def cmd_exit(interp, argv):
    raise ExitException(get_int(argv[1]) if len(argv) > 1 else 0)


@command("if")
def cmd_if(interp, argv):
    i = 1
    while True:
        if i >= len(argv):
            raise TclError('wrong # args: no expression after "if" argument')
        cond = argv[i]
        i += 1
        if i < len(argv) and argv[i] == "then":
            i += 1
        if i >= len(argv):
            raise TclError('wrong # args: no script following "%s" argument' % cond)
        body = argv[i]
        i += 1
        if to_bool(expr(interp, cond)):
            return interp.eval(body)
        if i >= len(argv):
            return ""
        if argv[i] == "elseif":
            i += 1
            continue
        if argv[i] == "else":
            i += 1
        if i >= len(argv):
            raise TclError('wrong # args: no script following "else" argument')
        return interp.eval(argv[i])


@command("while")
def cmd_while(interp, argv):
    if len(argv) != 3:
        wrong_args("while test command")
    while to_bool(expr(interp, argv[1])):
        try:
            interp.eval(argv[2])
        except BreakException:
            break
        except ContinueException:
            pass
    return ""


@command("for")
def cmd_for(interp, argv):
    if len(argv) != 5:
        wrong_args("for start test next command")
    interp.eval(argv[1])
    while to_bool(expr(interp, argv[2])):
        try:
            interp.eval(argv[4])
        except BreakException:
            break
        except ContinueException:
            pass
        interp.eval(argv[3])
    return ""


def _foreach(interp, argv, collect):
    if len(argv) < 4 or len(argv) % 2 != 0:
        wrong_args("%s varList list ?varList list ...? command" % argv[0])
    pairs = []
    for i in range(1, len(argv) - 1, 2):
        names = parse_list(argv[i])
        if not names:
            raise TclError("foreach varlist is empty")
        pairs.append((names, parse_list(argv[i + 1])))
    rounds = max((len(v) + len(n) - 1) // len(n) for n, v in pairs)
    out = []
    for r in range(rounds):
        for names, values in pairs:
            for k, name in enumerate(names):
                idx = r * len(names) + k
                interp.set_var(name, values[idx] if idx < len(values) else "")
        try:
            v = interp.eval(argv[-1])
            if collect:
                out.append(format_number(v))
        except BreakException:
            break
        except ContinueException:
            pass
    return format_list(out) if collect else ""


@command("foreach")
def cmd_foreach(interp, argv):
    return _foreach(interp, argv, False)


@command("lmap")
def cmd_lmap(interp, argv):
    return _foreach(interp, argv, True)


@command("switch")
def cmd_switch(interp, argv):
    args = argv[1:]
    mode = "exact"
    while args and args[0].startswith("-"):
        opt = args.pop(0)
        if opt == "--":
            break
        if opt in ("-exact", "-glob"):
            mode = opt[1:]
        else:
            raise TclError('bad option "%s": must be -exact, -glob, or --' % opt)
    if not args:
        wrong_args("switch ?switches? string pattern body ... ?default body?")
    value = args[0]
    pairs = parse_list(args[1]) if len(args) == 2 else args[1:]
    if len(pairs) % 2:
        raise TclError("extra switch pattern with no body")
    for i in range(0, len(pairs), 2):
        pat = pairs[i]
        hit = pat == "default" and i == len(pairs) - 2
        if not hit:
            hit = glob_match(pat, value) if mode == "glob" else pat == value
        if hit:
            j = i + 1
            while j < len(pairs) and pairs[j] == "-":
                j += 2
            if j >= len(pairs):
                raise TclError('no body specified for pattern "%s"' % pat)
            return interp.eval(pairs[j])
    return ""


@command("catch")
def cmd_catch(interp, argv):
    if len(argv) < 2 or len(argv) > 4:
        wrong_args("catch script ?resultVarName? ?optionVarName?")
    code, result = 0, ""
    try:
        result = format_number(interp.eval(argv[1]))
    except TclError as e:
        code, result = 1, e.msg
    except ReturnException as r:
        code, result = r.code, r.value
    except BreakException:
        code = 3
    except ContinueException:
        code = 4
    if len(argv) >= 3:
        interp.set_var(argv[2], result)
    if len(argv) == 4:
        interp.set_var(argv[3], format_list(["-code", str(code), "-level", "0"]))
    return str(code)


@command("eval")
def cmd_eval(interp, argv):
    if len(argv) < 2:
        wrong_args("eval arg ?arg ...?")
    return interp.eval(" ".join(argv[1:]))


@command("expr")
def cmd_expr(interp, argv):
    if len(argv) < 2:
        wrong_args("expr arg ?arg ...?")
    return format_number(expr(interp, " ".join(argv[1:])))


@command("subst")
def cmd_subst(interp, argv):
    args = argv[1:]
    flags = set()
    while len(args) > 1 and args[0].startswith("-"):
        flags.add(args.pop(0))
    if len(args) != 1:
        wrong_args("subst ?-nobackslashes? ?-nocommands? ?-novariables? string")
    from .parser import Parser
    s = args[0]
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and "-nobackslashes" not in flags:
            from .parser import backslash
            t, i = backslash(s, i)
            out.append(t)
        elif c == "$" and "-novariables" not in flags:
            p = Parser(s)
            p.i = i
            v = p.parse_variable()
            if v is None:
                out.append("$")
                i += 1
            else:
                out.append(format_number(interp.read_var_part(v)))
                i = p.i
        elif c == "[" and "-nocommands" not in flags:
            p = Parser(s)
            p.i = i
            text = p.parse_bracket()
            out.append(format_number(interp.eval(text)))
            i = p.i
        else:
            out.append(c)
            i += 1
    return "".join(out)


@command("rename")
def cmd_rename(interp, argv):
    if len(argv) != 3:
        wrong_args("rename oldName newName")
    old, new = argv[1].lstrip(":"), argv[2].lstrip(":")
    if old in interp.procs:
        p = interp.procs.pop(old)
        if new:
            interp.procs[new] = p
    elif old in interp.commands:
        c = interp.commands.pop(old)
        if new:
            interp.commands[new] = c
    else:
        raise TclError('can\'t rename "%s": command doesn\'t exist' % argv[1])


@command("info")
def cmd_info(interp, argv):
    if len(argv) < 2:
        wrong_args("info subcommand ?arg ...?")
    sub = argv[1]
    if sub == "exists":
        return "1" if interp.var_exists(argv[2]) else "0"
    if sub in ("args", "body", "default"):
        p = interp.procs.get(argv[2])
        if p is None:
            raise TclError('"%s" isn\'t a procedure' % argv[2])
        if sub == "args":
            return format_list([n for n, _ in p.params])
        if sub == "body":
            return p.body
        for n, d in p.params:
            if n == argv[3]:
                interp.set_var(argv[4], d or "")
                return "1" if d is not None else "0"
        raise TclError('procedure "%s" doesn\'t have an argument "%s"' % (argv[2], argv[3]))
    if sub == "level":
        if len(argv) == 2:
            return str(interp.frame.level)
        f = _level_frame(interp, "#" + argv[2]) if not argv[2].startswith("-") else None
        return format_list(f.args) if f else ""
    if sub in ("procs", "commands"):
        names = list(interp.procs) + (list(interp.commands) if sub == "commands" else [])
        if len(argv) > 2:
            names = [n for n in names if glob_match(argv[2], n)]
        return format_list(names)
    if sub in ("vars", "locals", "globals"):
        frame = interp.globals if sub == "globals" else interp.frame
        names = list(frame.vars)
        if len(argv) > 2:
            names = [n for n in names if glob_match(argv[2], n)]
        return format_list(names)
    raise TclError('unknown or ambiguous subcommand "%s"' % sub)


@command("puts")
def cmd_puts(interp, argv):
    args = argv[1:]
    newline = True
    if args and args[0] == "-nonewline":
        newline = False
        args = args[1:]
    channel = "stdout"
    if len(args) == 2:
        channel = args[0]
        args = args[1:]
    if len(args) != 1:
        wrong_args("puts ?-nonewline? ?channelId? string")
    if channel not in ("stdout", "stderr"):
        raise TclError('can not find channel named "%s"' % channel)
    interp.write(args[0] + ("\n" if newline else ""), channel)


# -- lists --------------------------------------------------------------------

@command("list")
def cmd_list(interp, argv):
    return format_list(argv[1:])


@command("llength")
def cmd_llength(interp, argv):
    if len(argv) != 2:
        wrong_args("llength list")
    return str(len(parse_list(argv[1])))


@command("lindex")
def cmd_lindex(interp, argv):
    if len(argv) < 2:
        wrong_args("lindex list ?index ...?")
    value = argv[1]
    indices = argv[2:]
    if len(indices) == 1:
        indices = parse_list(indices[0])
    for ix in indices:
        items = parse_list(value)
        k = get_index(ix, len(items))
        if k < 0 or k >= len(items):
            raise TclError("list index out of range")
        value = items[k]
    return value


@command("lrange")
def cmd_lrange(interp, argv):
    if len(argv) != 4:
        wrong_args("lrange list first last")
    items = parse_list(argv[1])
    a = max(get_index(argv[2], len(items)), 0)
    b = get_index(argv[3], len(items))
    return format_list(items[a:b + 1])


@command("linsert")
def cmd_linsert(interp, argv):
    if len(argv) < 3:
        wrong_args("linsert list index element ?element ...?")
    items = parse_list(argv[1])
    k = get_index(argv[2], len(items))
    if argv[2].strip().startswith("end"):
        k += 1
    k = min(max(k, 0), len(items))
    return format_list(items[:k] + argv[3:] + items[k:])


@command("lreplace")
def cmd_lreplace(interp, argv):
    if len(argv) < 4:
        wrong_args("lreplace list first last ?element element ...?")
    items = parse_list(argv[1])
    a = max(get_index(argv[2], len(items)), 0)
    b = get_index(argv[3], len(items))
    if a >= len(items) and items:
        raise TclError('list doesn\'t contain element %s' % argv[2])
    return format_list(items[:a] + argv[4:] + items[max(b + 1, a):])


@command("lset")
def cmd_lset(interp, argv):
    if len(argv) < 3:
        wrong_args("lset listVar index ?index...? value")
    value = argv[-1]
    indices = argv[2:-1]
    if len(indices) == 1:
        indices = parse_list(indices[0])

    def setin(lst, idx):
        if not idx:
            return value
        items = parse_list(lst)
        k = get_index(idx[0], len(items))
        if k < 0 or k >= len(items):
            raise TclError("list index out of range")
        items[k] = setin(items[k], idx[1:])
        return format_list(items)

    return interp.set_var(argv[1], setin(interp.get_var(argv[1]), indices))


@command("lassign")
def cmd_lassign(interp, argv):
    if len(argv) < 3:
        wrong_args("lassign list varName ?varName ...?")
    items = parse_list(argv[1])
    for k, name in enumerate(argv[2:]):
        interp.set_var(name, items[k] if k < len(items) else "")
    return format_list(items[len(argv) - 2:])


@command("lrepeat")
def cmd_lrepeat(interp, argv):
    if len(argv) < 3:
        wrong_args("lrepeat positiveCount value ?value ...?")
    n = get_int(argv[1])
    if n < 1:
        raise TclError("must have a count of at least 1")
    return format_list(argv[2:] * n)


@command("lreverse")
def cmd_lreverse(interp, argv):
    if len(argv) != 2:
        wrong_args("lreverse list")
    return format_list(parse_list(argv[1])[::-1])


@command("concat")
def cmd_concat(interp, argv):
    return " ".join(a.strip() for a in argv[1:] if a.strip())


@command("join")
def cmd_join(interp, argv):
    if len(argv) not in (2, 3):
        wrong_args("join list ?joinString?")
    return (argv[2] if len(argv) == 3 else " ").join(parse_list(argv[1]))


@command("split")
def cmd_split(interp, argv):
    if len(argv) not in (2, 3):
        wrong_args("split string ?splitChars?")
    s = argv[1]
    chars = argv[2] if len(argv) == 3 else " \t\n\r"
    if chars == "":
        return format_list(list(s))
    out, cur = [], []
    for c in s:
        if c in chars:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    out.append("".join(cur))
    return format_list(out)


def _sort_key(mode, nocase):
    def key(x):
        if mode == "integer":
            return get_int(x)
        if mode == "real":
            n = parse_number(x)
            if n is None:
                raise TclError('expected floating-point number but got "%s"' % x)
            return float(n)
        return x.lower() if nocase else x
    return key


@command("lsort")
def cmd_lsort(interp, argv):
    if len(argv) < 2:
        wrong_args("lsort ?options? list")
    opts = argv[1:-1]
    items = parse_list(argv[-1])
    mode, reverse, unique, nocase, index, command_ = "ascii", False, False, False, None, None
    i = 0
    while i < len(opts):
        o = opts[i]
        if o in ("-ascii", "-dictionary", "-integer", "-real"):
            mode = o[1:]
        elif o == "-increasing":
            reverse = False
        elif o == "-decreasing":
            reverse = True
        elif o == "-unique":
            unique = True
        elif o == "-nocase":
            nocase = True
        elif o == "-index":
            i += 1
            index = opts[i]
        elif o == "-command":
            i += 1
            command_ = opts[i]
        else:
            raise TclError('bad option "%s"' % o)
        i += 1
    keyfn = _sort_key(mode, nocase)
    if index is not None:
        base = keyfn

        def keyfn(x):
            e = parse_list(x)
            k = get_index(index, len(e))
            if k < 0 or k >= len(e):
                raise TclError('element %s missing from sublist "%s"' % (index, x))
            return base(e[k])
    if command_ is not None:
        import functools

        def cmp(a, b):
            return get_int(interp.eval(format_list(parse_list(command_) + [a, b])))
        result = sorted(items, key=functools.cmp_to_key(cmp), reverse=reverse)
    else:
        result = sorted(items, key=keyfn, reverse=reverse)
    if unique:
        out = []
        for x in result:
            if not out or keyfn(out[-1]) != keyfn(x):
                out.append(x)
        result = out
    return format_list(result)


@command("lsearch")
def cmd_lsearch(interp, argv):
    if len(argv) < 3:
        wrong_args("lsearch ?options? list pattern")
    opts = argv[1:-2]
    items = parse_list(argv[-2])
    pattern = argv[-1]
    mode, all_, inline, negate, start, nocase, index = "glob", False, False, False, 0, False, None
    i = 0
    while i < len(opts):
        o = opts[i]
        if o in ("-exact", "-glob", "-integer", "-real", "-dictionary"):
            mode = o[1:]
        elif o == "-all":
            all_ = True
        elif o == "-inline":
            inline = True
        elif o == "-not":
            negate = True
        elif o == "-nocase":
            nocase = True
        elif o == "-start":
            i += 1
            start = get_index(opts[i], len(items))
        elif o == "-index":
            i += 1
            index = opts[i]
        elif o in ("-sorted", "-increasing", "-decreasing", "-ascii", "-bisect"):
            pass
        else:
            raise TclError('bad option "%s"' % o)
        i += 1

    def match(x):
        if index is not None:
            e = parse_list(x)
            x = e[get_index(index, len(e))]
        if mode == "glob":
            r = glob_match(pattern, x, nocase)
        elif mode in ("integer", "real"):
            a, b = parse_number(x), parse_number(pattern)
            r = a is not None and a == b
        else:
            r = x.lower() == pattern.lower() if nocase else x == pattern
        return r != negate

    hits = [k for k in range(max(start, 0), len(items)) if match(items[k])]
    if all_:
        return format_list([items[k] for k in hits] if inline else [str(k) for k in hits])
    if not hits:
        return "" if inline else "-1"
    return items[hits[0]] if inline else str(hits[0])


# -- strings ------------------------------------------------------------------

_CLASSES = {
    "alnum": str.isalnum, "alpha": str.isalpha, "digit": str.isdigit, "lower": str.islower,
    "upper": str.isupper, "space": str.isspace, "ascii": lambda s: all(ord(c) < 128 for c in s),
    "xdigit": lambda s: all(c in "0123456789abcdefABCDEF" for c in s),
    "punct": lambda s: all(not c.isalnum() and not c.isspace() and c.isprintable() for c in s),
    "print": str.isprintable, "wordchar": lambda s: all(c.isalnum() or c == "_" for c in s),
    "control": lambda s: all(ord(c) < 32 or ord(c) == 127 for c in s),
    "graph": lambda s: all(c.isprintable() and not c.isspace() for c in s),
}


def _string_is(cls, s, strict):
    if s == "":
        return not strict
    if cls == "integer":
        return isinstance(parse_number(s), int) and s == s.strip()
    if cls == "double":
        return parse_number(s) is not None and s == s.strip()
    if cls == "boolean":
        return s.lower() in ("0", "1", "true", "false", "yes", "no", "on", "off")
    if cls == "true":
        return s.lower() in ("1", "true", "yes", "on")
    if cls == "false":
        return s.lower() in ("0", "false", "no", "off")
    if cls == "list":
        try:
            parse_list(s)
            return True
        except TclError:
            return False
    if cls in _CLASSES:
        return _CLASSES[cls](s)
    raise TclError('bad class "%s"' % cls)


@command("string")
def cmd_string(interp, argv):
    if len(argv) < 2:
        wrong_args("string subcommand ?argument ...?")
    sub, args = argv[1], argv[2:]
    if sub == "length":
        return str(len(args[0]))
    if sub == "index":
        s = args[0]
        k = get_index(args[1], len(s))
        return s[k] if 0 <= k < len(s) else ""
    if sub == "range":
        s = args[0]
        a = max(get_index(args[1], len(s)), 0)
        b = get_index(args[2], len(s))
        return s[a:b + 1]
    if sub in ("first", "last"):
        needle, hay = args[0], args[1]
        if sub == "first":
            start = get_index(args[2], len(hay)) if len(args) > 2 else 0
            return str(hay.find(needle, max(start, 0)))
        end = get_index(args[2], len(hay)) if len(args) > 2 else len(hay)
        return str(hay.rfind(needle, 0, end + 1))
    if sub in ("compare", "equal"):
        nocase = "-nocase" in args
        rest = [a for a in args if a != "-nocase"]
        length = None
        if "-length" in rest:
            k = rest.index("-length")
            length = get_int(rest[k + 1])
            rest = rest[:k] + rest[k + 2:]
        a, b = rest[0], rest[1]
        if nocase:
            a, b = a.lower(), b.lower()
        if length is not None and length >= 0:
            a, b = a[:length], b[:length]
        if sub == "equal":
            return "1" if a == b else "0"
        return str((a > b) - (a < b))
    if sub == "match":
        nocase = args[0] == "-nocase"
        if nocase:
            args = args[1:]
        return "1" if glob_match(args[0], args[1], nocase) else "0"
    if sub == "map":
        nocase = args[0] == "-nocase"
        if nocase:
            args = args[1:]
        mapping = parse_list(args[0])
        s = args[1]
        for k in range(0, len(mapping) - 1, 2):
            s = s.replace(mapping[k], mapping[k + 1])
        return s
    if sub == "repeat":
        return args[0] * get_int(args[1])
    if sub == "reverse":
        return args[0][::-1]
    if sub in ("toupper", "tolower", "totitle"):
        s = args[0]
        fn = {"toupper": str.upper, "tolower": str.lower, "totitle": str.capitalize}[sub]
        if len(args) == 1:
            return fn(s)
        a = max(get_index(args[1], len(s)), 0)
        b = get_index(args[2], len(s)) if len(args) > 2 else a
        return s[:a] + fn(s[a:b + 1]) + s[b + 1:]
    if sub in ("trim", "trimleft", "trimright"):
        chars = args[1] if len(args) > 1 else None
        fn = {"trim": str.strip, "trimleft": str.lstrip, "trimright": str.rstrip}[sub]
        return fn(args[0], chars)
    if sub == "replace":
        s = args[0]
        a = max(get_index(args[1], len(s)), 0)
        b = get_index(args[2], len(s))
        if b < a:
            return s
        return s[:a] + (args[3] if len(args) > 3 else "") + s[b + 1:]
    if sub == "is":
        strict = "-strict" in args
        rest = [a for a in args if a != "-strict"]
        return "1" if _string_is(rest[0], rest[-1], strict) else "0"
    if sub in ("wordstart", "wordend"):
        s, k = args[0], get_index(args[1], len(args[0]))
        k = min(max(k, 0), max(len(s) - 1, 0))
        isword = lambda c: c.isalnum() or c == "_"
        if sub == "wordstart":
            while k > 0 and isword(s[k - 1]) and isword(s[k]):
                k -= 1
            return str(k)
        if not s:
            return "0"
        if not isword(s[k]):
            return str(k + 1)
        while k < len(s) and isword(s[k]):
            k += 1
        return str(k)
    if sub == "cat":
        return "".join(args)
    raise TclError('unknown or ambiguous subcommand "%s"' % sub)


# -- format and scan ----------------------------------------------------------

_SPEC = re.compile(r"%([-+ #0]*)(\*|\d+)?(?:\.(\*|\d+))?([hlL]*)([diouxXeEfgGcs%])")


def _fmt_float(flags, width, prec, conv, value):
    if conv == "f":
        q = decimal.Decimal(repr(value)).quantize(decimal.Decimal(1).scaleb(-(6 if prec is None else prec)),
                                                  rounding=decimal.ROUND_HALF_UP)
        body = format(q, "f")
        if "+" in flags and value >= 0:
            body = "+" + body
        elif " " in flags and value >= 0:
            body = " " + body
        w = width or 0
        if "-" in flags:
            return body.ljust(w)
        if "0" in flags:
            sign = body[0] if body[0] in "+- " else ""
            return sign + body[len(sign):].rjust(w - len(sign), "0")
        return body.rjust(w)
    spec = "%" + flags + (str(width) if width is not None else "") + ("." + str(prec) if prec is not None else "") + conv
    return spec % value


@command("format")
def cmd_format(interp, argv):
    if len(argv) < 2:
        wrong_args("format formatString ?arg arg ...?")
    fmt, args = argv[1], argv[2:]
    out = []
    pos = 0
    ai = 0

    def next_arg():
        nonlocal ai
        if ai >= len(args):
            raise TclError("not enough arguments for all format specifiers")
        ai += 1
        return args[ai - 1]

    for m in _SPEC.finditer(fmt):
        out.append(fmt[pos:m.start()])
        pos = m.end()
        flags, width, prec, _, conv = m.groups()
        if conv == "%":
            out.append("%")
            continue
        if width == "*":
            width = get_int(next_arg())
        elif width:
            width = int(width)
        if prec == "*":
            prec = get_int(next_arg())
        elif prec:
            prec = int(prec)
        v = next_arg()
        if conv in "diouxX":
            n = parse_number(v)
            if n is None:
                raise TclError('expected integer but got "%s"' % v)
            n = int(n)
            spec = "%" + flags + (str(width) if width else "") + ("." + str(prec) if prec is not None else "") + ("d" if conv in "iu" else conv)
            out.append(spec % n)
        elif conv in "eEfgG":
            n = parse_number(v)
            if n is None:
                raise TclError('expected floating-point number but got "%s"' % v)
            out.append(_fmt_float(flags, width, prec, conv, float(n)))
        elif conv == "c":
            out.append(("%" + flags + (str(width) if width else "") + "s") % chr(get_int(v)))
        else:
            spec = "%" + flags + (str(width) if width else "") + ("." + str(prec) if prec is not None else "") + "s"
            out.append(spec % v)
    out.append(fmt[pos:])
    return "".join(out)


_SCAN = re.compile(r"%(\*)?(\d+)?([dioxXcsfeEgG]|\[\^?\]?[^\]]*\])")


@command("scan")
def cmd_scan(interp, argv):
    if len(argv) < 3:
        wrong_args("scan string format ?varName varName ...?")
    s, fmt, names = argv[1], argv[2], argv[3:]
    values = []
    i = 0
    pos = 0
    while pos < len(fmt):
        c = fmt[pos]
        if c.isspace():
            while i < len(s) and s[i].isspace():
                i += 1
            pos += 1
            continue
        if c != "%":
            if i < len(s) and s[i] == c:
                i += 1
                pos += 1
                continue
            break
        m = _SCAN.match(fmt, pos)
        if not m:
            raise TclError("bad scan conversion character")
        pos = m.end()
        skip, width, conv = m.groups()
        width = int(width) if width else None
        if conv not in "c" and not conv.startswith("["):
            while i < len(s) and s[i].isspace():
                i += 1
        rest = s[i:i + width] if width else s[i:]
        if conv in "di":
            mm = re.match(r"[-+]?\d+", rest)
        elif conv == "o":
            mm = re.match(r"[-+]?[0-7]+", rest)
        elif conv in "xX":
            mm = re.match(r"[-+]?[0-9a-fA-F]+", rest)
        elif conv in "feEgG":
            mm = re.match(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", rest)
        elif conv == "s":
            mm = re.match(r"\S+", rest)
        elif conv == "c":
            mm = re.match(r".", rest, re.S)
        else:
            mm = re.match(conv + "+", rest)
        if not mm:
            break
        text = mm.group()
        i += len(text)
        if skip:
            continue
        if conv in "di":
            values.append(str(int(text)))
        elif conv == "o":
            values.append(str(int(text, 8)))
        elif conv in "xX":
            values.append(str(int(text, 16)))
        elif conv in "feEgG":
            values.append(repr(float(text)))
        elif conv == "c":
            values.append(str(ord(text)))
        else:
            values.append(text)
    if names:
        for k, name in enumerate(names):
            if k < len(values):
                interp.set_var(name, values[k])
        return str(len(values))
    return format_list(values)


# -- arrays -------------------------------------------------------------------

@command("array")
def cmd_array(interp, argv):
    if len(argv) < 3:
        wrong_args("array subcommand ?arg ...?")
    sub, name = argv[1], argv[2]
    arr = interp.get_array(name)
    pattern = argv[3] if len(argv) > 3 else None
    if sub == "exists":
        return "1" if arr is not None else "0"
    if sub == "size":
        return str(len(arr) if arr is not None else 0)
    if sub == "names":
        if arr is None:
            return ""
        return format_list([k for k in arr if pattern is None or glob_match(pattern, k)])
    if sub == "get":
        if arr is None:
            return ""
        out = []
        for k, v in arr.items():
            if pattern is None or glob_match(pattern, k):
                out += [k, v]
        return format_list(out)
    if sub == "set":
        items = parse_list(argv[3])
        if len(items) % 2:
            raise TclError("list must have an even number of elements")
        for k in range(0, len(items), 2):
            interp.set_var(name, items[k + 1], items[k])
        if not items:
            interp.get_array(name, create=True)
        return ""
    if sub == "unset":
        if arr is None:
            return ""
        if pattern is None:
            interp.unset_var(name)
        else:
            for k in [k for k in arr if glob_match(pattern, k)]:
                del arr[k]
        return ""
    raise TclError('unknown or ambiguous subcommand "%s"' % sub)


# -- dictionaries -------------------------------------------------------------

def to_dict(s):
    items = parse_list(s)
    if len(items) % 2:
        raise TclError("missing value to go with key")
    d = {}
    for k in range(0, len(items), 2):
        d[items[k]] = items[k + 1]
    return d


def from_dict(d):
    out = []
    for k, v in d.items():
        out += [k, v]
    return format_list(out)


def _dict_get(value, keys):
    for k in keys:
        d = to_dict(value)
        if k not in d:
            raise TclError("key %s not found" % k)
        value = d[k]
    return value


def _dict_set(value, keys, new):
    d = to_dict(value)
    if len(keys) == 1:
        d[keys[0]] = new
    else:
        d[keys[0]] = _dict_set(d.get(keys[0], ""), keys[1:], new)
    return from_dict(d)


@command("dict")
def cmd_dict(interp, argv):
    if len(argv) < 2:
        wrong_args("dict subcommand ?argument ...?")
    sub, args = argv[1], argv[2:]
    if sub == "create":
        if len(args) % 2:
            wrong_args("dict create ?key value ...?")
        return from_dict(to_dict(format_list(args)))
    if sub == "get":
        return _dict_get(args[0], args[1:])
    if sub == "exists":
        try:
            _dict_get(args[0], args[1:])
            return "1"
        except TclError:
            return "0"
    if sub == "set":
        cur = interp.get_var(args[0]) if interp.var_exists(args[0]) else ""
        return interp.set_var(args[0], _dict_set(cur, args[1:-1], args[-1]))
    if sub == "unset":
        cur = to_dict(interp.get_var(args[0]) if interp.var_exists(args[0]) else "")
        cur.pop(args[1], None)
        return interp.set_var(args[0], from_dict(cur))
    if sub in ("keys", "values"):
        d = to_dict(args[0])
        vals = list(d.keys()) if sub == "keys" else list(d.values())
        if len(args) > 1:
            keys = [k for k in d if glob_match(args[1], k)] if sub == "keys" else [v for v in vals if glob_match(args[1], v)]
            vals = keys
        return format_list(vals)
    if sub == "size":
        return str(len(to_dict(args[0])))
    if sub == "for":
        names = parse_list(args[0])
        for k, v in to_dict(args[1]).items():
            interp.set_var(names[0], k)
            interp.set_var(names[1], v)
            try:
                interp.eval(args[2])
            except BreakException:
                break
            except ContinueException:
                pass
        return ""
    if sub in ("append", "lappend", "incr"):
        cur = to_dict(interp.get_var(args[0]) if interp.var_exists(args[0]) else "")
        key = args[1]
        if sub == "append":
            cur[key] = cur.get(key, "") + "".join(args[2:])
        elif sub == "lappend":
            cur[key] = format_list(parse_list(cur.get(key, "")) + args[2:])
        else:
            cur[key] = str(get_int(cur.get(key, "0")) + (get_int(args[2]) if len(args) > 2 else 1))
        return interp.set_var(args[0], from_dict(cur))
    if sub == "merge":
        d = {}
        for a in args:
            d.update(to_dict(a))
        return from_dict(d)
    if sub == "remove":
        d = to_dict(args[0])
        for k in args[1:]:
            d.pop(k, None)
        return from_dict(d)
    if sub == "replace":
        d = to_dict(args[0])
        d.update(to_dict(format_list(args[1:])))
        return from_dict(d)
    if sub == "filter":
        d = to_dict(args[0])
        kind = args[1]
        if kind == "key":
            return from_dict({k: v for k, v in d.items() if glob_match(args[2], k)})
        if kind == "value":
            return from_dict({k: v for k, v in d.items() if glob_match(args[2], v)})
        names = parse_list(args[2])
        out = {}
        for k, v in d.items():
            interp.set_var(names[0], k)
            interp.set_var(names[1], v)
            if to_bool(interp.eval(args[3])):
                out[k] = v
        return from_dict(out)
    if sub == "map":
        names = parse_list(args[0])
        out = {}
        for k, v in to_dict(args[1]).items():
            interp.set_var(names[0], k)
            interp.set_var(names[1], v)
            out[k] = format_number(interp.eval(args[2]))
        return from_dict(out)
    if sub == "info":
        return "%d entries in table" % len(to_dict(args[0]))
    raise TclError('unknown or ambiguous subcommand "%s"' % sub)
