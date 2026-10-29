; ============================================================================
; NeuroFlex Dashboard - Instalador NSIS con MUI2
; ----------------------------------------------------------------------------
; Para compilar: arrastrar este archivo sobre makensis.exe
; Assets graficos generados por installer/assets/build_assets.py
; Compatible con instalacion silenciosa (/S) para el updater.
; ============================================================================

!define APP_NAME "NeuroFlex"
!ifndef APP_VERSION
!define APP_VERSION "0.0.1"
!endif
!define APP_PUBLISHER "NeuroFlex"
!define APP_URL "https://github.com/basstiago/neuroflex-dashboard"
!define INSTALL_DIR "$PROGRAMFILES\NeuroFlex"
!define APP_REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

; ---------------------------------------------------------------------------
; Includes
; ---------------------------------------------------------------------------
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"

; ---------------------------------------------------------------------------
; Variables de la pagina de configuracion
; ---------------------------------------------------------------------------
Var hConfigPage
Var hTokenPage
Var txtApiUrl
Var txtClientId
Var valApiUrl
Var valClientId
Var txtGitHubToken
Var valGitHubToken

; Pagina de deteccion de instalacion previa
Var hChoicePage
Var radioRepair
Var radioFresh
Var radioRemove
Var installMode           ; 0 = nuevo (default), 1 = reparar, 2 = instalar desde cero
Var hasPreviousInstall    ; 1 = se detecto una instalacion previa
Var previousInstallDir

; Valores previos del .env (para preservarlos en actualizaciones / modo /S)
Var oldSecretKey
Var oldClientId
Var oldApiUrl
Var oldGitHubToken
Var oldWazuhAuditLogPath
Var oldWazuhAuditHashKey
; Valores finales que se escriben en el .env
Var finalSecretKey
Var finalClientId
Var finalApiUrl
Var finalGitHubToken

; ---------------------------------------------------------------------------
; Configuracion visual global MUI2
; ---------------------------------------------------------------------------
!define MUI_ICON "assets\neuroflex.ico"
!define MUI_UNICON "assets\neuroflex.ico"

; Header image (franja superior en directory e instfiles)
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "assets\header.bmp"
!define MUI_HEADERIMAGE_RIGHT

; Panel lateral welcome/finish
!define MUI_WELCOMEFINISHPAGE_BITMAP "assets\welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "assets\un-welcome.bmp"

; Abort warning
!define MUI_ABORTWARNING
!define MUI_UNABORTWARNING

; Branding text (barra inferior)
BrandingText "NeuroFlex ${APP_VERSION} · neuroflex-dashboard"

; ---------------------------------------------------------------------------
; Paginas del installer
; Cada bloque de defines va justo antes del insertmacro de esa pagina.
; ---------------------------------------------------------------------------

; --- Welcome ---
!define MUI_WELCOMEPAGE_TITLE "Bienvenido al asistente de instalacion de NeuroFlex"
!define MUI_WELCOMEPAGE_TEXT "Este programa instalara NeuroFlex Dashboard en su equipo.$\r$\n$\r$\nNeuroFlex Dashboard es una aplicacion orientada a profesionales de la salud para la visualizacion de sesiones clinicas, ejecucion de inferencia y gestion de informes.$\r$\n$\r$\nHaga clic en Siguiente para continuar o en Cancelar para salir."
!insertmacro MUI_PAGE_WELCOME

; --- Detectar instalacion previa: Reparar / Instalar desde cero / Eliminar ---
Page custom ChoicePageCreate ChoicePageLeave

; --- Directory ---
!define MUI_DIRECTORYPAGE_TEXT_TOP "Seleccione la carpeta donde desea instalar NeuroFlex Dashboard.$\r$\n$\r$\nSe recomienda mantener la ubicacion predeterminada."
!insertmacro MUI_PAGE_DIRECTORY

; --- Configuracion de API (pagina custom nsDialogs) ---
Page custom ConfigPageCreate ConfigPageLeave

; --- Configuracion del token de GitHub (pagina custom nsDialogs) ---
Page custom TokenPageCreate TokenPageLeave

; --- InstFiles (con callback para log oscuro) ---
!define MUI_PAGE_CUSTOMFUNCTION_SHOW OnInstFilesShow
!insertmacro MUI_PAGE_INSTFILES

