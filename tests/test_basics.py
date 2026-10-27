import unittest

from tests.helpers import tcl


class TestBasics(unittest.TestCase):
    def test_set_and_substitution(self):
        self.assertEqual(tcl('set x 3\nset y "x is $x"\nputs $y\nputs [set x]\n'), ("x is 3\n3\n", 0))

    def test_expr_arithmetic(self):
        self.assertEqual(tcl("puts [expr {2 + 3 * 4}]\nputs [expr {(2 + 3) * 4}]\n"), ("14\n20\n", 0))

    def test_proc_and_recursion(self):
        script = "proc fact {n} { if {$n <= 1} { return 1 }; expr {$n * [fact [expr {$n - 1}]]} }\nputs [fact 10]\n"
        self.assertEqual(tcl(script), ("3628800\n", 0))

    def test_foreach_and_lists(self):
        script = "set out {}\nforeach x {a b c} { lappend out [string toupper $x] }\nputs [join $out -]\nputs [llength $out]\n"
        self.assertEqual(tcl(script), ("A-B-C\n3\n", 0))

    def test_catch_error_message(self):
        self.assertEqual(tcl("puts [catch {error oops} msg]\nputs $msg\n"), ("1\noops\n", 0))

    def test_string_commands(self):
        script = "puts [string length hello]\nputs [string range hello 1 3]\nputs [string index hello end]\n"
        self.assertEqual(tcl(script), ("5\nell\no\n", 0))
