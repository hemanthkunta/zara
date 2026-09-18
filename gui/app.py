"""
ZARA Desktop GUI: Native desktop interface with live state visualization, chat, and tool observability.
Built with standard library tkinter for zero external GUI dependencies on macOS.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import sys
from pathlib import Path
from typing import Optional

from core.engine import ZaraEngine
from core.conversation import ConversationalSession
from modules.memory import MemoryStore
from core.recovery import RecoveryManager
from config.settings import RiskLevel

class ZaraDesktopApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ZARA — Autonomous Personal AI Agent")
        self.root.geometry("1100x750")
        self.root.configure(bg="#1e1e2e")

        self.engine = ZaraEngine(enable_voice=True, on_step_update=self._on_engine_step)
        self.session = ConversationalSession(self.engine)
        self.memory = MemoryStore()
        self.recovery = RecoveryManager()

        self._build_ui()

    def _build_ui(self):
        # 1. Header Frame
        header = tk.Frame(self.root, bg="#181825", height=60)
        header.pack(fill=tk.X, side=tk.TOP)

        title = tk.Label(
            header,
            text="ZARA • Autonomous Personal AI Engineering & Research Agent",
            font=("Helvetica", 16, "bold"),
            fg="#89b4fa",
            bg="#181825"
        )
        title.pack(side=tk.LEFT, padx=20, pady=12)

        self.status_label = tk.Label(
            header,
            text="● SYSTEM READY",
            font=("Helvetica", 12, "bold"),
            fg="#a6e3a1",
            bg="#181825"
        )
        self.status_label.pack(side=tk.RIGHT, padx=20, pady=12)

        # 2. Main Content Panes
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left Pane: Chat & Task Entry
        left_frame = tk.Frame(main_paned, bg="#1e1e2e")
        main_paned.add(left_frame, weight=1)

        chat_label = tk.Label(left_frame, text="Conversation & Task Input", font=("Helvetica", 12, "bold"), fg="#cdd6f4", bg="#1e1e2e")
        chat_label.pack(anchor=tk.W, pady=(0, 5))

        self.chat_display = scrolledtext.ScrolledText(
            left_frame,
            wrap=tk.WORD,
            bg="#11111b",
            fg="#cdd6f4",
            insertbackground="#89b4fa",
            font=("Monaco", 11)
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Input box
        input_frame = tk.Frame(left_frame, bg="#1e1e2e")
        input_frame.pack(fill=tk.X)

        self.entry = tk.Entry(input_frame, bg="#313244", fg="#cdd6f4", font=("Helvetica", 12), insertbackground="#89b4fa")
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=4)
        self.entry.bind("<Return>", lambda e: self._send_task())

        send_btn = tk.Button(input_frame, text="Send / Run", bg="#89b4fa", fg="#11111b", font=("Helvetica", 11, "bold"), command=self._send_task)
        send_btn.pack(side=tk.RIGHT)

        # Right Pane: Notebook with Pipeline, Tools, Memory, Checkpoints
        right_frame = tk.Frame(main_paned, bg="#1e1e2e")
        main_paned.add(right_frame, weight=1)

        notebook = ttk.Notebook(right_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Execution Pipeline & State
        tab_pipeline = tk.Frame(notebook, bg="#181825")
        notebook.add(tab_pipeline, text="State Machine Loop")
        self.pipeline_display = scrolledtext.ScrolledText(tab_pipeline, bg="#11111b", fg="#a6adc8", font=("Monaco", 11))
        self.pipeline_display.pack(fill=tk.BOTH, expand=True, pwheel=True if hasattr(scrolledtext, "pwheel") else 5)

        # Tab 2: Memory Log
        tab_memory = tk.Frame(notebook, bg="#181825")
        notebook.add(tab_memory, text="Memory Log")
        self.memory_display = scrolledtext.ScrolledText(tab_memory, bg="#11111b", fg="#a6adc8", font=("Monaco", 10))
        self.memory_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._refresh_memory()

        # Tab 3: Checkpoints & Recovery
        tab_recovery = tk.Frame(notebook, bg="#181825")
        notebook.add(tab_recovery, text="Checkpoints")
        self.checkpoints_display = scrolledtext.ScrolledText(tab_recovery, bg="#11111b", fg="#a6adc8", font=("Monaco", 10))
        self.checkpoints_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._refresh_checkpoints()

        # Welcome message in chat
        self.chat_display.insert(tk.END, "ZARA: Hello! I am ZARA, your autonomous personal engineering and research agent.\n")
        self.chat_display.insert(tk.END, "Enter a requirement or ask a question to begin.\n\n")

    def _send_task(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)

        self.chat_display.insert(tk.END, f"User: {text}\n")
        self.status_label.config(text="● EXECUTING TASK...", fg="#f9e2af")

        def worker():
            reply = self.session.process_user_input(text)
            self.root.after(0, lambda: self._on_task_completed(reply))

        threading.Thread(target=worker, daemon=True).start()

    def _on_task_completed(self, reply: str):
        self.chat_display.insert(tk.END, f"ZARA: {reply}\n\n")
        self.chat_display.see(tk.END)
        self.status_label.config(text="● SYSTEM READY", fg="#a6e3a1")
        self._refresh_memory()
        self._refresh_checkpoints()

    def _on_engine_step(self, stage: str, step):
        msg = f"[{stage}] Step {step.id}: {step.title}\n"
        if "VERIFY" in stage:
            msg += f"  Status: {step.status.value}\n"
        self.root.after(0, lambda: self._append_pipeline(msg))

    def _append_pipeline(self, msg: str):
        self.pipeline_display.insert(tk.END, msg)
        self.pipeline_display.see(tk.END)

    def _refresh_memory(self):
        self.memory_display.delete(1.0, tk.END)
        entries = self.memory.get_all_entries()
        for e in entries:
            self.memory_display.insert(tk.END, e + "\n" + "-"*50 + "\n")

    def _refresh_checkpoints(self):
        self.checkpoints_display.delete(1.0, tk.END)
        ckps = self.recovery.list_checkpoints()
        if not ckps:
            self.checkpoints_display.insert(tk.END, "No pending checkpoints. System clean.")
        for c in ckps:
            self.checkpoints_display.insert(tk.END, f"Task: {c['task']}\nStep: {c['current_step']}/{c['total_steps']}\nTime: {c['checkpoint_time']}\nFile: {c['file']}\n\n")

def launch_gui():
    root = tk.Tk()
    app = ZaraDesktopApp(root)
    root.mainloop()

if __name__ == "__main__":
    launch_gui()
