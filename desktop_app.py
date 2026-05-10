"""
Medication Indication Mapper — Desktop App
==========================================
Standalone Tkinter GUI. Same processing engine as the Streamlit web app.

Run: py desktop_app.py
     (from the medication_mapper directory)

Features:
  - Structured CSV/Excel file upload with column validation
  - Free-text / paste tab for quick testing
  - API status bar (RxNorm, openFDA NDC, ICD-10 NLM)
  - Background thread processing (UI stays responsive)
  - Sortable, scrollable results table with row colour coding
  - Search + filter controls (manual review, HCC flag, confidence)
  - Export to Excel, tab-delimited text, or CSV
"""

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

# ── Ensure the script can find parser.py in the same directory ────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from parser import (
    REQUIRED_INPUT_COLS,
    STRUCTURED_OUTPUT_COLS,
    parse_structured_dataframe,
    parse_medication_list,
)

# ── Colour palette ────────────────────────────────────────────────────────────
CLR_BG        = "#f0f4f8"
CLR_HEADER    = "#1a3c5e"
CLR_ACCENT    = "#4a6fa5"
CLR_WARNING   = "#fff3cd"
CLR_WARN_TEXT = "#856404"
CLR_ROW_ALT   = "#e8f0fa"
CLR_ROW_NORM  = "#ffffff"
CLR_YES_HCC   = "#fff3cd"
CLR_YES_REV   = "#f8d7da"

DISCLAIMER = (
    "⚠  Research / Support Tool — All outputs are POSSIBLE indications only. "
    "Not confirmed diagnoses. Not for clinical use or billing."
)

FREETEXT_SAMPLE = """\
Metformin 500 mg
Lisinopril 10 mg
Atorvastatin 40 mg
Gabapentin 300 mg
Prednisone 10 mg
Warfarin 5 mg
RXCUI:860975
310798
UnknownDrugXYZ 100 mg
"""


