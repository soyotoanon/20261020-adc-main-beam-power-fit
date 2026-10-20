set root [file dirname [file normalize [info script]]]
set out [file join $root build]
file mkdir $out
read_verilog -sv [file join $root calibration_top.sv]
read_xdc [file join $root board.xdc]
synth_design -top calibration_top -part xc7a35tfgg484-2
if {[llength [get_cells -hier -regexp {.*captured(_otr)?_reg(\[[0-9]+\])?}]] != 15} {
    error "Expected exactly 15 ADC capture registers"
}
opt_design
place_design
route_design
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing.rpt]
report_drc -file [file join $out drc.rpt]
report_utilization -file [file join $out utilization.rpt]
write_checkpoint -force [file join $out routed.dcp]
set setup_paths [get_timing_paths -delay_type max -max_paths 1]
set hold_paths [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup_paths] == 0 || [llength $hold_paths] == 0} {error "Missing timing paths"}
if {[get_property SLACK $setup_paths] < 0 || [get_property SLACK $hold_paths] < 0} {
    error "Timing failed; bitstream not released"
}
if {[llength [get_drc_violations -filter {SEVERITY == Error}]]} {error "DRC errors"}
write_bitstream -force [file join $out mot556_calibration.bit]
puts "BUILD_PASS"
