@echo off
title LoRA Gallery V5
pushd "%~dp0"

echo ============================================================
echo  LoRA Gallery V5
echo ============================================================
echo.
echo  [1]  Smart rebuild  --  Rescan LoRA folders, reuse cached PNG prompts
echo         Use this for: added/removed LoRAs, normal day-to-day refresh
echo         Speed: fast (seconds)
echo.
echo  [2]  Skip-prompts rebuild  --  Rescan folders, skip ALL PNG prompt reading
echo         Use this for: fastest possible rebuild, you don't need image prompts
echo         Speed: fastest (no PNG reading at all)
echo.
echo  [3]  Full rebuild  --  Rescan everything + re-read ALL PNG prompts fresh
echo         Use this for: first run, or image prompt data looks wrong/stale
echo         Speed: slow (minutes, reads every sample image)
echo.
echo  [4]  Clear cache + rebuild  --  Delete cached prompt data, then Smart rebuild
echo         Use this after: updating the gallery script, or if lightbox prompts
echo         look wrong / missing for newly added images
echo         Speed: moderate (re-reads PNG metadata fresh during scan)
echo.
echo  [5]  Open gallery  --  Open existing lora_gallery.html instantly, no scan
echo         Use this for: gallery is already up-to-date, just want to browse
echo         Speed: instant (no Python, no scanning)
echo.
echo  [6]  Update CivitAI metadata  --  Re-fetch stats/triggers/tags from civitai.red
echo         then Smart rebuild with the fresh data
echo         Use this for: likes/download counts are stale, triggers changed on CivitAI
echo         Speed: slow (network requests for each LoRA that has a .info file)
echo.
echo  [7]  Fetch CivitAI sample images  --  Download top 5 most-reacted images per LoRA
echo         Saves images + prompt metadata (visible in gallery lightbox)
echo         You choose which subfolder to target (Pony, Anima, etc.)
echo         Note: skips images already downloaded; NSFW included
echo         Speed: slow (downloads images for each LoRA with a .info file)
echo.
echo  [8]  Run deletions  --  Execute run_deletions.py to move marked items to _DELETED/
echo         Items marked in the gallery (images + folders) are moved, not permanently deleted
echo         HOW TO GET run_deletions.py: open gallery, click "Deletions (N)" button,
echo         save the file to THIS folder, then choose this option
echo.
set "choice="
set /p choice= Choose 1-8 then press Enter (default=1):

echo.

if "%choice%"=="5" (
    echo Opening existing gallery...
    if not exist "lora_gallery.html" (
        echo  ERROR: lora_gallery.html not found. Run option 1, 2, 3, or 4 first to build it.
        pause
        popd
        exit /b 1
    )
    start "" "lora_gallery.html"
    popd
    exit /b 0
)

if "%choice%"=="2" (
    echo [2] Skip-prompts rebuild -- rescanning folders, skipping PNG prompts...
    python LocalLoraGalleryV5.py --skip-meta
) else if "%choice%"=="3" (
    echo [3] Full rebuild -- rescanning all folders + re-reading ALL PNG prompts...
    python LocalLoraGalleryV5.py --clear-cache
) else if "%choice%"=="4" (
    echo [4] Clearing metadata cache, then rebuilding...
    if exist ".lora_gallery_meta_cache.json" del ".lora_gallery_meta_cache.json"
    python LocalLoraGalleryV5.py
) else if "%choice%"=="6" (
    echo [6] Fetching updated metadata from CivitAI, then rebuilding...
    echo     This may take several minutes depending on your collection size.
    python LocalLoraGalleryV5.py --update-civitai
) else if "%choice%"=="7" (
    echo [7] Fetching top CivitAI sample images, then rebuilding...
    echo     You will be asked which folder to target.
    python LocalLoraGalleryV5.py --fetch-images 5
) else if "%choice%"=="8" (
    if not exist "run_deletions.py" (
        echo.
        echo  run_deletions.py not found in this folder.
        echo.
        echo  To get it:
        echo    1. Open the gallery  (option 5^)
        echo    2. Click the "Deletions (N^)" button in the toolbar
        echo    3. Save the downloaded file to this folder:
        echo       %~dp0
        echo    4. Run this option again
        echo.
        popd
        pause
        exit /b 0
    )
    echo [8] Running deletions -- moving marked items to _DELETED/ ...
    python run_deletions.py
    if errorlevel 1 py run_deletions.py
    echo.
    echo  Done. Files moved to _DELETED\ (reversible^).
    echo  Run a rebuild (option 1^) to update the gallery.
    echo.
    popd
    pause
    exit /b 0
) else (
    echo [1] Smart rebuild -- rescanning folders with cached PNG prompts...
    python LocalLoraGalleryV5.py
)

if errorlevel 1 (
    echo.
    echo  Trying "py" launcher instead of "python"...
    if "%choice%"=="2" (
        py LocalLoraGalleryV5.py --skip-meta
    ) else if "%choice%"=="3" (
        py LocalLoraGalleryV5.py --clear-cache
    ) else if "%choice%"=="4" (
        if exist ".lora_gallery_meta_cache.json" del ".lora_gallery_meta_cache.json"
        py LocalLoraGalleryV5.py
    ) else if "%choice%"=="6" (
        py LocalLoraGalleryV5.py --update-civitai
    ) else if "%choice%"=="7" (
        py LocalLoraGalleryV5.py --fetch-images 5
    ) else if "%choice%"=="8" (
        py run_deletions.py
    ) else (
        py LocalLoraGalleryV5.py
    )
)

if errorlevel 1 (
    echo.
    echo  ERROR: Could not run Python.
    echo  Make sure Python 3.8+ is installed and in your PATH.
    echo  You can also run:  python LocalLoraGalleryV5.py
    echo.
    popd
    pause
    exit /b 1
)

echo.
set "openyn="
set /p openyn= Open gallery in browser? (Y/N, default=Y):
if /i not "%openyn%"=="n" (
    start "" "lora_gallery.html"
)

popd
pause
