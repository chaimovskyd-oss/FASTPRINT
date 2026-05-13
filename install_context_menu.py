import sys
from pathlib import Path
try:
    import winreg
except ImportError:
    print('Run on Windows only'); sys.exit(1)
ROOT=Path(__file__).resolve().parent
APP=ROOT/'launcher.py'
ICON=ROOT/'assets'/'hadish_printer.ico'
PYTHONW=Path(sys.executable).with_name('pythonw.exe')
if not PYTHONW.exists(): PYTHONW=Path(sys.executable)
KEY=r'Software\Classes\SystemFileAssociations\image\shell\HadishSmartPhotoPrint'
CMD=KEY+r'\command'
command=f'"{PYTHONW}" "{APP}" "%1"'
with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:
    winreg.SetValueEx(k,None,0,winreg.REG_SZ,'הדפס חכם - חדיש')
    winreg.SetValueEx(k,'Icon',0,winreg.REG_SZ,str(ICON))
    winreg.SetValueEx(k,'MultiSelectModel',0,winreg.REG_SZ,'Document')
with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CMD) as k:
    winreg.SetValueEx(k,None,0,winreg.REG_SZ,command)
print('Installed context menu:', command)
