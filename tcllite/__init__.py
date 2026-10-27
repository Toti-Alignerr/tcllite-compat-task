"""tcllite: a small Tcl interpreter in pure Python."""

from .errors import BreakException, ContinueException, ExitException, ReturnException, TclError
from .interp import Interp
from .lists import format_list

__version__ = "0.4.0"
__all__ = ["run", "Interp"]


def run(argv, stdout, stderr):
    """Run the script argv[0] with arguments argv[1:]; returns the exit status."""
    if not argv:
        stderr.write("usage: tcllite script ?arg ...?\n")
        return 1
    path = argv[0]
    try:
        with open(path, encoding="latin-1") as f:
            script = f.read()
    except OSError:
        stderr.write('couldn\'t read file "%s": no such file or directory\n' % path)
        return 1
    interp = Interp(stdout, stderr)
    interp.set_var("argv0", path)
    interp.set_var("argv", format_list(argv[1:]))
    interp.set_var("argc", str(len(argv) - 1))
    status = 0
    try:
        interp.eval(script)
    except ExitException as e:
        status = e.status
    except ReturnException:
        status = 0
    except TclError as e:
        stderr.write(e.msg + "\n")
        status = 1
    except BreakException:
        stderr.write('invoked "break" outside of a loop\n')
        status = 1
    except ContinueException:
        stderr.write('invoked "continue" outside of a loop\n')
        status = 1
    except RecursionError:
        stderr.write("too many nested evaluations (infinite loop?)\n")
        status = 1
    try:
        stdout.flush()
    except (OSError, ValueError):
        pass
    return status
