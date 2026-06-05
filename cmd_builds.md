# Primera vez (crea venv + compila todo)
.\build_nuitka.ps1

# Reutilizar el venv (más rápido en rebuilds)
.\build_nuitka.ps1 -SkipVenv

# Solo regenerar el instalador directo (sin recompilar Nuitka)
.\build_nuitka.ps1 -SkipVenv -SkipBuild

# Solo el instalador, usando la distribución existente en dist\PDFlex
.\build_setup.ps1

# Artefacto final para publicar / auto-updater
dist\PDFlex_<version>_Setup.exe
