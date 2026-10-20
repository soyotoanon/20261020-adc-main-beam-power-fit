@echo off
cd /d "%~dp0"
call "D:\xilinx\Vivado\2023.2\bin\vivado.bat" -mode batch -source fpga/build.tcl
if errorlevel 1 (
  echo BUILD FAILED. Read the Vivado log.
  pause
  exit /b 1
)
echo Build finished. See fpga\build\mot556_calibration.bit
pause