# ═════════════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Medication Indication Mapper")
        self.geometry("1400x900")
        self.minsize(900, 600)
        self.configure(bg=CLR_BG)

        # State
        self._file_path: str = ""
        self._df_input:  pd.DataFrame | None = None
        self._df_result: pd.DataFrame | None = None
        self._sort_col:  str = ""
        self._sort_asc:  bool = True
        self._result_q:  queue.Queue = queue.Queue()

        self._build_ui()
        self._poll_result_queue()
        self._check_apis_async()

    # ─── UI construction ──────────────────────────────────────────────────────
    def _build_ui(self):
        self.rowconfigure(0, weight=0)  # disclaimer
        self.rowconfigure(1, weight=0)  # api status
        self.rowconfigure(2, weight=0)  # notebook (input tabs)
        self.rowconfigure(3, weight=0)  # metrics
        self.rowconfigure(4, weight=0)  # filters
        self.rowconfigure(5, weight=1)  # table
        self.rowconfigure(6, weight=0)  # export
        self.columnconfigure(0, weight=1)

        self._build_disclaimer()
        self._build_api_status()
        self._build_input_notebook()
        self._build_metrics_frame()
        self._build_filter_frame()
        self._build_table_frame()
        self._build_export_frame()

    def _build_disclaimer(self):
        frm = tk.Frame(self, bg=CLR_WARNING, pady=6, padx=10)
        frm.grid(row=0, column=0, sticky="ew")
        tk.Label(
            frm, text=DISCLAIMER, bg=CLR_WARNING, fg=CLR_WARN_TEXT,
            font=("Segoe UI", 9, "bold"), wraplength=1300, justify="left",
        ).pack(anchor="w")

    def _build_api_status(self):
        """Horizontal API status strip below disclaimer."""
        frm = tk.Frame(self, bg=CLR_BG, pady=3, padx=10)
        frm.grid(row=1, column=0, sticky="ew")

        self._api_rxnorm = tk.Label(frm, text="RxNorm API: checking…",
                                    font=("Segoe UI", 8), bg=CLR_BG, fg=CLR_ACCENT)
        self._api_rxnorm.pack(side="left", padx=8)

        self._api_ndc = tk.Label(frm, text="openFDA NDC: checking…",
                                 font=("Segoe UI", 8), bg=CLR_BG, fg=CLR_ACCENT)
        self._api_ndc.pack(side="left", padx=8)

        self._api_icd10 = tk.Label(frm, text="ICD-10 NLM: checking…",
                                   font=("Segoe UI", 8), bg=CLR_BG, fg=CLR_ACCENT)
        self._api_icd10.pack(side="left", padx=8)

        tk.Label(frm, text="HCC: CMS-HCC v28 crosswalk (local — offline capable)",
                 font=("Segoe UI", 8), bg=CLR_WARNING, fg=CLR_WARN_TEXT,
                 padx=6, pady=2).pack(side="left", padx=12)

    def _check_apis_async(self):
        """Check API status in a background thread; update labels on main thread."""
        def _check():
            try:
                from rxnorm_client import check_api_available
                rx_ok = check_api_available()
            except Exception:
                rx_ok = False
            try:
                from ndc_client import check_ndc_api_available
                ndc_ok = check_ndc_api_available()
            except Exception:
                ndc_ok = False
            try:
                from icd10_client import lookup_description
                icd_ok = bool(lookup_description("E11.9"))
            except Exception:
                icd_ok = False
            self.after(0, lambda: self._update_api_labels(rx_ok, ndc_ok, icd_ok))

        threading.Thread(target=_check, daemon=True).start()

    def _update_api_labels(self, rx_ok: bool, ndc_ok: bool, icd_ok: bool):
        def _fmt(lbl, name, ok):
            lbl.config(
                text=f"{name}: {'Online' if ok else 'Offline'}",
                fg="#155724" if ok else "#721c24",
            )
        _fmt(self._api_rxnorm, "RxNorm API", rx_ok)
        _fmt(self._api_ndc,    "openFDA NDC", ndc_ok)
        _fmt(self._api_icd10,  "ICD-10 NLM", icd_ok)

    def _build_input_notebook(self):
        """Tabbed input area: structured file upload + free-text paste."""
        nb_outer = tk.Frame(self, bg=CLR_BG)
        nb_outer.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 2))
        nb_outer.columnconfigure(0, weight=1)

        nb = ttk.Notebook(nb_outer)
        nb.pack(fill="x", expand=True)
        self._input_nb = nb

        # ── Tab 1: Structured file ────────────────────────────────────────────
        tab1 = tk.Frame(nb, bg=CLR_BG)
        nb.add(tab1, text="  Structured File Upload (CSV / Excel)  <- Primary  ")
        tab1.columnconfigure(1, weight=1)

        # Required columns info
        info_lbl = tk.Label(
            tab1,
            text="Required columns: " + " | ".join(REQUIRED_INPUT_COLS),
            font=("Consolas", 8), bg="#e8f0fa", fg=CLR_HEADER,
            padx=6, pady=3, anchor="w",
        )
        info_lbl.grid(row=0, column=0, columnspan=3, sticky="ew", padx=4, pady=(6, 2))

        tk.Label(tab1, text="File:", bg=CLR_BG, font=("Segoe UI", 9)).grid(
            row=1, column=0, sticky="w", padx=(4, 6), pady=4)
        self._path_var = tk.StringVar()
        tk.Entry(
            tab1, textvariable=self._path_var, state="readonly",
            font=("Consolas", 9), width=80,
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        tk.Button(
            tab1, text="Browse…", command=self._browse_file,
            bg=CLR_ACCENT, fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", padx=10,
        ).grid(row=1, column=2, sticky="e", padx=(0, 4))

        self._file_info_lbl = tk.Label(
            tab1, text="", bg=CLR_BG, fg=CLR_HEADER, font=("Segoe UI", 9),
        )
        self._file_info_lbl.grid(row=2, column=0, columnspan=3, sticky="w", padx=4)

        self._col_status_lbl = tk.Label(
            tab1, text="", bg=CLR_BG, font=("Segoe UI", 9),
        )
        self._col_status_lbl.grid(row=3, column=0, columnspan=3, sticky="w", padx=4)

        # Process button + progress
        ctrl = tk.Frame(tab1, bg=CLR_BG)
        ctrl.grid(row=4, column=0, columnspan=3, sticky="ew", padx=4, pady=6)
        ctrl.columnconfigure(2, weight=1)

        self._run_btn = tk.Button(
            ctrl, text="▶  Process File", command=self._start_processing,
            bg="#155724", fg="white", font=("Segoe UI", 10, "bold"),
            relief="flat", padx=16, pady=4, state="disabled",
        )
        self._run_btn.grid(row=0, column=0, sticky="w", padx=(0, 12))

        self._progress = ttk.Progressbar(ctrl, mode="indeterminate", length=300)
        self._progress.grid(row=0, column=1, sticky="w", padx=(0, 12))

        self._status_lbl = tk.Label(
            ctrl, text="Select a file to begin.", bg=CLR_BG,
            fg=CLR_HEADER, font=("Segoe UI", 9),
        )
        self._status_lbl.grid(row=0, column=2, sticky="w")

        # ── Tab 2: Free text ──────────────────────────────────────────────────
        tab2 = tk.Frame(nb, bg=CLR_BG)
        nb.add(tab2, text="  Free Text / Paste  <- Quick Test  ")
        tab2.rowconfigure(1, weight=1)
        tab2.columnconfigure(0, weight=1)

        hints = (
            "Metformin 500 mg  |  Lipitor 40mg  |  RXCUI:860975  |  860975  |  Atorvastatin RXCUI:83367"
        )
        tk.Label(tab2, text=f"Supported formats: {hints}",
                 font=("Segoe UI", 8), bg=CLR_BG, fg=CLR_ACCENT,
                 anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 2))

        txt_scroll = ttk.Scrollbar(tab2, orient="vertical")
        txt_scroll.grid(row=1, column=1, sticky="ns", padx=(0, 4), pady=4)
        self._ft_text = tk.Text(
            tab2, font=("Consolas", 9), height=8,
            yscrollcommand=txt_scroll.set, wrap="word",
        )
        self._ft_text.grid(row=1, column=0, sticky="nsew", padx=(6, 0), pady=4)
        txt_scroll.config(command=self._ft_text.yview)

        ft_ctrl = tk.Frame(tab2, bg=CLR_BG)
        ft_ctrl.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))

        tk.Button(
            ft_ctrl, text="Load Sample", command=self._load_ft_sample,
            bg=CLR_ACCENT, fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", padx=10, pady=3,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            ft_ctrl, text="Upload .txt / .csv", command=self._browse_ft_file,
            bg=CLR_ACCENT, fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", padx=10, pady=3,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            ft_ctrl, text="▶  Process Free Text", command=self._start_ft_processing,
            bg="#155724", fg="white", font=("Segoe UI", 10, "bold"),
            relief="flat", padx=14, pady=3,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            ft_ctrl, text="Clear", command=self._clear_ft,
            bg="#888888", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", padx=10, pady=3,
        ).pack(side="left")

        self._ft_status_lbl = tk.Label(
            ft_ctrl, text="", font=("Segoe UI", 9), bg=CLR_BG, fg="#155724",
        )
        self._ft_status_lbl.pack(side="left", padx=12)

    def _build_metrics_frame(self):
        self._metrics_frm = tk.Frame(self, bg=CLR_BG)
        self._metrics_frm.grid(row=3, column=0, sticky="ew", padx=12, pady=(2, 0))
        self._metric_labels: dict[str, tk.Label] = {}
        for i, (key, title) in enumerate([
            ("total",      "Total Rows"),
            ("recognized", "Recognized"),
            ("unknown",    "Unknown"),
            ("review",     "Manual Review"),
            ("hcc",        "High Value HCC"),
            ("api",        "Via API"),
        ]):
            card = tk.Frame(self._metrics_frm, bg="white", relief="ridge", bd=1, padx=12, pady=6)
            card.grid(row=0, column=i, padx=4, pady=4, sticky="nsew")
            self._metrics_frm.columnconfigure(i, weight=1)
            tk.Label(card, text=title, bg="white", fg=CLR_ACCENT,
                     font=("Segoe UI", 8)).pack()
            lbl = tk.Label(card, text="—", bg="white", fg=CLR_HEADER,
                           font=("Segoe UI", 14, "bold"))
            lbl.pack()
            self._metric_labels[key] = lbl

    def _build_filter_frame(self):
        frm = tk.Frame(self, bg=CLR_BG, pady=4)
        frm.grid(row=4, column=0, sticky="ew", padx=12)

        tk.Label(frm, text="Search:", bg=CLR_BG, font=("Segoe UI", 9)).pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filters())
        tk.Entry(frm, textvariable=self._search_var, width=24,
                 font=("Segoe UI", 9)).pack(side="left", padx=(4, 14))

        tk.Label(frm, text="Manual Review:", bg=CLR_BG, font=("Segoe UI", 9)).pack(side="left")
        self._review_var = tk.StringVar(value="All")
        self._review_var.trace_add("write", lambda *_: self._apply_filters())
        ttk.Combobox(
            frm, textvariable=self._review_var, values=["All", "YES", "No"],
            state="readonly", width=8,
        ).pack(side="left", padx=(4, 14))

        tk.Label(frm, text="High Value HCC:", bg=CLR_BG, font=("Segoe UI", 9)).pack(side="left")
        self._hcc_var = tk.StringVar(value="All")
        self._hcc_var.trace_add("write", lambda *_: self._apply_filters())
        ttk.Combobox(
            frm, textvariable=self._hcc_var,
            values=["All", "YES — Review", "No", "Unknown — Manual Review"],
            state="readonly", width=22,
        ).pack(side="left", padx=(4, 14))

        tk.Label(frm, text="Confidence:", bg=CLR_BG, font=("Segoe UI", 9)).pack(side="left")
        self._conf_var = tk.StringVar(value="All")
        self._conf_var.trace_add("write", lambda *_: self._apply_filters())
        ttk.Combobox(
            frm, textvariable=self._conf_var,
            values=["All", "High", "Medium", "Low", "Unknown"],
            state="readonly", width=10,
        ).pack(side="left", padx=(4, 14))

        self._row_count_lbl = tk.Label(frm, text="", bg=CLR_BG,
                                       fg=CLR_ACCENT, font=("Segoe UI", 9))
        self._row_count_lbl.pack(side="right", padx=4)

    def _build_table_frame(self):
        frm = tk.Frame(self, bg=CLR_BG)
        frm.grid(row=5, column=0, sticky="nsew", padx=12, pady=(2, 4))
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)

        # Columns are configured dynamically in _populate_tree so results from
        # both structured and free-text modes display correctly.
        self._tree = ttk.Treeview(
            frm,
            columns=[],
            show="headings",
            selectmode="browse",
        )

        # Style
        style = ttk.Style()
        style.configure("Treeview", font=("Segoe UI", 8), rowheight=22)
        style.configure("Treeview.Heading", font=("Segoe UI", 8, "bold"))
        self._tree.tag_configure("alt",    background=CLR_ROW_ALT)
        self._tree.tag_configure("norm",   background=CLR_ROW_NORM)
        self._tree.tag_configure("hcc",    background=CLR_YES_HCC)
        self._tree.tag_configure("review", background=CLR_YES_REV)

        vsb = ttk.Scrollbar(frm, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(frm, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

    def _build_export_frame(self):
        frm = tk.LabelFrame(
            self, text="Step 3 — Export Results",
            bg=CLR_BG, fg=CLR_HEADER, font=("Segoe UI", 10, "bold"),
            padx=10, pady=6,
        )
        frm.grid(row=6, column=0, sticky="ew", padx=12, pady=(0, 8))

        tk.Button(
            frm, text="📥  Export to Excel (.xlsx)",
            command=self._export_excel,
            bg=CLR_ACCENT, fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", padx=12, pady=4,
        ).pack(side="left", padx=(0, 12))

        tk.Button(
            frm, text="📥  Export to Text (.txt, tab-delimited)",
            command=self._export_tsv,
            bg=CLR_ACCENT, fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", padx=12, pady=4,
        ).pack(side="left", padx=(0, 12))

        tk.Button(
            frm, text="📥  Export to CSV (.csv)",
            command=self._export_csv,
            bg=CLR_ACCENT, fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", padx=12, pady=4,
        ).pack(side="left")

        tk.Label(
            frm,
            text="Exports always use the full unfiltered results table.",
            bg=CLR_BG, fg="gray", font=("Segoe UI", 8),
        ).pack(side="left", padx=16)

    # ─── Free-text helpers ────────────────────────────────────────────────────
    def _load_ft_sample(self):
        self._ft_text.delete("1.0", "end")
        self._ft_text.insert("1.0", FREETEXT_SAMPLE)

    def _browse_ft_file(self):
        path = filedialog.askopenfilename(
            title="Select text file",
            filetypes=[("Text / CSV", "*.txt *.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self._ft_text.delete("1.0", "end")
            self._ft_text.insert("1.0", content)
            self._ft_status_lbl.config(text=f"Loaded: {os.path.basename(path)}", fg=CLR_ACCENT)
        except Exception as e:
            messagebox.showerror("File Error", f"Could not read file:\n{e}")

    def _clear_ft(self):
        self._ft_text.delete("1.0", "end")
        self._ft_status_lbl.config(text="")

    def _start_ft_processing(self):
        raw = self._ft_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("No Input", "Please enter or paste medication names first.")
            return
        self._ft_status_lbl.config(text="Processing…", fg=CLR_ACCENT)
        self._clear_table()
        self._df_result = None

        def worker():
            try:
                results = parse_medication_list(raw)
                if not results:
                    self._result_q.put(("ft_empty", None))
                else:
                    df = pd.DataFrame(results)
                    self._result_q.put(("ft_ok", df))
            except Exception as exc:
                self._result_q.put(("err", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    # ─── File handling ────────────────────────────────────────────────────────
    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select medication input file",
            filetypes=[
                ("CSV / Excel files", "*.csv *.xlsx *.xls"),
                ("CSV",  "*.csv"),
                ("Excel","*.xlsx *.xls"),
                ("All",  "*.*"),
            ],
        )
        if not path:
            return
        self._load_file(path)

    def _load_file(self, path: str):
        self._file_path = path
        self._path_var.set(path)
        self._df_result = None
        self._clear_table()

        try:
            ext = path.rsplit(".", 1)[-1].lower()
            df = pd.read_csv(path, dtype=str) if ext == "csv" else pd.read_excel(path, dtype=str)
        except Exception as exc:
            messagebox.showerror("File Error", f"Could not read file:\n{exc}")
            self._file_info_lbl.config(text="")
            self._col_status_lbl.config(text="")
            self._run_btn.config(state="disabled")
            return

        self._df_input = df
        self._file_info_lbl.config(
            text=f"✔  {os.path.basename(path)}  —  {len(df):,} rows, {len(df.columns)} columns",
            fg="#155724",
        )

        # Column check
        input_lower = {c.lower().strip() for c in df.columns}
        missing = [c for c in REQUIRED_INPUT_COLS if c.lower() not in input_lower]
        extra   = [c for c in df.columns if c.lower().strip() not in
                   {r.lower() for r in REQUIRED_INPUT_COLS}]

        if missing:
            self._col_status_lbl.config(
                text=f"✘  Missing required columns: {missing}",
                fg="#721c24",
            )
            self._run_btn.config(state="disabled")
        else:
            msg = "✔  All required columns found."
            if extra:
                msg += f"   (Extra columns ignored: {extra[:3]}{'…' if len(extra) > 3 else ''})"
            self._col_status_lbl.config(text=msg, fg="#155724")
            self._run_btn.config(state="normal")
            self._status_lbl.config(text="Ready to process.")

    # ─── Processing ───────────────────────────────────────────────────────────
    def _start_processing(self):
        if self._df_input is None:
            return
        self._run_btn.config(state="disabled")
        self._progress.start(10)
        self._status_lbl.config(text="Processing… please wait.")
        self._clear_table()

        def worker():
            try:
                result = parse_structured_dataframe(self._df_input)
                self._result_q.put(("ok", result))
            except Exception as exc:
                self._result_q.put(("err", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_result_queue(self):
        try:
            kind, payload = self._result_q.get_nowait()
            self._progress.stop()
            self._run_btn.config(state="normal")
            if kind == "ok":
                self._df_result = payload
                self._status_lbl.config(
                    text=f"Done — {len(payload):,} rows processed.",
                    fg="#155724",
                )
                self._update_metrics(payload)
                self._apply_filters()
            elif kind == "ft_ok":
                self._df_result = payload
                self._ft_status_lbl.config(
                    text=f"Done — {len(payload):,} rows processed.", fg="#155724"
                )
                self._update_metrics(payload)
                self._apply_filters()
            elif kind == "ft_empty":
                self._ft_status_lbl.config(text="No medication lines found.", fg="#721c24")
            else:
                self._status_lbl.config(text=f"Error: {payload}", fg="#721c24")
                self._ft_status_lbl.config(text=f"Error: {payload}", fg="#721c24")
                messagebox.showerror("Processing Error", payload)
        except queue.Empty:
            pass
        self.after(150, self._poll_result_queue)

    # ─── Metrics ─────────────────────────────────────────────────────────────
    def _update_metrics(self, df: pd.DataFrame):
        total      = len(df)
        unknown    = int(df["Normalized Generic Name"].isin(["Unknown Medication", "Unknown"]).sum()) \
                     if "Normalized Generic Name" in df.columns else 0
        recognized = total - unknown
        review     = int((df["Manual Review Flag"] == "YES").sum()) \
                     if "Manual Review Flag" in df.columns else 0
        hcc        = int(df["High Value HCC Flag"].str.startswith("YES", na=False).sum()) \
                     if "High Value HCC Flag" in df.columns else 0
        api        = int(df["Data Source"].str.contains("API", na=False).sum()) \
                     if "Data Source" in df.columns else 0

        self._metric_labels["total"].config(text=f"{total:,}")
        self._metric_labels["recognized"].config(text=f"{recognized:,}")
        self._metric_labels["unknown"].config(text=f"{unknown:,}")
        self._metric_labels["review"].config(text=f"{review:,}")
        self._metric_labels["hcc"].config(text=f"{hcc:,}")
        self._metric_labels["api"].config(text=f"{api:,}")

    # ─── Table population & filtering ─────────────────────────────────────────
    def _clear_table(self):
        for row in self._tree.get_children():
            self._tree.delete(row)
        self._row_count_lbl.config(text="")

    def _apply_filters(self):
        if self._df_result is None:
            return

        df = self._df_result.copy()

        # Search
        q = self._search_var.get().strip()
        if q:
            mask = df.apply(lambda r: r.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
            df = df[mask]

        # Dropdowns
        rev = self._review_var.get()
        if rev != "All" and "Manual Review Flag" in df.columns:
            df = df[df["Manual Review Flag"] == rev]

        hcc = self._hcc_var.get()
        if hcc != "All" and "High Value HCC Flag" in df.columns:
            df = df[df["High Value HCC Flag"] == hcc]

        conf = self._conf_var.get()
        if conf != "All" and "Confidence Level" in df.columns:
            df = df[df["Confidence Level"] == conf]

        # Sort
        if self._sort_col and self._sort_col in df.columns:
            df = df.sort_values(self._sort_col, ascending=self._sort_asc, na_position="last")

        self._populate_tree(df)
        total = len(self._df_result)
        self._row_count_lbl.config(text=f"Showing {len(df):,} of {total:,} rows")

    def _populate_tree(self, df: pd.DataFrame):
        """Rebuild the treeview columns for df, then insert all rows."""
        # Reconfig columns to match df (handles both structured and free-text result schemas)
        cols = list(df.columns)
        self._tree["columns"] = cols
        self._tree["show"]    = "headings"

        col_widths = {
            "Row Number":                   60,
            "Original Input":              180,
            "MedicationsID":                80,
            "DocID":                        80,
            "DateOfService":                90,
            "Normalized Generic Name":     130,
            "Brand Name Match":            100,
            "Dosage":                       70,
            "Drug Class":                  130,
            "Possible Indication 1":       200,
            "Possible Indication 2":       200,
            "Possible Indication 3":       200,
            "Why Member May Take This Drug": 240,
            "Possible ICD-10-CM Code 1":    90,
            "ICD-10 Description 1":        220,
            "HCC Category (ICD 1)":         90,
            "HCC Description (ICD 1)":     180,
            "Possible ICD-10-CM Code 2":    90,
            "ICD-10 Description 2":        220,
            "HCC Category (ICD 2)":         90,
            "Possible ICD-10-CM Code 3":    90,
            "ICD-10 Description 3":        220,
            "HCC Category (ICD 3)":         90,
            "Possible ICD-10-CM Code 4":    90,
            "ICD-10 Description 4":        220,
            "HCC Category (ICD 4)":         90,
            "High Value HCC Flag":         120,
            "Confidence Level":             80,
            "Manual Review Flag":           90,
            "Ambiguity Notes":             200,
            "Data Source":                 200,
        }

        for col in cols:
            width = col_widths.get(col, 120)
            self._tree.heading(col, text=col, anchor="w",
                               command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=width, minwidth=50, stretch=False)

        # Clear existing rows then insert
        for row_id in self._tree.get_children():
            self._tree.delete(row_id)

        hcc_col = "High Value HCC Flag"
        rev_col = "Manual Review Flag"

        for i, (_, row) in enumerate(df.iterrows()):
            def _safe(v):
                try:
                    return "" if pd.isna(v) else str(v)
                except (TypeError, ValueError):
                    return str(v)
            values  = [_safe(row.get(c, "")) for c in cols]
            hcc_val = str(row.get(hcc_col, ""))
            rev_val = str(row.get(rev_col, ""))

            if hcc_val.startswith("YES"):
                tag = "hcc"
            elif rev_val == "YES":
                tag = "review"
            elif i % 2 == 0:
                tag = "norm"
            else:
                tag = "alt"

            self._tree.insert("", "end", values=values, tags=(tag,))

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._apply_filters()

    # ─── Export ───────────────────────────────────────────────────────────────
    def _export_excel(self):
        if self._df_result is None:
            messagebox.showwarning("No Results", "Process a file first.")
            return
        init_dir = os.path.dirname(self._file_path) if self._file_path else os.path.expanduser("~")
        path = filedialog.asksaveasfilename(
            initialdir=init_dir,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            title="Save results as Excel",
        )
        if not path:
            return
        try:
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                self._df_result.to_excel(writer, sheet_name="Results", index=False)
                ws = writer.sheets["Results"]
                ws.freeze_panes = "A2"
                for col_cells in ws.columns:
                    max_len = max(
                        (len(str(c.value)) if c.value is not None else 0)
                        for c in col_cells
                    )
                    ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 55)
            messagebox.showinfo("Export Complete", f"Saved:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _export_tsv(self):
        if self._df_result is None:
            messagebox.showwarning("No Results", "Process a file first.")
            return
        init_dir = os.path.dirname(self._file_path) if self._file_path else os.path.expanduser("~")
        path = filedialog.asksaveasfilename(
            initialdir=init_dir,
            defaultextension=".txt",
            filetypes=[("Tab-delimited text", "*.txt")],
            title="Save results as tab-delimited text",
        )
        if not path:
            return
        try:
            self._df_result.to_csv(path, sep="\t", index=False)
            messagebox.showinfo("Export Complete", f"Saved:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _export_csv(self):
        if self._df_result is None:
            messagebox.showwarning("No Results", "Process a file first.")
            return
        init_dir = os.path.dirname(self._file_path) if self._file_path else os.path.expanduser("~")
        path = filedialog.asksaveasfilename(
            initialdir=init_dir,
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")],
            title="Save results as CSV",
        )
        if not path:
            return
        try:
            self._df_result.to_csv(path, index=False, encoding="utf-8")
            messagebox.showinfo("Export Complete", f"Saved:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))


# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()
