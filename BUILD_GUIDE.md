# Witcher 1 — Universal Dual Subtitles v10
## Build instructions

### Requirements
- Windows 10/11
- Python 3.13 (64-bit)
- PyInstaller
- The project files from this repository

### 1. Install PyInstaller

```powershell
py -3.13 -m pip install pyinstaller
```

### 2. Build the standalone executable

Run from the repository directory:

```powershell
py -3.13 -m PyInstaller --noconfirm --clean --onefile --windowed --name "Witcher1_Dual_Subtitles" --add-data "witcher1_dual.py;." Witcher1_Dual_Subtitles_GUI_recovered.py
```

The executable will be created in `dist/Witcher1_Dual_Subtitles.exe`.

### 3. Test

Place `witcher1_dual.py` beside the executable when running the reconstructed source build, or adapt the packaging mode so the engine is available beside the executable. Test SAFE TEST, INSTALL, RESTORE, PATCH SAVE and PATCH ALL SAVES with a backup of the game and saves.

### Notes

The public v10 release contains an executable whose GUI entrypoint was embedded by PyInstaller. The exact embedded GUI code object is included in `Witcher1_Dual_Subtitles_GUI_v10_embedded.marshal` for security review. `witcher1_dual.py` is the original readable engine source shipped with the release.
