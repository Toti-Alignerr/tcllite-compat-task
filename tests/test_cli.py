import unittest

from tests.helpers import tcl


class TestCommandLine(unittest.TestCase):
    def test_argv(self):
        self.assertEqual(tcl("puts $argc\nputs [lindex $argv 1]\n", ["a", "b c"]), ("2\nb c\n", 0))

    def test_exit_status(self):
        self.assertEqual(tcl("puts before\nexit 3\nputs after\n"), ("before\n", 3))

    def test_uncaught_error_exits_1(self):
        self.assertEqual(tcl("puts one\nnosuchcommand\nputs two\n"), ("one\n", 1))

    def test_puts_nonewline(self):
        self.assertEqual(tcl("puts -nonewline a\nputs b\n"), ("ab\n", 0))
