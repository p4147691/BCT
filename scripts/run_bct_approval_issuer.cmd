@echo off
setlocal
rem User must open this launcher manually. No automatic sign or command-line grant.
python -I -m bct.approval_issuer
if errorlevel 1 (
  echo BCT approval issuer could not start. Verify Python/BCT installation.
  pause
)
