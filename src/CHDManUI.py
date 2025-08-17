import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import glob
import sys
import shutil
import threading
import re

# Optional drag-and-drop support
try:
    import tkinterdnd2 as tkdnd  # type: ignore
    DND_AVAILABLE = True
except ImportError:
    tkdnd = None
    DND_AVAILABLE = False

# --- Detect chdman.exe ---
def find_chdman():
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    local_path = os.path.join(base_dir, "chdman.exe")
    if os.path.isfile(local_path):
        return local_path
    found = shutil.which("chdman")
    if found:
        return found
    return None

CHDMAN_PATH = find_chdman()

SYSTEMS = [
    "Sony PlayStation (PS1)",
    "Sony PlayStation 2 (PS2)",
    "Sega Saturn",
    "Sega Dreamcast",
    "Sega / Mega CD",
    "SNK Neo Geo CD",
    "NEC TurboGrafx CD / PC Engine CD",
    "3DO",
    "Commodore Amiga CD32",
]

# Sorted list for UI dropdown
SYSTEMS_SORTED = sorted(SYSTEMS)

# Map systems to supported input extensions
SYSTEM_FILETYPES = {
    "Sony PlayStation (PS1)": [".cue", ".iso"],
    "Sony PlayStation 2 (PS2)": [".cue", ".iso"],  # .iso will use createdvd
    "Sega Saturn": [".cue", ".iso"],
    "Sega Dreamcast": [".gdi", ".cue", ".cdi", ".iso"],
    "Sega / Mega CD": [".cue", ".iso"],
    "Neo Geo CD": [".cue", ".iso"],
    "TurboGrafx / PC Engine CD": [".cue", ".iso"],
    "3DO": [".cue", ".iso"],
    "Commodore Amiga CD32": [".cue", ".iso"],
}

def build_filetypes(system: str):
    exts = SYSTEM_FILETYPES.get(system, [".cue", ".gdi", ".iso"])
    patterns = " ".join(f"*{e}" for e in exts)
    return [("Disc files", patterns), ("All files", "*.*")], exts

def choose_subcommand(system: str, input_path: str) -> str:
    # PS2 DVD images should use createdvd, CDs use createcd
    if "PlayStation 2" in system and input_path.lower().endswith(".iso"):
        return "createdvd"
    return "createcd"

