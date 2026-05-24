@echo off
REM Batch script to fetch traffic documents from OnBase using curl
REM Usage: fetch_documents.bat <document_id>
REM        fetch_documents.bat --batch (reads from document_ids.txt)

setlocal enabledelayedexpansion

set ONBASE_API=https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/Document
set OUTPUT_DIR=traffic_data
set DOC_ID=%1

if not exist %OUTPUT_DIR% (
    mkdir %OUTPUT_DIR%
)

if "%DOC_ID%"=="--batch" (
    echo Batch processing documents from document_ids.txt...
    if not exist document_ids.txt (
        echo Error: document_ids.txt not found
        exit /b 1
    )
    
    setlocal enabledelayedexpansion
    set counter=0
    for /f "tokens=*" %%A in (document_ids.txt) do (
        set /a counter+=1
        set doc_id=%%A
        echo.
        echo [!counter!] Fetching document...
        call :fetch_document !doc_id! !counter!
        timeout /t 1 /nobreak
    )
    endlocal
) else if "%DOC_ID%"=="" (
    echo Usage: fetch_documents.bat ^<document_id^>
    echo        fetch_documents.bat --batch
    echo.
    echo Example:
    echo   fetch_documents.bat "AdzJUwDCr1WBUTV48f^%^C3^%^81mNHVPlw..."
    exit /b 1
) else (
    call :fetch_document %DOC_ID% 1
)

exit /b 0

:fetch_document
setlocal
set doc_id=%~1
set counter=%~2
set filename=%OUTPUT_DIR%\document_%counter%.pdf

echo Fetching: %doc_id%
echo Output: %filename%

curl.exe "%ONBASE_API%/%doc_id%/" ^
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0" ^
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" ^
  -H "Accept-Language: en-US,en;q=0.9" ^
  -H "Accept-Encoding: gzip, deflate, br, zstd" ^
  -H "Sec-Fetch-Storage-Access: none" ^
  -H "Connection: keep-alive" ^
  -H "Referer: https://onbasepublic.glastonbury-ct.gov/PavClient/PublicRecordTrafficCount/index.html?OBKey__102_1=MAIN^%^20ST" ^
  -H "Upgrade-Insecure-Requests: 1" ^
  -H "Sec-Fetch-Dest: iframe" ^
  -H "Sec-Fetch-Mode: navigate" ^
  -H "Sec-Fetch-Site: same-origin" ^
  -H "Sec-Fetch-User: ?1" ^
  -H "Priority: u=4" ^
  -H "TE: trailers" ^
  -o "%filename%" ^
  -w "HTTP Status: %%{http_code} | Size: %%{size_download} bytes\n"

if %errorlevel% equ 0 (
    echo. Done!
) else (
    echo. Failed with error code %errorlevel%
)

endlocal
exit /b 0
