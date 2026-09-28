import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP = "The Witcher 1 — Dual Subtitles Tool v10 Universal Final"
DEFAULT_GAME = r"D:\Steam\steamapps\common\The Witcher Enhanced Edition"

LANG_NAMES = {
    3: "English", 5: "Polski", 10: "Deutsch", 11: "Français", 12: "Español",
    13: "Italiano", 14: "Русский", 15: "Čeština", 16: "Magyar",
    20: "한국어", 21: "中文（繁體）", 22: "中文（简体）",
}

class App:
    def __init__(self, root):
        self.root = root
        root.title(APP)
        root.geometry("1120x800")
        root.resizable(False, False)
        self.proc = None
        self.busy = False
        self.last_candidate = None
        self.last_manifest = None
        self.last_tlk_candidate = None
        self.last_report = None
        self.languages = []
        self.lang_by_id = {}
        self.base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        self.engine = self.base / "witcher1_dual.py"
        self.state_file = self.base / "LAST_SAFE_TEST.txt"
        self.log_file = self.base / "Witcher1_Dual_Subtitles.log"

        self.primary = tk.StringVar()
        self.secondary = tk.StringVar()
        self.lang_info = tk.StringVar()
        self.english_menu = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready.")

        self._build_ui()
        self._load_state()
        self.update_buttons()
        self.root.after(100, self.refresh_languages)

    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=14); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Witcher 1 Enhanced Edition folder:").grid(row=0,column=0,sticky="w")
        self.path = ttk.Entry(frm, width=88); self.path.grid(row=1,column=0,columnspan=4,sticky="we",pady=(4,8))
        self.path.insert(0, DEFAULT_GAME)
        ttk.Button(frm, text="Browse…", command=self.browse).grid(row=1,column=4,padx=(8,0))
        ttk.Label(frm,text="Primary language:").grid(row=2,column=0,sticky="w",padx=8)
        self.primary_box=ttk.Combobox(frm,textvariable=self.primary,state="readonly",width=20)
        self.primary_box.grid(row=3,column=0,sticky="w",padx=8); self.primary_box.bind("<<ComboboxSelected>>",lambda e:self.update_language_info())
        ttk.Label(frm,text="Secondary language:").grid(row=2,column=1,sticky="w",padx=8)
        self.secondary_box=ttk.Combobox(frm,textvariable=self.secondary,state="readonly",width=20)
        self.secondary_box.grid(row=3,column=1,sticky="w",padx=8); self.secondary_box.bind("<<ComboboxSelected>>",lambda e:self.update_language_info())
        ttk.Label(frm,textvariable=self.lang_info).grid(row=3,column=2,columnspan=3,sticky="w",padx=8)
        ttk.Label(frm,text="SAFE TEST processes the complete game: DLG + QST.",foreground="darkgreen").grid(row=4,column=0,columnspan=5,sticky="w",pady=(5,2))
        ttk.Label(frm,text="If a language is missing or displays symbols, swap Primary and Secondary. The active Primary language controls the font context.",wraplength=980).grid(row=5,column=0,columnspan=5,sticky="w",pady=(0,6))
        ttk.Checkbutton(frm,text="ENGLISH MENU + SETTINGS + JOURNAL UI",variable=self.english_menu).grid(row=6,column=0,columnspan=3,sticky="w")
        ttk.Label(frm,text="SAFE TEST never changes the game. INSTALL applies the tested DLG + QST + optional English UI. SAVE PATCH uses the same Primary + Secondary pair and creates a .dual_backup first.",wraplength=980).grid(row=7,column=0,columnspan=5,sticky="w",pady=(2,8))
        buttons=[("SAFE TEST",self.safe_test),("INSTALL LAST TEST",self.install_last),("RESTORE ORIGINAL",self.restore),("CLEAR LOG",self.clear_log),("SHOW LAST CHANGES",self.show_report),("PATCH SAVE",self.patch_save),("PATCH ALL SAVES",self.patch_all_saves)]
        for i,(txt,cmd) in enumerate(buttons):
            b=ttk.Button(frm,text=txt,command=cmd); b.grid(row=8+(i//4),column=i%4,padx=7,pady=4,sticky="ew"); setattr(self,"b_"+txt.lower().replace(" ","_"),b)
        self.status_label=ttk.Label(frm,textvariable=self.status); self.status_label.grid(row=10,column=0,columnspan=5,sticky="w",pady=(6,0))
        self.txt=tk.Text(frm,width=124,height=29,font=("Consolas",9),wrap="none"); self.txt.grid(row=11,column=0,columnspan=5,sticky="nsew")
        sb=ttk.Scrollbar(frm,orient="vertical",command=self.txt.yview); sb.grid(row=11,column=5,sticky="ns"); self.txt.configure(yscrollcommand=sb.set)
        ttk.Label(frm,text="Workflow: choose Primary + Secondary → SAFE TEST → INSTALL LAST TEST. For existing saves: PATCH SAVE / PATCH ALL SAVES. Close the game before save patching.",wraplength=980).grid(row=12,column=0,columnspan=5,sticky="w",pady=(8,0))
        ttk.Label(frm,text="IMPORTANT: If Secondary text shows symbols/boxes, SWAP Primary and Secondary.",foreground="darkred",wraplength=1050).grid(row=13,column=0,columnspan=5,sticky="w",pady=(5,0))
        ttk.Label(frm,text="Author: ExiZZ • Nexus Mods",foreground="dimgray").grid(row=14,column=0,columnspan=5,sticky="w",pady=(5,0))

    def _load_state(self):
        try:
            if self.state_file.is_file():
                p=self.state_file.read_text(encoding="utf-8").strip().split("|")
                if len(p)>=4:
                    self.path.delete(0,"end"); self.path.insert(0,p[0]); self.primary.set(p[1]); self.secondary.set(p[2]); self.last_manifest=p[3]
        except Exception: pass

    def _save_state(self):
        try: self.state_file.write_text("|".join([self.path.get().strip(),self.primary.get(),self.secondary.get(),self.last_manifest or ""]),encoding="utf-8")
        except Exception: pass

    def log(self,msg):
        self.txt.insert("end",msg+"\n"); self.txt.see("end")
        try: self.log_file.write_text(self.txt.get("1.0","end"),encoding="utf-8")
        except Exception: pass

    def clear_log(self): self.txt.delete("1.0","end")
    def browse(self):
        p=filedialog.askdirectory(title="Select The Witcher Enhanced Edition folder")
        if p: self.path.delete(0,"end"); self.path.insert(0,p); self.refresh_languages()
    def valid_game(self):
        g=Path(self.path.get().strip()); return (g/"Data"/"dialogues00.bif").is_file() and (g/"Data"/"quests00.bif").is_file()

    def run_engine(self,args,callback):
        if self.busy: return
        self.busy=True; self.update_buttons(); self.status.set("Working…")
        def worker():
            try:
                cmd=[sys.executable,str(self.engine)]+args
                if getattr(sys,"frozen",False):
                    # In the public EXE the GUI is frozen but the engine is shipped beside it.
                    cmd=[sys.executable,str(self.engine)]+args
                p=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace")
                out=(p.stdout or "").strip(); err=(p.stderr or "").strip()
                if err: out += ("\n" if out else "")+err
                try: result=json.loads(out.splitlines()[-1]) if out else {"error":"No output"}
                except Exception: result={"error":out or "Unknown error"}
                self.root.after(0,lambda: callback(result,p.returncode))
            except Exception as e: self.root.after(0,lambda:self._finish_error(str(e)))
        threading.Thread(target=worker,daemon=True).start()

    def _finish_error(self,e): self.busy=False; self.status.set("Error"); self.log("ERROR: "+e); messagebox.showerror("Error",e); self.update_buttons()
    def update_buttons(self):
        state="disabled" if self.busy else "normal"
        for n in ["b_safe_test","b_install_last_test","b_restore_original","b_clear_log","b_show_last_changes","b_patch_save","b_patch_all_saves"]:
            if hasattr(self,n): getattr(self,n).configure(state=state)

    def refresh_languages(self):
        if not self.valid_game(): return
        self.run_engine(["scan-languages","--game",self.path.get().strip()],self.languages_done)
    def languages_done(self,r,code):
        self.busy=False
        if code or "error" in r: self.log("Language scan failed: "+str(r.get("error",r))); self.update_buttons(); return
        self.languages=r.get("available",[]); self.lang_by_id={x["language_id"]:x for x in self.languages}
        vals=[f'{x["language_id"]}: {x["language"]}' for x in self.languages]
        self.primary_box["values"]=vals; self.secondary_box["values"]=vals
        if vals:
            if self.primary.get() not in vals: self.primary.set(vals[0])
            if self.secondary.get() not in vals or self.secondary.get()==self.primary.get(): self.secondary.set(vals[1] if len(vals)>1 else vals[0])
        self.update_language_info(); self.update_buttons()
    def display_language(self,v): return v.split(":",1)[0].strip() if ":" in v else v
    def get_lang_id(self,v): return int(self.display_language(v))
    def pair(self):
        p=self.get_lang_id(self.primary.get()); s=self.get_lang_id(self.secondary.get())
        if p==s: raise ValueError("Primary and Secondary languages must be different")
        return p,s
    def update_language_info(self):
        try:
            p,s=self.pair(); self.lang_info.set(f"Primary: {LANG_NAMES.get(p,p)}  •  Secondary: {LANG_NAMES.get(s,s)}")
        except Exception: self.lang_info.set("")

    def safe_test(self):
        if not self.valid_game(): return messagebox.showerror("Game path","Select a valid Witcher 1 game folder first.")
        try: p,s=self.pair()
        except Exception as e: return messagebox.showerror("Language pair",str(e))
        out=Path(tempfile.mkdtemp(prefix="W1_Dual_Test_",dir=self.base)); self.last_candidate=str(out); self.log("=== SAFE TEST ===")
        self.run_engine(["build-all","--game",self.path.get().strip(),"--outdir",str(out),"--primary-id",str(p),"--secondary-id",str(s)],lambda r,c:self.test_done(r,c,p,s,out))

    def test_done(self,r,code,p,s,out):
        if code or "error" in r: self.busy=False; self.status.set("SAFE TEST failed"); self.log(json.dumps(r,ensure_ascii=False,indent=2)); self.update_buttons(); return
        self.last_manifest=str(out/"manifest.json")
        manifest={"dialogues_out":r["dialogues_out"],"quests_out":r["quests_out"],"primary_id":p,"secondary_id":s}
        Path(self.last_manifest).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        if self.english_menu.get():
            tlk=out/"dialog_primary_ui.tlk"
            # build_tlk_ui can be run synchronously via a second engine call
            cmd=[sys.executable,str(self.engine),"build-tlk-ui","--game",self.path.get().strip(),"--out",str(tlk),"--primary-id",str(p)]
            q=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace")
            if q.returncode or "error" in q.stdout: self.busy=False; self.status.set("SAFE TEST failed"); self.log(q.stdout or q.stderr); self.update_buttons(); return
            self.last_tlk_candidate=str(tlk)
        self.busy=False; self.status.set("SAFE TEST successful — ready to install"); self.log(json.dumps(r,ensure_ascii=False,indent=2)); self._save_state(); self.update_buttons(); messagebox.showinfo("SAFE TEST","SAFE TEST completed successfully. You can now use INSTALL LAST TEST.")

    def install_last(self):
        if not self.last_manifest or not Path(self.last_manifest).is_file(): return messagebox.showwarning("INSTALL","Run SAFE TEST successfully first.")
        if messagebox.askyesno("INSTALL LAST TEST","Install the last successful SAFE TEST candidate? The game must be closed."):
            try: p,_=self.pair()
            except Exception as e: return messagebox.showerror("Language pair",str(e))
            args=["install","--game",self.path.get().strip(),"--out",str(Path(self.last_manifest).parent/"dialogues00.dual.bif"),"--primary-id",str(p)]
            # Install is performed directly by the engine for one BIF; use a tiny helper block here for both outputs.
            def worker():
                try:
                    import witcher1_dual as eng
                    m=json.loads(Path(self.last_manifest).read_text(encoding="utf-8")); g=Path(self.path.get().strip())
                    res=eng.install_candidates(g,self.last_manifest,self.last_tlk_candidate,p)
                    self.root.after(0,lambda:self.install_done(res,0))
                except Exception as e:self.root.after(0,lambda:self.install_done({"error":str(e)},1))
            self.busy=True; self.update_buttons(); self.status.set("Installing…"); threading.Thread(target=worker,daemon=True).start()
    def install_done(self,r,code):
        self.busy=False; self.update_buttons(); self.status.set("Installed" if code==0 and "error" not in r else "Install failed"); self.log(json.dumps(r,ensure_ascii=False,indent=2));
        if code==0 and "error" not in r: messagebox.showinfo("INSTALL","The last SAFE TEST candidate was installed.")
        else: messagebox.showerror("INSTALL",str(r.get("error",r)))

    def restore(self):
        if not messagebox.askyesno("RESTORE ORIGINAL","Restore all original BIF/TLK files saved by this tool?"): return
        self.log("=== RESTORE ORIGINAL ==="); self.run_engine(["restore","--game",self.path.get().strip()],self.restore_done)
    def restore_done(self,r,c): self.busy=False; self.update_buttons(); self.status.set("Restored" if c==0 and "error" not in r else "Restore failed"); self.log(json.dumps(r,ensure_ascii=False,indent=2));
    def show_report(self):
        if self.last_report and Path(self.last_report).is_file(): os.startfile(self.last_report)
        elif self.last_manifest and Path(self.last_manifest).is_file(): os.startfile(self.last_manifest)
        else: messagebox.showinfo("Last changes","No report is available yet.")

    def patch_save(self):
        try: p,s=self.pair()
        except Exception as e: return messagebox.showerror("Language pair",str(e))
        f=filedialog.askopenfilename(title="Select The Witcher save",filetypes=[("The Witcher saves","*.TheWitcherSave"),("All files","*.*")])
        if not f:return
        if not messagebox.askyesno("PATCH SAVE","The game must be CLOSED. A .dual_backup will be created before replacement. Continue?"):return
        self.status.set("Patching save…"); self.log("=== PATCH SAVE ===")
        self.run_engine(["patch-save","--bif",f,"--primary-id",str(p),"--secondary-id",str(s)],self.save_done)
    def save_done(self,r,c): self.busy=False; self.update_buttons(); self.status.set("Save patched" if c==0 and "error" not in r else "Save patch failed"); self.log(json.dumps(r,ensure_ascii=False,indent=2));
    def patch_all_saves(self):
        try:p,s=self.pair()
        except Exception as e:return messagebox.showerror("Language pair",str(e))
        folder=filedialog.askdirectory(title="Select The Witcher save folder")
        if not folder:return
        saves=sorted(Path(folder).glob("*.TheWitcherSave"),key=lambda x:x.name.lower())
        if not saves:return messagebox.showinfo("No saves","No .TheWitcherSave files were found.")
        if not messagebox.askyesno("PATCH ALL SAVES",f"The game must be CLOSED.\n\nFound {len(saves)} save(s).\n\nPair: {LANG_NAMES.get(p,p)} + {LANG_NAMES.get(s,s)}\n\nEach save gets a .dual_backup. Continue?"):return
        self.status.set("Patching all saves…"); self.log("=== PATCH ALL SAVES ===")
        self.run_engine(["patch-save","--folder",folder,"--primary-id",str(p),"--secondary-id",str(s)],self.all_saves_done)
    def all_saves_done(self,r,c): self.busy=False; self.update_buttons(); self.status.set("All saves patched" if c==0 and "error" not in r else "Patch all failed"); self.log(json.dumps(r,ensure_ascii=False,indent=2))

if __name__ == "__main__":
    root=tk.Tk(); App(root); root.mainloop()
