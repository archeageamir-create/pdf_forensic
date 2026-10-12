set CXXFLAGS=
set CFLAGS=

mkdir build
cd build

:: Configure.
cmake %CMAKE_ARGS% -G"Ninja" ^
      -DCMAKE_INSTALL_PREFIX:PATH="%LIBRARY_PREFIX:/=\\%" ^
      -DCMAKE_BUILD_TYPE=Release ^
      -DCMAKE_PREFIX_PATH="%LIBRARY_PREFIX%:/=\\" ^
      -DCMAKE_SYSTEM_PREFIX_PATH="%LIBRARY_PREFIX:/=\\%" ^
      -DBUILD_SHARED_LIBS:BOOL=true ^
      -DFT_DISABLE_BZIP2=TRUE ^
      -DFT_DISABLE_HARFBUZZ=TRUE ^
      -DFT_DISABLE_ZLIB=FALSE ^
      -DFT_DISABLE_PNG=FALSE ^
      -DFT_DISABLE_BROTLI=TRUE ^
      "%SRC_DIR:/=\\%"
if errorlevel 1 exit 1

:: Build.
cmake --build . --config Release
if errorlevel 1 exit 1

:: Test.
if not "%CONDA_BUILD_SKIP_TESTS%"=="1" (
  ctest -C Release
)
if errorlevel 1 exit 1

:: Install.
cmake --install .
if errorlevel 1 exit 1

:: Move everything 1-level down.
move %LIBRARY_INC%\freetype2\freetype %LIBRARY_INC% || exit 1
move %LIBRARY_INC%\freetype2\ft2build.h %LIBRARY_INC% || exit 1

:: vs2008 created libfreetype.dll instead of freetype.dll
set LIB="%LIBRARY_BIN%\libfreetype.dll"
if exist %LIB% (copy %LIB% %LIBRARY_BIN%\freetype.dll) || exit 1
