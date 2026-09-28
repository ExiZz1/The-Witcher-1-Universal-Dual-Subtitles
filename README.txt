THE WITCHER 1 — DUAL SUBTITLES TOOL v10 UNIVERSAL FINAL
Author: ExiZZ • Nexus Mods

Universal dual subtitles for The Witcher: Enhanced Edition.

WHAT IT DOES
• Keeps the selected Primary language first.
• Adds the selected Secondary language underneath.
• Automatically detects the installed Witcher 1 language files at startup.
• Processes the complete DLG + QST set.
• Optional English Menu + Settings + Journal UI.
• Supports PATCH SAVE and PATCH ALL SAVES.
• Creates backups and can restore the original files.

HOW TO USE
1. Close The Witcher 1.
2. Run START_HERE.bat.
3. Select the game folder if needed.
4. Choose Primary and Secondary languages.
5. Click SAFE TEST.
6. If SAFE TEST succeeds, click INSTALL LAST TEST.
7. Start the game and test the subtitles.

IMPORTANT — LANGUAGE ORDER
The Primary language controls the active font context. If the Secondary language appears as
symbols, boxes, punctuation or otherwise unreadable characters, swap Primary and Secondary and
run SAFE TEST → INSTALL LAST TEST again.

Example: Polish → Russian may display Cyrillic incorrectly, while Russian → Polish can render both.

SAVE PATCH
Close the game before patching saves. PATCH SAVE patches one save; PATCH ALL SAVES patches every
save in the selected save folder. A .dual_backup is created before replacement.

WHY ARE SOME MENU / SETTINGS ENTRIES STILL IN ENGLISH?
The Witcher 1 does not contain a complete localized version of every UI element for every language.
Some entries use the game's original English fallback. This tool does not machine-translate UI text;
it uses the game's existing localization resources. Therefore, missing localized UI entries may remain
in English. If ENGLISH MENU + SETTINGS + JOURNAL UI is enabled, English UI text is intentional.

For detailed troubleshooting, language notes and technical information, see GUIDE.txt.


PYTHON-FREE RELEASE
The final Nexus release is designed to ship with Witcher1_Dual_Subtitles.exe. End users do not need Python. The executable contains the Python runtime; no separate Python installation is required. A bundled engine module (witcher1_dual.py) is included because INSTALL uses it directly for the final backup/copy step.
