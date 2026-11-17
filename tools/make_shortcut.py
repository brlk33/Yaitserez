"""Создаёт ярлык «Яйцерез» на рабочем столе (запуск без консоли, иконка-яйцо)."""
import os

import pythoncom
from win32com.shell import shell, shellcon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ID = "Yaytsa.Yaitserez"


def main():
    desktop = shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0)
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    exe = os.path.join(ROOT, ".venv", "Scripts", "Yaitserez.exe")
    if not os.path.isfile(exe):
        exe = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
    link.SetPath(exe)
    link.SetArguments(f'"{os.path.join(ROOT, "app.py")}"')
    link.SetWorkingDirectory(ROOT)
    link.SetIconLocation(os.path.join(ROOT, "ui", "icon.ico"), 0)
    link.SetDescription("Яйцерез — нарезка и синхронизация исходников")
    # тот же AppUserModelID, что у окна, — иначе Windows покажет на панели задач значок питона
    from win32com.propsys import propsys, pscon
    store = link.QueryInterface(propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
    store.Commit()
    path = os.path.join(desktop, "Яйцерез.lnk")
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(path, 0)
    # и в меню «Пуск»
    programs = shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, None, 0)
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(os.path.join(programs, "Яйцерез.lnk"), 0)
    print(path)


if __name__ == "__main__":
    main()
