; Яйцерез — установщик (NSIS 3, Unicode). Копирует программу и запускает install.bat,
; который ставит Python, библиотеки и ffmpeg (как у VoiceType).
Unicode true
SetCompressor /SOLID lzma
ManifestDPIAware true
RequestExecutionLevel user

!define APPNAME "Яйцерез"
!define EXE ".venv\Scripts\Yaitserez.exe"
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Yaitserez"
!ifndef VERSION
  !define VERSION "1.2.0"
!endif

Name "${APPNAME}"
OutFile "..\Yaitserez-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\Yaitserez"
InstallDirRegKey HKCU "Software\Yaitserez" "InstallDir"
BrandingText "${APPNAME} ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1049 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=1049 "FileDescription" "Установщик ${APPNAME}"
VIAddVersionKey /LANG=1049 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1049 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1049 "CompanyName" "Яйца Cloud"
VIAddVersionKey /LANG=1049 "LegalCopyright" "Яйца Cloud"

!include "MUI2.nsh"
!define MUI_ICON "..\ui\icon.ico"
!define MUI_UNICON "..\ui\icon.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION RunApp
!define MUI_FINISHPAGE_RUN_TEXT "Запустить ${APPNAME}"
!define MUI_INSTFILESPAGE_COLORS "FFFFFF 191919"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Russian"

Section "Install"
  SetDetailsView show
  SetOutPath "$INSTDIR"
  File "..\app.py"
  File "..\requirements.txt"
  File "..\install.bat"
  File "..\version.txt"
  File "..\README.md"
  File "..\Яйцерез.bat"
  SetOutPath "$INSTDIR\yaitserez"
  File "..\yaitserez\*.py"
  SetOutPath "$INSTDIR\ui"
  File "..\ui\index.html"
  File "..\ui\style.css"
  File "..\ui\app.js"
  File "..\ui\i18n.js"
  File "..\ui\timeline.js"
  File "..\ui\editor.js"
  File "..\ui\logo.svg"
  File "..\ui\logo.png"
  File "..\ui\icon.ico"
  SetOutPath "$INSTDIR\tools"
  File "..\tools\make_icon.py"
  File "..\tools\make_exe.py"
  File "..\tools\make_shortcut.py"
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  DetailPrint "Скачиваю Python, библиотеки и ffmpeg — это 5–15 минут, нужен интернет…"
  nsExec::ExecToLog '"$INSTDIR\install.bat" /silent'
  Pop $0
  StrCmp $0 "0" +3
    MessageBox MB_ICONEXCLAMATION "Установка не завершилась. Откройте install.bat в папке программы, чтобы увидеть ошибку."
    Abort

  WriteRegStr HKCU "Software\Yaitserez" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${REGKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${REGKEY}" "Publisher" "Яйца Cloud"
  WriteRegStr HKCU "${REGKEY}" "DisplayIcon" "$INSTDIR\ui\icon.ico"
  WriteRegStr HKCU "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "URLInfoAbout" "https://github.com/brlk33/Yaitserez"
  WriteRegStr HKCU "${REGKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${REGKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${REGKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${REGKEY}" "EstimatedSize" 2500000
SectionEnd

Function RunApp
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\${EXE}" "$INSTDIR\app.py"'
FunctionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  RMDir /r "$INSTDIR\.venv"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\yaitserez"
  RMDir /r "$INSTDIR\ui"
  Delete "$INSTDIR\*.*"
  ; data (кеш и настройки) удаляем — это всё пересоздаётся
  RMDir /r "$INSTDIR\data"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${REGKEY}"
  DeleteRegKey HKCU "Software\Yaitserez"
SectionEnd
