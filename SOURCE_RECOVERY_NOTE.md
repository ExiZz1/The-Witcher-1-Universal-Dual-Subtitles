# Source recovery note

The v10 Nexus package preserved `witcher1_dual.py` as readable Python source, but the Tkinter GUI entrypoint was embedded inside the shipped PyInstaller executable rather than stored as a separate `.py` file.

For transparency, this repository contains:

- `witcher1_dual.py` — the original readable engine source shipped with v10.
- `Witcher1_Dual_Subtitles_GUI_v10_embedded.marshal` — the exact embedded GUI code object extracted from the final v10 executable.
- `Witcher1_Dual_Subtitles_GUI_recovered.py` — a readable source reconstruction of the GUI based on the exact v10 embedded bytecode and its observed interface/behavior.

The recovered GUI source is not claimed to preserve the original author's formatting or comments. The embedded marshal file is included so the reviewer can compare the recovered source with the exact code object shipped in the final executable.

The final v10 executable was built with Python 3.13 / PyInstaller and invokes the bundled `witcher1_dual.py` engine.