# --- Conversion Functions ---
def run_chdman(input_file, output_file, progress_cb=None, subcommand: str = "createcd"):
    if not CHDMAN_PATH:
        messagebox.showerror("Error", "Could not find chdman.exe!\nPut it in the same folder or PATH.")
        return False
    try:
        # Stream output so we can parse percentages as they appear
        proc = subprocess.Popen(
            [CHDMAN_PATH, subcommand, "-i", input_file, "-o", output_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,  # unbuffered so we see CR updates
            universal_newlines=True,
        )

        # Some chdman builds update progress using carriage returns without newlines.
        # Read small chunks and search for percentages incrementally.
        if proc.stdout is not None:
            buffer = ""
            # open a small log next to the script/exe to inspect later
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chd_output.log")
            try:
                logf = open(log_path, "a", encoding="utf-8", errors="ignore")
            except Exception:
                logf = None
            while True:
                chunk = proc.stdout.read(64)
                if not chunk:
                    break
                buffer += chunk
                # Mirror last snippet to the UI for debugging
                tail = buffer[-80:].replace("\r", " ").replace("\n", " ")
                try:
                    root.after(0, lambda t=tail: output_tail_var.set(t))
                except Exception:
                    pass
                if logf:
                    try:
                        logf.write(chunk)
                        logf.flush()
                    except Exception:
                        pass
                if progress_cb:
                    # Match integers or decimals before '%', e.g., 2% or 2.1%
                    for m in re.finditer(r"(\d{1,3}(?:\.\d+)?)\s*%", buffer):
                        try:
                            pct = float(m.group(1))
                            if 0.0 <= pct <= 100.0:
                                progress_cb(pct)
                        except ValueError:
                            pass
                # Keep a small tail to catch split tokens like '9' + '%'
                if len(buffer) > 128:
                    buffer = buffer[-16:]
            if logf:
                try:
                    logf.close()
                except Exception:
                    pass
        proc.wait()
        # Ensure we end at 100% on success
        if proc.returncode == 0 and progress_cb:
            progress_cb(100.0)
        return proc.returncode == 0
    except Exception:
        return False

def update_status(message):
    # Ensure UI updates happen on the main thread
    try:
        root.after(0, lambda: status_var.set(message))
    except Exception:
        pass

def set_progress(pct):
    try:
        clamped = max(0.0, min(100.0, float(pct)))
        def apply():
            # make sure we're in determinate mode and not animating
            try:
                progress_bar.stop()
            except Exception:
                pass
            progress_bar.config(mode="determinate", value=int(round(clamped)), maximum=100)
            percent_var.set(f"{clamped:.1f}%")
        root.after(0, apply)
    except Exception:
        pass

def convert_files(files, system):
    total, success, fail = len(files), 0, 0
    for idx, f in enumerate(files, 1):
        output_file = os.path.splitext(f)[0] + ".chd"
        update_status(f"[{idx}/{total}] Converting: {os.path.basename(f)}")
        # Reset progress for each file
        set_progress(0)
        subcmd = choose_subcommand(system, f)
        if run_chdman(f, output_file, progress_cb=set_progress, subcommand=subcmd):
            success += 1
        else:
            fail += 1
    update_status("Idle")
    set_progress(0)
    percent_var.set("")
    messagebox.showinfo("Batch Complete", f"{system}\nConverted: {success}\nFailed: {fail}")

# --- UI Functions ---
def select_single():
    system = system_var.get()
    filetypes, exts = build_filetypes(system)
    cue_file = filedialog.askopenfilename(title="Select Disc Image", filetypes=filetypes)
    if not cue_file: return
    default_out = os.path.splitext(cue_file)[0] + ".chd"
    save_file = filedialog.asksaveasfilename(title="Save CHD as",
                                             defaultextension=".chd",
                                             initialfile=os.path.basename(default_out),
                                             filetypes=[("CHD files", "*.chd")])
    if not save_file: return
    # Run conversion for a single item, but honor the chosen output path
    def single_convert():
        update_status(f"[1/1] Converting: {os.path.basename(cue_file)}")
        set_progress(0)
        subcmd = choose_subcommand(system, cue_file)
        ok = run_chdman(cue_file, save_file, progress_cb=set_progress, subcommand=subcmd)
        update_status("Idle")
        set_progress(0)
        percent_var.set("")
        messagebox.showinfo("Conversion Complete", f"{system}\nConverted: {1 if ok else 0}\nFailed: {0 if ok else 1}")
    threading.Thread(target=single_convert, daemon=True).start()

def select_batch():
    system = system_var.get()
    folder = filedialog.askdirectory(title="Select Folder with Disc Images")
    if not folder: return
    _, exts = build_filetypes(system)
    files = []
    for e in exts:
        files += glob.glob(os.path.join(folder, f"*{e}"))
    if not files:
        messagebox.showwarning("No files", "No .cue/.gdi/.iso files found.")
        return
    threading.Thread(target=convert_files, args=(files, system), daemon=True).start()

def handle_drop(event):
    paths = root.tk.splitlist(event.data)
    files, folders = [], []
    for p in paths:
        if os.path.isfile(p) and p.lower().endswith(('.cue', '.gdi', '.iso', '.cdi')):
            files.append(p)
        elif os.path.isdir(p):
            folders.append(p)
    for folder in folders:
        files += glob.glob(os.path.join(folder, "*.cue")) + \
                 glob.glob(os.path.join(folder, "*.gdi")) + \
                 glob.glob(os.path.join(folder, "*.iso")) + \
                 glob.glob(os.path.join(folder, "*.cdi"))
    if files:
        threading.Thread(target=convert_files, args=(files, system_var.get()), daemon=True).start()

# --- UI Setup ---
# Create the root window; if DnD is available, use the specialized Tk class.
root = (tkdnd.TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk())
root.title("CHDMan Frontend v1.0 Beta")
root.configure(bg="#1e1e1e")
root.geometry("700x650")  # slightly taller to accommodate bigger buttons

frame = tk.Frame(root, padx=20, pady=20, bg="#1e1e1e")
frame.pack(fill="both", expand=True)

style = ttk.Style(root)
style.theme_use("clam")
style.configure("TButton",
                background="#2d2d30",
                foreground="white",
                padding=(10,30),  # taller buttons (50px visually more)
                relief="flat")
style.map("TButton", background=[("active", "#3e3e40")])
style.configure("TLabel", background="#1e1e1e", foreground="white")
style.configure("TProgressbar", background="#00aaff", troughcolor="#2d2d30", bordercolor="#1e1e1e")

# --- Widgets ---
title_label = ttk.Label(frame, text="BIN/CUE → CHD Converter", font=("Segoe UI", 14, "bold"))
title_label.pack(pady=(0, 10))

default_system = "Sony PlayStation (PS1)" if "Sony PlayStation (PS1)" in SYSTEMS else SYSTEMS_SORTED[0]
system_var = tk.StringVar(value=default_system)
system_dropdown = ttk.Combobox(frame, textvariable=system_var, values=SYSTEMS_SORTED, state="readonly", width=35)
system_dropdown.pack(pady=5)

button_width = 30  # uniform width for all buttons

ttk.Button(frame, text="Convert Single File", command=select_single, width=button_width).pack(pady=10)
ttk.Button(frame, text="Batch Convert Folder", command=select_batch, width=button_width).pack(pady=10)
ttk.Button(frame, text="Quit", command=root.quit, width=button_width).pack(pady=10)

status_var = tk.StringVar(value="Idle")
status_label = ttk.Label(frame, textvariable=status_var)
status_label.pack(pady=10)

progress_bar = ttk.Progressbar(frame, mode="determinate", length=350, maximum=100)
progress_bar.pack(pady=10)

# Live output tail (for diagnosing progress parsing)
output_tail_var = tk.StringVar(value="")
output_tail_label = ttk.Label(frame, textvariable=output_tail_var, foreground="#9e9e9e")
output_tail_label.pack(pady=(0, 6))

# Percent label under the bar
percent_var = tk.StringVar(value="")
percent_label = ttk.Label(frame, textvariable=percent_var)
percent_label.pack(pady=(0, 10))

# Enable drag and drop (optional)
if DND_AVAILABLE:
    try:
        root.drop_target_register(tkdnd.DND_FILES)
        root.dnd_bind('<<Drop>>', handle_drop)
    except Exception:
        pass

root.mainloop()
