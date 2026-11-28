@echo off

::
:: Extracts archive using Windows Tar.
::
:: %~1 - NAME - User-friendly name shown in logging.
:: %~2 - FLAG - Absolute Path to a file or directory within %~4.
::              If it already exists on disk, skip extraction.
:: %~3 - SRC  - Absolute archive path - MUST exist.
:: %~4 - DST  - Extraction directory path - MUST exist.
::
:: Windows tar directly supports .tar.gz and .zip.
:: Archive content is extracted directly into %~4.
::
:: %~2 FLAG is assumed to not include version suffix even if archive content
:: naming convention uses one. For example, for zlib.tar.gz verion 1.4 expect
::     - "zlib-1.4" - top-level container;
::     - "zlib-1.4/win32/Makefile.msc" - probe inside archive;
::     - "zlib/win32/Makefile.msc" - %~2 FLAG, probe on disk - version suffix
::        is stripped after extraction.
::   
:: The script tests for possible presense of version suffix in top-level path
:: element of archive member corresponding to the on-disk %~2 FLAG {extensions
:: are not supported} and derives archive PROBE, e.g.:
::     - "zlib.EXT/win32/Makefile.msc" would yield "zlib*.EXT/win32/Makefile.msc".
::
:: Archive must pass the test with the derived PROBE or fail otherwise.
:: When top-level path element in archive includes version suffix, rename
:: it automaticaly to match the FLAG.
::
:: Use XSTARTED="%~4/%~nx3.part" flag to ensure atomic extraction.

:: ============================================================================ MAIN BEGIN
:: ============================================================================
:MAIN

setlocal EnableExtensions EnableDelayedExpansion

set "EXIT_STATUS=0"

call :COLOR_SCHEME

echo:
echo --------------------------------------------------------------------------------
echo %WARN% Processing %NAME% archive.
echo:

call :PARSE_ARGS %* || (
    set "EXIT_STATUS=1"
    goto :EXTRACT_EXIT
)

if exist "%DST%/%FLAG%" if not exist "%XSTARTED%" (
    set "EXIT_STATUS=0"
    echo %INFO% OK - PRESENT - "%DST%/%FLAG%".
    echo %INFO% OK - ABSENT  - "%XSTARTED%".
    echo %OKOK% ===== Using previously extracted %NAME% =====
    goto :EXTRACT_EXIT
)

if not defined TAR set "TAR=%SystemRoot%\System32\tar.exe"
if not exist "%TAR%" (
    set "EXIT_STATUS=1"
    echo %ERROR% Tar not found: %TAR%.
    goto :EXTRACT_EXIT
)

echo %INFO% ===== Check %NAME% archive for presence of the probe =====
echo:

:: Check for and set on disk interruption flag.

if exist "%XSTARTED%" (
    echo %WARN% Found "%XSTARTED%" flag. Prior extraction was interrupted. Overwriting.
) else (
    echo: >"%XSTARTED%"
)

:: Test archive for presence of probe.

call :ARCHIVE_PROBE || (
    set "EXIT_STATUS=%ERRORLEVEL%"
    goto :EXTRACT_EXIT
)

echo %INFO% ===== Extract %NAME% archive =====
echo:

"%TAR%" -x -f "%SRC%" -C "%DST%"
set "EXIT_STATUS=%ERRORLEVEL%"
if "%EXIT_STATUS%"=="0" (
    echo %INFO% Extracted %NAME%.
) else (
    echo %ERROR% Failed to extract %NAME%. Error Code: %EXIT_STATUS%.
)

:: Check file flag in extracted archive on disk.

if not exist "%DST%/%ARCH_FLAG%" (
    set "_EXIT_STATUS=1"
    echo %ERROR% Extraction failed. "%DST%/%ARCH_FLAG%" not found.
    goto :EXTRACT_EXIT
)

:: Rename temporary FSO.