; --- Finish ---
!define MUI_FINISHPAGE_TITLE "Instalacion completada"
!define MUI_FINISHPAGE_TEXT "NeuroFlex Dashboard se ha instalado correctamente.$\r$\n$\r$\nHaga clic en Finalizar para cerrar este asistente."
!define MUI_FINISHPAGE_RUN "$INSTDIR\neuroflex.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Ejecutar NeuroFlex al finalizar"
!define MUI_FINISHPAGE_SHOWREADME ""
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!define MUI_FINISHPAGE_NOREBOOTSUPPORT
!insertmacro MUI_PAGE_FINISH

; ---------------------------------------------------------------------------
; Paginas del uninstaller
; ---------------------------------------------------------------------------

; --- UnWelcome ---
!define MUI_UNWELCOMEPAGE_TITLE "Bienvenido al asistente de desinstalacion de NeuroFlex"
!define MUI_UNWELCOMEPAGE_TEXT "Este programa eliminara NeuroFlex Dashboard de su equipo.$\r$\n$\r$\nHaga clic en Siguiente para continuar o en Cancelar para salir."
!insertmacro MUI_UNPAGE_WELCOME

; --- UnConfirm ---
!define MUI_UNCONFIRMPAGE_TITLE "Confirmar desinstalacion"
!define MUI_UNCONFIRMPAGE_TEXT "NeuroFlex Dashboard se va a desinstalar de la siguiente carpeta:$\r$\n$\r$\n$INSTDIR$\r$\n$\r$\nHaga clic en Desinstalar para continuar."
!insertmacro MUI_UNPAGE_CONFIRM

; --- UnInstFiles (con callback para log oscuro) ---
!define MUI_PAGE_CUSTOMFUNCTION_SHOW un.OnUnInstFilesShow
!insertmacro MUI_UNPAGE_INSTFILES

; --- UnFinish ---
!define MUI_UNFINISHPAGE_TITLE "Desinstalacion completada"
!define MUI_UNFINISHPAGE_TEXT "NeuroFlex Dashboard se ha desinstalado correctamente.$\r$\n$\r$\nHaga clic en Finalizar para cerrar este asistente."
!insertmacro MUI_UNPAGE_FINISH

; ---------------------------------------------------------------------------
; Idioma
; ---------------------------------------------------------------------------
!insertmacro MUI_LANGUAGE "Spanish"

; ---------------------------------------------------------------------------
; Pagina custom: instalacion previa detectada (Reparar / Desde cero / Eliminar)
; ---------------------------------------------------------------------------
Function ChoicePageCreate
    ; Sin instalacion previa la pagina se salta por completo.
    ${If} $hasPreviousInstall != 1
        Abort
    ${EndIf}

    !insertmacro MUI_HEADER_TEXT "Instalacion previa detectada" "Seleccione que desea hacer con la instalacion existente."

    nsDialogs::Create 1018
    Pop $hChoicePage
    ${If} $hChoicePage == error
        Abort
    ${EndIf}

    ${NSD_CreateLabel} 0 0 100% 26u "Se detecto una instalacion previa de NeuroFlex en:$\r$\n$previousInstallDir$\r$\nSeleccione como desea continuar."
    Pop $0

    ; --- Actualizar/Reparar ---
    ${NSD_CreateRadioButton} 0 40u 100% 26u "Actualizar/Reparar$\r$\nReinstala el programa sin perder los datos configurados (.env, sesiones e informes)."
    Pop $radioRepair
    ${NSD_SetState} $radioRepair ${BST_CHECKED}
    StrCpy $installMode 1

    ; --- Instalar desde cero ---
    ${NSD_CreateRadioButton} 0 78u 100% 26u "Instalar desde cero$\r$\nReinstala el programa y elimina la configuracion y los datos previos (.env, sesiones e informes)."
    Pop $radioFresh
    ${NSD_SetState} $radioFresh ${BST_UNCHECKED}

    ; --- Eliminar ---
    ${NSD_CreateRadioButton} 0 116u 100% 22u "Eliminar$\r$\nDesinstala NeuroFlex y cierra este asistente."
    Pop $radioRemove
    ${NSD_SetState} $radioRemove ${BST_UNCHECKED}

    nsDialogs::Show
FunctionEnd

