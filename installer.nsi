Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "WinVer.nsh"
!include "x64.nsh"

!ifndef APP_VERSION
  !define APP_VERSION "1.0.2"
!endif
!ifndef APP_EXE
  !define APP_EXE "build\installer-app\NightLightTray.exe"
!endif
!ifndef OUTPUT_FILE
  !define OUTPUT_FILE "NightLightTraySetup.exe"
!endif

; Установка для текущего пользователя без повышения прав
Name "NightLight Tray"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\NightLightTray"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetDatablockOptimize on
ShowInstDetails show
ShowUninstDetails show
Icon "resources\moon.ico"
UninstallIcon "resources\moon.ico"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1049 "ProductName" "NightLight Tray"
VIAddVersionKey /LANG=1049 "FileDescription" "Установщик NightLight Tray"
VIAddVersionKey /LANG=1049 "FileVersion" "${APP_VERSION}"

!ifndef UNINSTALL_KEY
  !define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\NightLightTray"
!endif
!ifndef START_MENU_FOLDER
  !define START_MENU_FOLDER "NightLight Tray"
!endif
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
!define MUI_ABORTWARNING
!define MUI_ICON "resources\moon.ico"
!define MUI_UNICON "resources\moon.ico"
!define MUI_WELCOMEPAGE_TEXT "Мастер установит NightLight Tray для вашей учётной записи.$\r$\n$\r$\nPython, Node.js и права администратора не нужны.$\r$\n$\r$\nПеред установкой закройте работающий NightLight Tray через меню трея → «Выход».$\r$\n$\r$\nАвтозапуск можно включить позже в настройках приложения."
!define MUI_FINISHPAGE_RUN "$INSTDIR\NightLightTray.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Запустить NightLight Tray"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "Russian"

Function .onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "Нужна 64-разрядная Windows 11."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin11}
    MessageBox MB_OK|MB_ICONSTOP "Нужна Windows 11."
    Abort
  ${EndIf}
FunctionEnd

Section "Установка"
  ReadRegStr $1 HKCU "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $1 != ""
    ${If} $1 != $INSTDIR
      Abort "Приложение уже установлено в $1. Чтобы сменить папку, сначала удалите предыдущую установку."
    ${EndIf}
  ${Else}
    IfFileExists "$INSTDIR\NightLightTray.exe" 0 +2
      Abort "В выбранной папке уже есть NightLightTray.exe. Выберите другую папку."
  ${EndIf}
  ; Проверка не открывает окно и не завершает работающую программу
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=NightLightTray.exe "${APP_EXE}"
  check_running:
  ClearErrors
  ExecWait '"$PLUGINSDIR\NightLightTray.exe" --installer-check' $0
  ${If} ${Errors}
    Abort "Не удалось запустить проверку приложения."
  ${EndIf}
  ${If} $0 == 3
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "NightLight Tray уже работает. Выберите «Выход» в меню трея, затем нажмите «Повторить»." /SD IDCANCEL IDRETRY check_running
    Abort
  ${EndIf}
  ${If} $0 != 0
    Abort "Не удалось проверить состояние приложения."
  ${EndIf}
  SetOutPath "$INSTDIR"
  File /oname=NightLightTray.exe "${APP_EXE}"
  File "tools\WNL_LICENSE.txt"
  File "tools\WNL_SOURCE.txt"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\${START_MENU_FOLDER}"
  CreateShortcut "$SMPROGRAMS\${START_MENU_FOLDER}\NightLight Tray.lnk" "$INSTDIR\NightLightTray.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "NightLight Tray"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\NightLightTray.exe,0"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
SectionEnd

Function un.onInit
  SetShellVarContext current
FunctionEnd

Section "Uninstall"
  cleanup:
  ClearErrors
  ExecWait '"$INSTDIR\NightLightTray.exe" --uninstall-cleanup' $0
  ${If} ${Errors}
    Abort "Не удалось запустить приложение для безопасного удаления автозапуска."
  ${EndIf}
  ${If} $0 == 3
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Выберите «Выход» в меню трея NightLight Tray, затем нажмите «Повторить»." /SD IDCANCEL IDRETRY cleanup
    Abort
  ${EndIf}
  ${If} $0 != 0
    Abort "Не удалось безопасно удалить автозапуск. Файлы приложения сохранены."
  ${EndIf}
  ; Никаких рекурсивных удалений и изменений настройки ночного света
  ClearErrors
  Delete "$INSTDIR\NightLightTray.exe"
  ${If} ${Errors}
    Abort "Не удалось удалить EXE. Закройте приложение и повторите удаление."
  ${EndIf}
  Delete "$INSTDIR\WNL_LICENSE.txt"
  Delete "$INSTDIR\WNL_SOURCE.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${START_MENU_FOLDER}\NightLight Tray.lnk"
  RMDir "$SMPROGRAMS\${START_MENU_FOLDER}"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
