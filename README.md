# tcllite

A small interpreter for the Tcl language in pure Python (standard library
only).

```sh
python3 -m tcllite script.tcl arg1 arg2
python3 -m tcllite examples/report.tcl
```

From Python:

```python
import io, sys
import tcllite

status = tcllite.run(["script.tcl", "arg1"], sys.stdout.buffer, sys.stderr)
```

`run(argv, stdout, stderr)` runs the script `argv[0]` with the arguments
`argv[1:]`. `stdout` is a binary stream and `stderr` is a text stream. It
returns the exit status: 0, the value given to `exit`, or 1 after an uncaught
error (the message goes to `stderr`).

## Language

The Tcl syntax described in `Tcl(n)`: words, `{braces}`, `"quotes"`,
backslash sequences, `{*}` expansion, comments, `$var`, `${var}`, `$arr(index)`
and `[command]` substitution.

Variables are local to procedures; `global`, `upvar`, `uplevel` and `::name`
reach other frames. Arrays are associative variables written `name(index)`.

## Commands

* **Variables and procedures:** `set`, `unset`, `incr`, `append`, `lappend`,
  `proc`, `apply`, `return`, `global`, `upvar`, `uplevel`, `rename`, `info`.
* **Control flow:** `if`, `while`, `for`, `foreach`, `lmap`, `break`,
  `continue`, `switch` (`-exact`, `-glob`), `catch`, `error`, `eval`, `subst`,
  `exit`.
* **Lists:** `list`, `llength`, `lindex`, `lrange`, `linsert`, `lreplace`,
  `lset`, `lassign`, `lrepeat`, `lreverse`, `lsearch`, `lsort`, `concat`,
  `join`, `split`.
* **Strings:** `string` (`length`, `index`, `range`, `first`, `last`,
  `compare`, `equal`, `match`, `map`, `repeat`, `reverse`, `toupper`,
  `tolower`, `totitle`, `trim`, `trimleft`, `trimright`, `replace`, `is`,
  `wordstart`, `wordend`, `cat`), `format`, `scan`.
* **Expressions:** `expr` with the usual arithmetic, comparison, bitwise,
  logical and ternary operators, `eq`/`ne`/`in`/`ni`, `**`, and the math
  functions `abs`, `ceil`, `floor`, `round`, `int`, `wide`, `entier`, `double`,
  `bool`, `sqrt`, `isqrt`, `exp`, `log`, `log10`, `pow`, `fmod`, `hypot`,
  `min`, `max` and the trigonometric functions.
* **Arrays and dictionaries:** `array` (`set`, `get`, `names`, `size`,
  `exists`, `unset`) and `dict` (`create`, `get`, `set`, `unset`, `exists`,
  `keys`, `values`, `size`, `for`, `map`, `filter`, `append`, `lappend`,
  `incr`, `merge`, `remove`, `replace`, `info`).
* **Output:** `puts ?-nonewline? ?stdout|stderr? string`.

The script's arguments are in `argv` (a list), `argc` and `argv0`.

## Behaviour notes

* Numbers are Python integers (any size) and floats. Integer literals are
  decimal unless they start with `0x`, `0b` or `0o`.
* Floating-point results print in Python's shortest form (`1e+16`, `0.1`).
* Integer division and `%` truncate toward zero.
* `array names` and `array get` list elements in the order they were created.
* List elements that contain spaces are quoted with braces, and other special
  characters with backslashes.