Function ChoicePageLeave
    ${NSD_GetState} $radioRepair $0
    ${If} $0 == ${BST_CHECKED}
        StrCpy $installMode 1
        Goto choice_done
    ${EndIf}

    ${NSD_GetState} $radioFresh $0
    ${If} $0 == ${BST_CHECKED}
        StrCpy $installMode 2
        Goto choice_done
    ${EndIf}

    ${NSD_GetState} $radioRemove $0
    ${If} $0 == ${BST_CHECKED}
        ; --- Eliminar: confirmar, ejecutar el desinstalador y salir del asistente.
        StrCpy $previousInstallDir ""
        ReadRegStr $previousInstallDir HKLM "${APP_REGKEY}" "UninstallString"
        ${If} $previousInstallDir == ""
            ReadRegStr $previousInstallDir HKCU "${APP_REGKEY}" "UninstallString"
        ${EndIf}
        ${If} $previousInstallDir == ""
            MessageBox MB_OK|MB_ICONSTOP "No se encontro el desinstalador de la instalacion previa. Elimine NeuroFlex manualmente desde Panel de control."
            Abort
        ${EndIf}
        MessageBox MB_YESNO|MB_ICONQUESTION "Se ejecutara el desinstalador de NeuroFlex:$\r$\n$previousInstallDir$\r$\n$\r$\nDesea continuar?" IDYES do_remove
        Abort
        do_remove:
        ExecWait '"$previousInstallDir" /S _?=$previousInstallDir'
        Quit
    ${EndIf}

    ; Ninguno marcado: avisar y no abandonar la pagina.
    MessageBox MB_OK|MB_ICONEXCLAMATION "Seleccione una opcion: Reparar, Instalar desde cero o Eliminar."
    Abort

    choice_done:
FunctionEnd
Function ConfigPageCreate
    ; En modo Reparar no se pide configuracion: el .env se conserva tal cual.
    ${If} $installMode == 1
        Abort
    ${EndIf}

    !insertmacro MUI_HEADER_TEXT "Configuracion de NeuroFlex" "Ingrese la configuracion proporcionada con el software."

    nsDialogs::Create 1018
    Pop $hConfigPage
    ${If} $hConfigPage == error
        Abort
    ${EndIf}

    ; --- URL de la API ---
    ${NSD_CreateLabel} 0 0 100% 12u "URL de la API de NeuroFlex:"
    Pop $0
    ${NSD_CreateText} 0 15u 100% 13u ""
    Pop $txtApiUrl

    ; --- Cognito Client ID ---
    ${NSD_CreateLabel} 0 35u 100% 12u "ID de cliente de Cognito:"
    Pop $0
    ${NSD_CreateText} 0 50u 100% 13u ""
    Pop $txtClientId

    nsDialogs::Show
FunctionEnd

Function ConfigPageLeave
    ; Leer valores de los campos
    ${NSD_GetText} $txtApiUrl $valApiUrl
    ${NSD_GetText} $txtClientId $valClientId

    ; Validar la configuracion requerida
    ${If} $valApiUrl == ""
        MessageBox MB_OK|MB_ICONEXCLAMATION "Debe ingresar la URL de la API."
        Abort
    ${EndIf}
    ${If} $valClientId == ""
        MessageBox MB_OK|MB_ICONEXCLAMATION "Debe ingresar el ID de cliente de Cognito."
        Abort
    ${EndIf}
FunctionEnd

; ---------------------------------------------------------------------------
; Pagina custom: Token de GitHub
; ---------------------------------------------------------------------------
Function TokenPageCreate
    ; En modo Reparar no se pide token: el .env se conserva tal cual.
    ${If} $installMode == 1
        Abort
    ${EndIf}

    !insertmacro MUI_HEADER_TEXT "Token de GitHub" "Ingrese el token de GitHub para habilitar las actualizaciones automaticas."

    nsDialogs::Create 1018
    Pop $hTokenPage
    ${If} $hTokenPage == error
        Abort
    ${EndIf}

    ${NSD_CreateLabel} 0 0 100% 24u "El token de GitHub permite que NeuroFlex verifique si hay nuevas versiones disponibles y descargue las actualizaciones automaticamente.$\r$\n$\r$\nEste token se le proporciona junto con el software."
    Pop $0

    ; --- GitHub Token ---
    ${NSD_CreateLabel} 0 40u 100% 12u "Token de GitHub:"
    Pop $0
    ${NSD_CreateText} 0 55u 100% 13u ""
    Pop $txtGitHubToken

    nsDialogs::Show
