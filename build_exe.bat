@echo off
setlocal
python -m pip install --upgrade pip
python -m pip install pyinstaller pyserial
pyinstaller --noconsole --onefile --name LeitorSerialPro serial_logger_pro.py
pause
