# Summarise a small table of scores.
set scores {
    ana 91
    bruno 78
    carla 85
    diego 62
}

proc grade {n} {
    if {$n >= 90} { return A }
    if {$n >= 80} { return B }
    if {$n >= 70} { return C }
    return D
}

set total 0
foreach {name score} $scores {
    set g [grade $score]
    lappend byGrade($g) $name
    incr total $score
    puts [format "%-6s %3d  %s" $name $score $g]
}
puts "average: [expr {$total / ([llength $scores] / 2)}]"
foreach g {A B C D} {
    if {[info exists byGrade($g)]} {
        puts "$g: [join $byGrade($g) {, }]"
    }
}