if /i not "%ARCH_LEAD%"=="%FLAG_LEAD%" (
    move "%DST%/%ARCH_LEAD%" "%DST%/%FLAG_LEAD%"
    set "EXIT_STATUS=!ERRORLEVEL!"
    if not "!EXIT_STATUS!"=="0" (
        echo %ERROR% Failed to rename "%DST%/%ARCH_LEAD%" to "%DST%/%FLAG_LEAD%".
        goto :EXTRACT_EXIT
    )
)

:: Check file flag in extracted archive on disk after rename.

if not exist "%DST%/%FLAG%" (
    set "_EXIT_STATUS=1"
    echo %ERROR% Extraction failed. "%DST%/%FLAG%" not found.
    goto :EXTRACT_EXIT
)

:: Delete XSTARTED

del /q "%XSTARTED:/=\%" || (
    set "_EXIT_STATUS=1"
    echo %ERROR% Extraction failed. Failed to delete flag "%XSTARTED%".
    goto :EXTRACT_EXIT
)

if exist "%XSTARTED%" (
    set "_EXIT_STATUS=1"
    echo %ERROR% Extraction failed. Failed to delete flag "%XSTARTED%".
    goto :EXTRACT_EXIT
)

:EXTRACT_EXIT

echo:
echo %WARN% Completed %NAME% archive extraction.
echo --------------------------------------------------------------------------------
echo:

if not defined EXIT_STATUS (set "EXIT_STATUS=0")
endlocal & exit /b %EXIT_STATUS%
:: ============================================================================
:: ============================================================================ MAIN END


:: ############################################################################
:: ############################################################################
:: ############################################################################


:: ============================================================================ PARSE_ARGS BEGIN
:: ============================================================================
:PARSE_ARGS

set "_EXIT_STATUS=0"

set "NAME=%~1"
set "SRC=%~3"
set "SRC=%SRC:\=/%"
set "DST=%~4"
set "DST=%DST:\=/%"
set "FLAG=%~2"
set "FLAG=%FLAG:\=/%"
set "FLAG=!FLAG:%DST%/=!"
set "XSTARTED=%DST%/%~nx3.part"

echo %INFO% ----------------------------------------------------------------------
echo %INFO% CLI arguments:
echo %INFO%
echo %INFO% %*
echo %INFO% ----------------------------------------------------------------------

if "%~4"=="" (
    set "_EXIT_STATUS=1"
    echo %ERROR% Missing required parameters.
    echo %INFO%  USAGE: call extract_archive.bat "NAME" "FLAG" "SRC" "DST"
    goto :PARSE_ARGS_EXIT
)

if not exist "%SRC%" (
    set "_EXIT_STATUS=1"
    echo %ERROR% Archive "%SRC%" not found.
    goto :PARSE_ARGS_EXIT
)

if exist "%SRC%/" (
    set "_EXIT_STATUS=1"
    echo %ERROR% Expected an archive file, not a directory: "%SRC%".
    goto :PARSE_ARGS_EXIT
)

if not exist "%DST%\." (
    set "_EXIT_STATUS=1"
    echo %ERROR% Output directory "%DST%" not found.
    goto :PARSE_ARGS_EXIT
)

set "VARS_TITLE=Main VARS:"
call :CHECK_VARS "NAME" "FLAG" "SRC" "DST" "XSTARTED"
set "VARS_TITLE="

:PARSE_ARGS_EXIT

if not defined _EXIT_STATUS (set "_EXIT_STATUS=0")
exit /b %_EXIT_STATUS%
:: ============================================================================
:: ============================================================================ PARSE_ARGS END


:: ============================================================================ ARCHIVE_PROBE BEGIN
:: ============================================================================
:ARCHIVE_PROBE

set "_EXIT_STATUS=0"

::                                           LEAD + TAIL
:: Split path like zlib/win32/Makefile.msc = zlib + win32/Makefile.msc

set "FLAG_LEAD="
set "FLAG_TAIL="
for /f "usebackq tokens=1,* delims=/" %%P in ('%FLAG%') do (
    set "FLAG_LEAD=%%~P"
    set "FLAG_TAIL=%%~Q"
)