FunctionEnd

Function TokenPageLeave
    ${NSD_GetText} $txtGitHubToken $valGitHubToken

    ${If} $valGitHubToken == ""
        MessageBox MB_OK|MB_ICONEXCLAMATION "Debe ingresar el token de GitHub para las actualizaciones."
        Abort
    ${EndIf}
FunctionEnd

; ---------------------------------------------------------------------------
; Callbacks: colorear el log de instalacion (estilo consola oscura)
; Control 1016 = RichEdit del instfiles
; ---------------------------------------------------------------------------
Function OnInstFilesShow
    GetDlgItem $0 $HWNDPARENT 1016
    SetCtlColors $0 0xF4F7FB 0x102938
FunctionEnd

Function un.OnUnInstFilesShow
    GetDlgItem $0 $HWNDPARENT 1016
    SetCtlColors $0 0xF4F7FB 0x102938
FunctionEnd

; ---------------------------------------------------------------------------
; StrStr - devuelve el resto de la cadena a partir de la primera aparicion de
; la subcadena buscada (o "" si no se encuentra). NSIS puro, sin plugins.
; Uso: Push "texto" ; Push "subcadena" ; Call StrStr ; Pop $resultado
; ---------------------------------------------------------------------------
Function StrStr
    Exch $1
    Exch
    Exch $0
    Exch
    Push $2
    Push $3
    Push $4
    Push $5
    StrLen $2 $1
    StrLen $3 $0
    StrCpy $4 0
    ${DoWhile} $4 <= $3
        StrCpy $5 $0 $2 $4
        ${If} $5 == $1
            StrCpy $0 $0 "" $4
            Goto done
        ${EndIf}
        IntOp $4 $4 + 1
    ${Loop}
    StrCpy $0 ""
    done:
    Pop $5
    Pop $4
    Pop $3
    Pop $2
    Exch $0
    Exch
    Pop $1
FunctionEnd

; ---------------------------------------------------------------------------
; ReadEnvValue - lee el valor de una clave en un archivo .env (lineas
; CLAVE=VALOR). Devuelve "" si la clave no existe o el archivo no se puede
; abrir. NSIS puro, sin plugins.
; Uso: Push "CLAVE" ; Push "ruta\archivo" ; Call ReadEnvValue ; Pop $resultado
; ---------------------------------------------------------------------------
Function ReadEnvValue
    Exch $0
    Exch
    Exch $1
    Push $2
    Push $3
    Push $4
    Push $5
    Push $6

    StrCpy $6 ""
    FileOpen $5 $0 r
    ${If} $5 == ""
        Goto done
    ${EndIf}

    loop:
        FileRead $5 $2
        ${If} $2 == ""
            Goto close
        ${EndIf}
        StrCpy $2 $2 -2          ; quitar \r\n
        ; StrStr consume haystack+needle y deja 1 resultado (neto -1);
        ; guardar $0/$1 y restaurarlos tras la llamada
        Push $0
        Push $1
        Push $2
        Push "="
        Call StrStr
        Pop $3
        Pop $1
        Pop $0
        ${If} $3 != ""
            StrLen $4 $3
            Push $6
            StrLen $6 $2
            IntOp $4 $6 - $4     ; longitud del nombre de clave
            Pop $6
            StrCpy $4 $2 $4      ; nombre de clave
            ${If} $4 == $1
                StrCpy $6 $3 "" 1 ; valor (despues de '=')
                Goto close
            ${EndIf}
        ${EndIf}
        Goto loop

    close:
        FileClose $5
    done:
    StrCpy $0 $6                ; resultado en $0 para el intercambio final
    Pop $6
    Pop $5
    Pop $4
    Pop $3
    Pop $2
    Exch $0
    Exch
    Pop $1
FunctionEnd

; ---------------------------------------------------------------------------
; Datos generales
; ---------------------------------------------------------------------------
Name "${APP_NAME}"
OutFile "NeuroFlex-Setup-${APP_VERSION}.exe"
InstallDir "${INSTALL_DIR}"
RequestExecutionLevel admin
ShowInstDetails show
ShowUninstDetails show

