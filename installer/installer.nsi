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
  !define VERSION "1.3.0"
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
!include "nsDialogs.nsh"
!include "LogicLib.nsh"

Var LLM
Var RB9
Var RB4
Var RB0
!define MUI_ICON "..\ui\icon.ico"
!define MUI_UNICON "..\ui\icon.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION RunApp
!define MUI_FINISHPAGE_RUN_TEXT "Запустить ${APPNAME}"
!define MUI_INSTFILESPAGE_COLORS "FFFFFF 191919"

!insertmacro MUI_PAGE_DIRECTORY
Page custom LlmPage LlmLeave
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
  File "..\tools\get_llm.py"
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  DetailPrint "Скачиваю Python, библиотеки и ffmpeg — это 5–15 минут, нужен интернет…"
  nsExec::ExecToLog '"$INSTDIR\install.bat" /silent /llm=$LLM'
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

; Какую нейросеть для разбора дублей скачать: больше места — точнее, меньше — легче
Function LlmPage
  !insertmacro MUI_HEADER_TEXT "Нейросеть для разбора дублей" "Она понимает смысл: находит перефразы и брошенные мысли"
  nsDialogs::Create 1018
  Pop $0
  ${NSD_CreateLabel} 0 0 100% 24u "Выберите, какую скачать. Поменять можно потом в настройках программы."
  Pop $0
  ${NSD_CreateRadioButton} 0 30u 100% 12u "Qwen3.5 9B — точнее (5,7 ГБ, видеокарта NVIDIA от 8 ГБ)"
  Pop $RB9
  ${NSD_CreateLabel} 12u 43u 95% 10u "Лучше ловит перефразы и переговорённые абзацы."
  Pop $0
  ${NSD_CreateRadioButton} 0 60u 100% 12u "Qwen3.5 4B — легче (2,7 ГБ)"
  Pop $RB4
  ${NSD_CreateLabel} 12u 73u 95% 10u "Быстрее и меньше места; перефразы замечает чуть хуже."
  Pop $0
  ${NSD_CreateRadioButton} 0 90u 100% 12u "Не скачивать сейчас"
  Pop $RB0
  ${NSD_CreateLabel} 12u 103u 95% 10u "Дубли будут разбираться только по словам."
  Pop $0
  ${If} $LLM == "4b"
    ${NSD_Check} $RB4
  ${ElseIf} $LLM == "none"
    ${NSD_Check} $RB0
  ${Else}
    ${NSD_Check} $RB9
  ${EndIf}
  nsDialogs::Show
FunctionEnd

Function LlmLeave
  ${NSD_GetState} $RB4 $0
  ${NSD_GetState} $RB0 $1
  ${If} $0 == ${BST_CHECKED}
    StrCpy $LLM "4b"
  ${ElseIf} $1 == ${BST_CHECKED}
    StrCpy $LLM "none"
  ${Else}
    StrCpy $LLM "9b"
  ${EndIf}
FunctionEnd

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
