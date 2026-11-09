@echo off
chcp 65001 >nul
title Subir Proyecto a GitHub (denzeracitvarbotsnewxd33)
color 0A

cd /d "%~dp0"
echo ===================================================================
echo        SUBIENDO PROYECTO A GITHUB (MODO SEGURO - SIN TOKEN)
echo        Repo: https://github.com/purorodriguez903-oss/denzeracitvarbotsnewxd33.git
echo ===================================================================
echo.
git add .
git commit -m "Actualizacion completa de DenzerBot para Railway"
echo Enviando cambios a GitHub...
git push -u origin main
echo.
if %errorlevel% equ 0 (
    echo ===================================================================
    echo  [EXITO] ¡Proyecto subido correctamente a GitHub!
    echo  Railway detectará los cambios y desplegará el bot automáticamente.
    echo ===================================================================
) else (
    echo ===================================================================
    echo  Si se abre una ventana del navegador, inicia sesion con tu cuenta
    echo  de GitHub para autorizar la subida.
    echo ===================================================================
)
echo.
pause
