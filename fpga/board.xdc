# ATK-DF7A35 V2.1. Pin facts transcribed from existing hardware wiring records;
# all RTL and this constraint file are independent of the previous project.
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property -dict {PACKAGE_PIN R4 IOSTANDARD LVCMOS33} [get_ports sys_clk]
set_property -dict {PACKAGE_PIN U2 IOSTANDARD LVCMOS33} [get_ports sys_rst_n]
create_clock -name system50 -period 20.000 [get_ports sys_clk]
set_property -dict {PACKAGE_PIN R17 IOSTANDARD LVCMOS33} [get_ports {adc_d[0]}]
set_property -dict {PACKAGE_PIN J16 IOSTANDARD LVCMOS33} [get_ports {adc_d[1]}]
set_property -dict {PACKAGE_PIN N15 IOSTANDARD LVCMOS33} [get_ports {adc_d[2]}]
set_property -dict {PACKAGE_PIN P19 IOSTANDARD LVCMOS33} [get_ports {adc_d[3]}]
set_property -dict {PACKAGE_PIN M17 IOSTANDARD LVCMOS33} [get_ports {adc_d[4]}]
set_property -dict {PACKAGE_PIN P20 IOSTANDARD LVCMOS33} [get_ports {adc_d[5]}]
set_property -dict {PACKAGE_PIN M16 IOSTANDARD LVCMOS33} [get_ports {adc_d[6]}]
set_property -dict {PACKAGE_PIN M15 IOSTANDARD LVCMOS33} [get_ports {adc_d[7]}]
set_property -dict {PACKAGE_PIN L15 IOSTANDARD LVCMOS33} [get_ports {adc_d[8]}]
set_property -dict {PACKAGE_PIN L14 IOSTANDARD LVCMOS33} [get_ports {adc_d[9]}]
set_property -dict {PACKAGE_PIN J17 IOSTANDARD LVCMOS33} [get_ports {adc_d[10]}]
set_property -dict {PACKAGE_PIN K17 IOSTANDARD LVCMOS33} [get_ports {adc_d[11]}]
set_property -dict {PACKAGE_PIN K18 IOSTANDARD LVCMOS33} [get_ports {adc_d[12]}]
set_property -dict {PACKAGE_PIN K19 IOSTANDARD LVCMOS33} [get_ports {adc_d[13]}]
set_property -dict {PACKAGE_PIN H19 IOSTANDARD LVCMOS33 DRIVE 8 SLEW SLOW} [get_ports adc_clk]
set_property -dict {PACKAGE_PIN J19 IOSTANDARD LVCMOS33} [get_ports adc_oeb_n]
set_property -dict {PACKAGE_PIN F20 IOSTANDARD LVCMOS33} [get_ports adc_otr]
set_property -dict {PACKAGE_PIN F19 IOSTANDARD LVCMOS33} [get_ports adc_pdn]
set_property -dict {PACKAGE_PIN T6 IOSTANDARD LVCMOS33 DRIVE 8 SLEW SLOW} [get_ports uart_txd]

# Board assumption: ADC delay + external round trip <=16 ns, minimum >=0 ns.
# Both multiplexed bus phases are constrained; no false-path on ADC data.
# Capture enable is phase 3 / 8, exactly the third system edge after launch.
create_generated_clock -name adc5 -source [get_ports sys_clk] -divide_by 10 [get_ports adc_clk]
set_input_delay -clock adc5 -max 16.000 [get_ports {adc_d[*] adc_otr}]
set_input_delay -clock adc5 -min 0.000 [get_ports {adc_d[*] adc_otr}]
set_input_delay -clock adc5 -clock_fall -add_delay -max 16.000 [get_ports {adc_d[*] adc_otr}]
set_input_delay -clock adc5 -clock_fall -add_delay -min 0.000 [get_ports {adc_d[*] adc_otr}]
# Three-cycle setup, paired with two-cycle hold correction. Restrict to ADC
# capture registers; this does not relax arithmetic or remove bus timing checks.
set capture_regs [get_cells -hier -regexp {.*captured(_otr)?_reg(\[[0-9]+\])?}]
set_multicycle_path 3 -setup -end -from [get_ports {adc_d[*] adc_otr}] -to $capture_regs
set_multicycle_path 2 -hold -end -from [get_ports {adc_d[*] adc_otr}] -to $capture_regs
# Asynchronous reset only; deassertion passes through two synchronizer stages.
set_false_path -from [get_ports sys_rst_n]
# UART is asynchronous to the USB bridge; no receiver clock exists in this design.
set_output_delay -clock system50 -max 0 [get_ports uart_txd]
set_output_delay -clock system50 -min 0 [get_ports uart_txd]