Function .onInit
    StrCpy $hasPreviousInstall 0
    StrCpy $installMode 0
    StrCpy $previousInstallDir ""

    ; --- Deteccion de instalacion previa: registro + datos de usuario ---
    ReadRegStr $previousInstallDir HKLM "${APP_REGKEY}" "InstallLocation"
    ${If} $previousInstallDir == ""
        ReadRegStr $previousInstallDir HKCU "${APP_REGKEY}" "InstallLocation"
    ${EndIf}
    ${If} ${FileExists} "$LOCALAPPDATA\NeuroFlex\data\.env"
        StrCpy $hasPreviousInstall 1
    ${EndIf}
    ${If} $previousInstallDir != ""
        StrCpy $hasPreviousInstall 1
    ${EndIf}

    ; -- Modo silencioso (/S, updater): siempre Reparar, conserva el .env --
    ${If} ${Silent}
    ${AndIf} $hasPreviousInstall == 1
        StrCpy $installMode 1
    ${EndIf}
FunctionEnd

; ===========================================================================
; Seccion: Install
; ===========================================================================
Section "Install"
    ; --- Instalar desde cero: limpiar instalacion y datos previos ---
    ${If} $installMode == 2
        ExecWait "taskkill /F /IM neuroflex.exe"
        Sleep 1000
        RMDir /r "$INSTDIR"
        RMDir /r "$LOCALAPPDATA\NeuroFlex"
    ${EndIf}

    SetOutPath "$INSTDIR"
    File /r "..\dist\neuroflex\*.*"

    FileOpen $0 "$INSTDIR\VERSION" w
    FileWrite $0 "${APP_VERSION}"
    FileClose $0

    ; --- Crear directorios de datos ---
    CreateDirectory "$LOCALAPPDATA\NeuroFlex\data"
    CreateDirectory "$LOCALAPPDATA\NeuroFlex\data\media"
    CreateDirectory "$LOCALAPPDATA\NeuroFlex\data\private_reports"
    CreateDirectory "$LOCALAPPDATA\NeuroFlex\data\clinical_sessions\data\local_sessions"

    ; --- Escribir .env en el directorio de datos ---
    ; Preservar los valores existentes: en modo silencioso (/S) las paginas
    ; custom no se ejecutan y $valClientId/$valApiUrl/$valGitHubToken quedan
    ; vacios, por lo que sobrescribir el .env destruiria las credenciales
    ; guardadas durante una actualizacion.
    StrCpy $oldSecretKey ""
    StrCpy $oldClientId ""
    StrCpy $oldApiUrl ""
    StrCpy $oldGitHubToken ""
    StrCpy $oldWazuhAuditLogPath ""
    StrCpy $oldWazuhAuditHashKey ""

    ${If} ${FileExists} "$LOCALAPPDATA\NeuroFlex\data\.env"
        Push "DJANGO_SECRET_KEY"
        Push "$LOCALAPPDATA\NeuroFlex\data\.env"
        Call ReadEnvValue
        Pop $oldSecretKey

        Push "COGNITO_CLIENT_ID"
        Push "$LOCALAPPDATA\NeuroFlex\data\.env"
        Call ReadEnvValue
        Pop $oldClientId

        Push "NEUROFLEX_API_BASE_URL"
        Push "$LOCALAPPDATA\NeuroFlex\data\.env"
        Call ReadEnvValue
        Pop $oldApiUrl

        Push "GITHUB_TOKEN"
        Push "$LOCALAPPDATA\NeuroFlex\data\.env"
        Call ReadEnvValue
        Pop $oldGitHubToken

        Push "WAZUH_AUDIT_LOG_PATH"
        Push "$LOCALAPPDATA\NeuroFlex\data\.env"
        Call ReadEnvValue
        Pop $oldWazuhAuditLogPath

        Push "WAZUH_AUDIT_HASH_KEY"
        Push "$LOCALAPPDATA\NeuroFlex\data\.env"
        Call ReadEnvValue
        Pop $oldWazuhAuditHashKey
    ${EndIf}

    ; DJANGO_SECRET_KEY: no hay campo en las paginas; preservar o usar default
    ${If} $oldSecretKey != ""
        StrCpy $finalSecretKey $oldSecretKey
    ${Else}
        StrCpy $finalSecretKey "change-me"
    ${EndIf}

    ; COGNITO_CLIENT_ID: valor de la pagina > valor previo > vacio
    ${If} $valClientId != ""
        StrCpy $finalClientId $valClientId
    ${ElseIf} $oldClientId != ""
        StrCpy $finalClientId $oldClientId
    ${Else}
        StrCpy $finalClientId ""
    ${EndIf}

    ; NEUROFLEX_API_BASE_URL: valor de la pagina > valor previo > vacio
    ${If} $valApiUrl != ""
        StrCpy $finalApiUrl $valApiUrl
    ${ElseIf} $oldApiUrl != ""
        StrCpy $finalApiUrl $oldApiUrl
    ${Else}
        StrCpy $finalApiUrl ""
    ${EndIf}

    ; GITHUB_TOKEN: valor de la pagina > valor previo > vacio
    ${If} $valGitHubToken != ""
        StrCpy $finalGitHubToken $valGitHubToken
    ${ElseIf} $oldGitHubToken != ""
        StrCpy $finalGitHubToken $oldGitHubToken
    ${Else}
        StrCpy $finalGitHubToken ""
    ${EndIf}

    FileOpen $0 "$LOCALAPPDATA\NeuroFlex\data\.env" w
    FileWrite $0 "DJANGO_SECRET_KEY=$finalSecretKey$\r$\n"
    FileWrite $0 "DJANGO_DEBUG=False$\r$\n"
    FileWrite $0 "SESSION_DATA_SOURCE=local$\r$\n"
    FileWrite $0 "SESSION_LOCAL_DATA_PATH=$LOCALAPPDATA\NeuroFlex\data\clinical_sessions\data\local_sessions$\r$\n"
    FileWrite $0 "COGNITIVE_MODEL_MODE=legacy_provisional$\r$\n"
    FileWrite $0 "COGNITO_REGION=us-east-1$\r$\n"
    FileWrite $0 "COGNITO_CLIENT_ID=$finalClientId$\r$\n"
    FileWrite $0 "NEUROFLEX_API_BASE_URL=$finalApiUrl$\r$\n"
    FileWrite $0 "GITHUB_TOKEN=$finalGitHubToken$\r$\n"
    FileWrite $0 "WAZUH_AUDIT_LOG_PATH=$oldWazuhAuditLogPath$\r$\n"
    FileWrite $0 "WAZUH_AUDIT_HASH_KEY=$oldWazuhAuditHashKey$\r$\n"
    FileClose $0

    ; --- Atajos ---
    CreateDirectory "$SMPROGRAMS\NeuroFlex"
    CreateShortCut "$SMPROGRAMS\NeuroFlex\NeuroFlex.lnk" "$INSTDIR\neuroflex.exe"
    CreateShortCut "$DESKTOP\NeuroFlex.lnk" "$INSTDIR\neuroflex.exe"

    ; --- Registro de desinstalacion (habilita la deteccion de instalaciones
    ; previas y la entradas en "Aplicaciones instaladas" de Windows) ---
    WriteRegStr HKLM "${APP_REGKEY}" "DisplayName" "NeuroFlex Dashboard"
    WriteRegStr HKLM "${APP_REGKEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "${APP_REGKEY}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKLM "${APP_REGKEY}" "DisplayIcon" "$INSTDIR\neuroflex.exe"
    WriteRegStr HKLM "${APP_REGKEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKLM "${APP_REGKEY}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegDWORD HKLM "${APP_REGKEY}" "NoModify" 1
    WriteRegDWORD HKLM "${APP_REGKEY}" "NoRepair" 1

    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; ===========================================================================
; Seccion: Uninstall
; ===========================================================================
Section "Uninstall"
    ; --- Cerrar NeuroFlex si esta en ejecucion ---
    ExecWait "taskkill /F /IM neuroflex.exe"
    Sleep 1000

    Delete "$INSTDIR\neuroflex.exe"
    Delete "$INSTDIR\VERSION"
    Delete "$INSTDIR\uninstall.exe"
    RMDir /r "$INSTDIR\_internal"
    RMDir "$INSTDIR"

    Delete "$SMPROGRAMS\NeuroFlex\NeuroFlex.lnk"
    RMDir "$SMPROGRAMS\NeuroFlex"
    Delete "$DESKTOP\NeuroFlex.lnk"

    DeleteRegKey HKLM "${APP_REGKEY}"

    MessageBox MB_YESNO "¿Deseas conservar los datos de usuario (base de datos, sesiones, informes)?" IDNO skip_data
    Goto done
    skip_data:
    RMDir /r "$LOCALAPPDATA\NeuroFlex"
    done:
SectionEnd
