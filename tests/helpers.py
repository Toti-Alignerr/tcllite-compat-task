import io
import os
import tempfile

import tcllite


def tcl(script, args=(), files=None):
    """Run a script with tcllite in a scratch directory; returns (stdout text, exit status)."""
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        for name, text in (files or {}).items():
            with open(os.path.join(d, name), "w", encoding="latin-1") as f:
                f.write(text)
        with open(os.path.join(d, "script.tcl"), "w", encoding="latin-1") as f:
            f.write(script)
        os.chdir(d)
        try:
            out, err = io.BytesIO(), io.StringIO()
            status = tcllite.run(["script.tcl", *args], out, err)
        finally:
            os.chdir(old)
    return out.getvalue().decode("latin-1"), status
