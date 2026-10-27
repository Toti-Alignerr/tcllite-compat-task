import sys

from . import run

sys.setrecursionlimit(20000)
sys.exit(run(sys.argv[1:], sys.stdout.buffer, sys.stderr))