set "PROBE=%FLAG_LEAD%*"
if defined FLAG_TAIL (set "PROBE=%PROBE%/%FLAG_TAIL%")

:: Probe archive for presence of the flag member.

set "ARCH_LEAD="
set "ARCH_TAIL="

:: Probe is pattern like zlib*/win32/Makefile.msc
::                                                       LEAD     + TAIL
:: Split archive path like zlib-1.4/win32/Makefile.msc = zlib-1.4 + win32/Makefile.msc

"%TAR%" -tf "%SRC%" "%PROBE%" 1>"%XSTARTED%" 2>nul && (
    for /f "usebackq tokens=1,* delims=/" %%L in ("%XSTARTED%") do (
        set "ARCH_LEAD=%%~L"
        set "ARCH_TAIL=%%~M"
    )
)

if defined ARCH_LEAD (
    set "_EXIT_STATUS=0"
    if defined ARCH_TAIL (
        set "ARCH_FLAG=%ARCH_LEAD%/%ARCH_TAIL%"
    ) else (
        set "ARCH_FLAG=%ARCH_LEAD%"
    )
    echo %INFO% "!ARCH_FLAG!" found inside "%SRC%".
) else (
    set "_EXIT_STATUS=1"
    echo %ERROR% "%PROBE%" not found inside "%SRC%".
)

:: set "VARS_TITLE=Archive probe components"
:: call :CHECK_VARS "PROBE" "FLAG_LEAD" "FLAG_TAIL" "ARCH_LEAD" "ARCH_TAIL"
:: echo:
:: set "VARS_TITLE="

if not defined _EXIT_STATUS (set "_EXIT_STATUS=0")
exit /b %_EXIT_STATUS%
:: ============================================================================
:: ============================================================================ ARCHIVE_PROBE END


:: ============================================================================ CHECK_VARS BEGIN
:: ============================================================================
:CHECK_VARS
:: 
:: Accepts variable number of variable name candidates. For each name reports,
:: if the corresponding variable is undefined or its value, if defined.
:: Set VARS_TITLE before calling to replace default title.

setlocal

set "PAD10=          "
set "WIDTH=25"
if not defined VARS_TITLE (set "VARS_TITLE=Checking environment variables:")

echo:
echo ----------------------------------------------------------------------
echo %WARN% %VARS_TITLE%
echo %INFO%

:NEXT_VAR

if "%~1"=="" goto :CHECK_VARS_EXIT

set "VAR_LABEL=%~1=%PAD10%%PAD10%%PAD10%%PAD10%"
set "VAR_LABEL=!VAR_LABEL:~0,%WIDTH%!"

if defined %~1 (
    echo %INFO% %VAR_LABEL% `!%~1!`
) else (
    echo %WARN% %VAR_LABEL% not defined.
)
shift & goto :NEXT_VAR

:CHECK_VARS_EXIT

echo ----------------------------------------------------------------------
echo:

endlocal & exit /b 0
:: ============================================================================
:: ============================================================================ CHECK_VARS END


:: ============================================================================ COLOR_SCHEME BEGIN
:: ============================================================================
:COLOR_SCHEME
:: ---------------------------------------------------------------------
:: Color Scheme (with NOCOLOR fallback)
:: ---------------------------------------------------------------------

if defined _ARG_NOCOLOR set "NOCOLOR=1"
if defined NO_COLOR set "NOCOLOR=1"
if defined NOCOLOR (
    set  "INFO= [INFO]  "
    set  "OKOK= [-OK-]  "
    set  "WARN= [WARN]  "
    set "ERROR= [ERROR] "
) else (
    set  "INFO=[100;92m [INFO]  [0m"
    set  "OKOK=[103;94m [-OK-]  [0m"
    set  "WARN=[106;35m [WARN]  [0m"
    set "ERROR=[105;34m [ERROR] [0m"
)

exit /b 0
:: ============================================================================
:: ============================================================================ COLOR_SCHEME END
