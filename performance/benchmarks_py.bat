@echo off
if "%~1"=="" goto run_sequence

REM Executed when an argument is provided

timer python %1.py
goto :eof

:run_sequence
REM Executed when no arguments are provided
call "%~f0" cs
call "%~f0" fib
call "%~f0" prime
call "%~f0" crc64
call "%~f0" e_pi
call "%~f0" mb
call "%~f0" sim
call "%~f0" fin

goto :eof
