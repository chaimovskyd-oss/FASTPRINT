import sys
try: import winreg
except ImportError: print('Run on Windows only'); sys.exit(1)
KEY=r'Software\Classes\SystemFileAssociations\image\shell\HadishSmartPhotoPrint'
def delete_tree(root,path):
    try:
        with winreg.OpenKey(root,path,0,winreg.KEY_READ|winreg.KEY_WRITE) as k:
            while True:
                try: sub=winreg.EnumKey(k,0); delete_tree(root,path+'\\'+sub)
                except OSError: break
        winreg.DeleteKey(root,path)
    except FileNotFoundError: pass
delete_tree(winreg.HKEY_CURRENT_USER, KEY)
print('Removed')
