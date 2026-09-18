import os
import threading
import json
import sys

import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog
import ttkbootstrap as tb
from ttkbootstrap.constants import *

import base64
import mimetypes

from fpdf import FPDF

from dotenv import load_dotenv, set_key
from openrouter import OpenRouter

APP_DATA_DIR = os.path.expanduser(
    "~/Library/Application Support/ProjectGen"
)
os.makedirs(APP_DATA_DIR, exist_ok=True)

ENV_FILE = os.path.join(APP_DATA_DIR, ".env")

load_dotenv(ENV_FILE)


def resource_path(filename):
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)

def get_api_key():
    api_key = os.getenv("HACKCLUB_API_KEY")

    if api_key:
        return api_key.strip()

    temp_root = tk.Tk()
    temp_root.withdraw()

    api_key = simpledialog.askstring(
        "HackClub AI API Key Required",
        "No API key was found.\nPaste your HackClub AI API key below:",
        show="*",
        parent=temp_root
    )

    temp_root.destroy()

    if not api_key or not api_key.strip():
        messagebox.showerror("Missing API key", "ProjectGen needs a HackClub AI API key to work.")
        raise SystemExit("No API key provided.")

    api_key = api_key.strip()

    set_key(
        ENV_FILE,
        "HACKCLUB_API_KEY",
        api_key
    )

    os.environ["HACKCLUB_API_KEY"] = api_key
    return api_key

client = OpenRouter(
    api_key=get_api_key(),
    server_url="https://ai.hackclub.com/proxy/v1",
    timeout_ms=20000.0
)

SAVE_FILE = os.path.join(APP_DATA_DIR, "projectgen_session.json")

STATUS_MESSAGES = [
    "Brainstorming...",
    "Thinking...",
    "Pondering...",
    "Raiding the parts bin...",
    "Summoning ideas..."
]

def build_prompt(components: str, hours: str, budget: str, difficulty: str, project_type: str) -> str:
    if project_type == "Software":
        components_line = f"Programming language you'd like to use: {components}"
        budget_line = ""
    else:
        components_line = f"Components: {components}"
        budget_line = f"Budget to buy missing components: {budget}"

    return f"""
Give me 5 project ideas based on:

{components_line}
Time available: {hours} hours
{budget_line}
Difficulty level = {difficulty}
Project Type = {project_type}


Respond ONLY with a valid JSON array (no markdown fences, no extra text, no explanation before or after).
Each element must be an object with exactly these keys:
"name" (string), "description" (string, up to 3 sentsences),
"extra_components" (string), "cost" (string, in dollars), "time" (string), "difficulty" (string, /10)

Make sure every project fits the user's budget and time constraints.
"""

def build_project_prompt(project: dict, difficulty: str= "Intermediate") -> str:
    return f"""
Create a complete, beginner-friendly build guide for this project.

PROJECT:
Name: {project.get("name", "")}
Description: {project.get("description", "")}
Extra components: {project.get("extra_components", "")}
Estimated cost: {project.get("cost", "")}
Estimated time: {project.get("time", "")}
Difficulty level: {difficulty}

Respond ONLY with a valid JSON object (no markdown fences, no extra text, no explanation before or after)

The JSON must contain these keys:
- "project_name"
- "overview"
- "components"
- "wiring"
- "steps"
- "code"

Components must be an array of objects with "name" and "quantity".
Wiring must be an array of strings.
Steps must be an array of strings.
Code must be a string.

Be specific and practical. Include exact pin numbers, voltages,
connections, polarity, and other important technical details when needed.

Write the wiring like this: OLED VCC -> ESP32 3V3, not OLED VCC to ESP32 3V3

If code is not required, return an empty string for "code".
If wiring is not applicable, return an empty array [] for "wiring".

If difficulty = easy, make sure to comment more heavilly on the code and simplify the logic so it's easier to understand.

Do not include any other keys.
Do not use markdown fences or any text outside the JSON.
"""

def call_ai(prompt: str):
    response = client.chat.send(
        model="google/gemini-3.8-flash",
        messages=[
            {"role": "user", "content": prompt}
        ],
        stream=False,
    )

    raw = response.choices[0].message.content.strip()

    if raw.startswith("```"):
        raw = raw.removeprefix("```json")
        raw = raw.removeprefix("```")
        raw = raw.removesuffix("```")
        raw = raw.strip()

    result = json.loads(raw)

    return result

def encode_image(image_path):
    mime_type, _ = mimetypes.guess_type(image_path)

    if mime_type == None:
        mime_type = "image/jpeg"

    with open(image_path, "rb") as image_file:
        image_data = base64.b64encode(image_file.read()).decode("utf-8")

    return f"data:{mime_type};base64,{image_data}"
    
def call_ai_image(prompt: str, image_path: str):

    image_data = encode_image(image_path)
    response = client.chat.send(
        model="google/gemini-3.8-flash",
        messages=[
            {"role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"""
{prompt}
IMPORTANT:
The user uploaded an image showing their available hardware components.

Analyze the image carefully and identify the components visible in it.

Use the components you identify from the image as the user's available
components when generating the project ideas.

Do not treat "Image uploaded" as an actual component.

Only suggest projects that can reasonably be built using the components
you can identify in the image, while respecting the user's time, budget,
difficulty, and project type constraints.

If you are unsure about a component, do not invent a specific model.
Use a general description such as "microcontroller board" when appropriate.

Return ONLY the JSON array requested above.
"""            
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_data
                    }
                }
            ]}
        ],
        stream=False,
    )

    raw = response.choices[0].message.content.strip()

    if raw.startswith("```"):
        raw = raw.removeprefix("```json")
        raw = raw.removeprefix("```")
        raw = raw.removesuffix("```")
        raw = raw.strip()

    result = json.loads(raw)

    return result

def wrap_text_lines(pdf, text, max_width):
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        if pdf.get_string_width(word) > max_width:
            if current:
                lines.append(current)
                current = ""
            chunk = ""
            for ch in word:
                if pdf.get_string_width(chunk + ch) > max_width:
                    if chunk:
                        lines.append(chunk)
                    chunk = ch
                else:
                    chunk += ch
            current = chunk
        else:
            test = (current + " " + word).strip() if current else word
            if pdf.get_string_width(test) > max_width:
                if current:
                    lines.append(current)
                current = word
            else:
                current = test
    if current:
        lines.append(current)
    return lines if lines else [""]

def draw_wrapped(pdf, text, line_height=6, fill=False):
    max_width = pdf.w - pdf.l_margin - pdf.r_margin - (pdf.get_x() - pdf.l_margin)
    max_width = pdf.w - pdf.l_margin - pdf.r_margin
    for line in wrap_text_lines(pdf, str(text), max_width):
        pdf.cell(0, line_height, text=line, new_x="LMARGIN", new_y="NEXT", fill=fill)

def export_pdf(instructions: dict, filepath: str):
    project_name = instructions.get("project_name", "Unknown")
    overview = instructions.get("overview", "Unknown")
    components = instructions.get("components", [])
    wiring = instructions.get("wiring", [])
    steps = instructions.get("steps", [])
    code = instructions.get("code", "")

    pdf = FPDF()
    pdf.add_font("DejaVu", "", resource_path("DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", resource_path("DejaVuSans-Bold.ttf"))
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ----- title -----
    pdf.set_font("DejaVu", "B", 22)
    draw_wrapped(pdf, project_name, line_height=12)
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, text="Build Guide", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    def section_title(text):
        pdf.set_font("DejaVu", "B", 14)
        pdf.cell(0, 10, text=text, new_x="LMARGIN", new_y="NEXT") 
        pdf.set_draw_color(180, 180, 180)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() +190, pdf.get_y()) 
        pdf.ln(4)

    if overview:
        section_title("Overview")
        pdf.set_font("DejaVu", "", 11)
        draw_wrapped(pdf, str(overview))
        pdf.ln(4)

    if components:
        section_title("Components")
        pdf.set_font("DejaVu", "", 11)
        if isinstance(components, list):
            for component in components:
                if isinstance(component, dict):
                    name = component.get("name", "Unknown")
                    quantity = component.get("quantity", 1)
                    line = f"- {name}  x{quantity}"
                else:
                    line = f"- {component}"
                draw_wrapped(pdf, line)
        else:
            draw_wrapped(pdf, str(components))
        pdf.ln(4)

    
    if wiring:
        section_title("Wiring")
        pdf.set_font("DejaVu", "", 11)
        if isinstance(wiring, list):
            for connection in wiring:
                    connection = str(connection).strip()
                    if connection.startswith("{") and connection.endswith("}"):
                        connection = connection[1:-1].strip()
                    connection = connection.strip("'\"")
                    draw_wrapped(pdf, f"- {connection}")
        else:       
            draw_wrapped(pdf, str(wiring))
        pdf.ln(4)

    if steps:
        section_title("Build Steps")
        if isinstance(steps, list):
            for i, step in enumerate(steps, 1):
                pdf.set_font("DejaVu", "B", 11)
                pdf.cell(10, 6, text=f"{i}. ")
                pdf.set_font("DejaVu", "", 11)
                draw_wrapped(pdf, str(step))
                pdf.ln(1)
        pdf.ln(3)       

    if code:
        section_title("Code")
        pdf.set_font("DejaVu", "", 9)
        pdf.set_fill_color(245, 245, 245)
        for line in str(code).split("\n"):
            draw_wrapped(pdf, line if line else " ", line_height=5, fill=True)

    pdf.output(filepath)

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ProjectGen - Powered by HackAi")
        self.root.geometry("650x650")
        self.root.minsize(500, 500)

        self.BG = "#F4F1DE"           
        self.HEADER = "#556B2F"        
        self.CARD = "#E7EDC9"         
        self.CARD_BORDER = "#6B8E23"
        self.TEXT = "#283618"  
        self.ACCENT = "#386641"   
        self.WHITE = "#FFFFFF"
        self.SECONDARY_TEXT = "#606C38" 
        self.META_TEXT = "#4F5D2F"       
        self.ERROR = "#BC4749"       

        self.root.configure(bg=self.BG)

        self.style = tb.Style()
        self.style.configure("Header.TFrame", background=self.HEADER)
        self.style.configure("Header.TLabel", background=self.HEADER, foreground=self.WHITE)
        self.style.configure("Body.TFrame", background=self.BG)
        self.style.configure("Body.TLabel", background=self.BG, foreground=self.TEXT)
        self.style.configure("Status.TLabel", background=self.BG, foreground=self.CARD_BORDER)
        self.style.configure("StatusError.TLabel", background=self.BG, foreground=self.ERROR)
        self.style.configure("Card.TFrame", background=self.CARD)
        self.style.configure("CardTitle.TLabel", background=self.CARD, foreground=self.CARD_BORDER, font=("Arial", 12, "bold"))
        self.style.configure("CardDesc.TLabel", background=self.CARD, foreground=self.TEXT, font=("Arial", 10))
        self.style.configure("CardExtra.TLabel", background=self.CARD, foreground=self.SECONDARY_TEXT, font=("Arial", 9))
        self.style.configure("CardMeta.TLabel", background=self.CARD, foreground=self.META_TEXT, font=("Arial", 9))
        self.style.configure("TitleCard.TFrame", background=self.HEADER)
        self.style.configure("TitleCard.TLabel", background=self.HEADER, foreground=self.WHITE)
        self.style.configure("Section.TLabelframe", background=self.CARD, bordercolor=self.CARD_BORDER)
        self.style.configure("Section.TLabelframe.Label", background=self.CARD, foreground=self.CARD_BORDER, font=("Arial", 11, "bold"))
        self.style.configure("StepBadge.TFrame", background=self.ACCENT)
        self.style.configure("StepBadge.TLabel", background=self.ACCENT, foreground=self.WHITE)

        self._status_index = 0
        self._spinning = False
        self._last_ideas = []
        self._build_request_id = 0
        self._instructions_cache = {}
        self.image_path = None

        self.build_widgets()

        if self._has_saved_session():
            self.root.after(100, self._prompt_load_session)

    def upload_image(self):
        image_path = filedialog.askopenfilename(
            title="Select an image",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.webp"),
                ("All files", "*.*")
            ]
        )
        if image_path:
            self.components_entry.config(state="normal")
            self.components_entry.delete(0, "end")
            self.components_entry.insert(0, "Image uploaded")
            self.components_entry.config(state="readonly")
            self.image_path = image_path
            self.clear_image_btn.pack(side="left", padx=(6, 0))

    def clear_image(self):
        self.components_entry.config(state="normal")
        self.components_entry.delete(0, "end")
        self.image_path = None
        self.clear_image_btn.pack_forget()
            
    def on_components_changed(self, event=None):
        if self.components_entry.get().strip() != "Image uploaded":
            self.image_path = None

    def build_widgets(self):

        self.header = tb.Frame(self.root, style="Header.TFrame")
        self.header.pack(fill ="x")

        title = tb.Label(
            self.header,
            text="ProjectGen",
            font=("Arial", 24, "bold"),
            style="Header.TLabel",
        )
        title.pack(pady=(10, 2))

        subtitle = tb.Label(
            self.header,
            text="Powered by HackAi",
            font=("Arial", 11),
            style="Header.TLabel",
        )
        subtitle.pack(pady=(0, 10))

        self.input_frame = tb.Frame(self.root, style="Body.TFrame")
        self.input_frame.pack(fill="x")

        pad = {"padx": 10, "pady": (10, 0)}

        tb.Label(
            self.input_frame,
            text="Project Type:",
            style="Body.TLabel"
        ).pack(anchor="w", **pad)
        
        self.project_type_combobox = tb.Combobox(
            self.input_frame,
            bootstyle=SUCCESS,
            values=[
                "Hardware",
                "Software"
            ],
            state="readonly"
        )
        self.project_type_combobox.pack(padx=10, fill="x")
        self.project_type_combobox.set("Hardware")

        self.project_type_combobox.bind("<<ComboboxSelected>>", self._on_project_type_change)

        tb.Label(
            self.input_frame,
            text="Difficulty level:",
            style="Body.TLabel"
        ).pack(anchor="w", **pad)
        self.difficulty_combobox = tb.Combobox(
            self.input_frame,
            bootstyle=SUCCESS,
            values=[
                "Easy",
                "Intermediate",
                "Difficult"
            ],
            state="readonly"
        )
        self.difficulty_combobox.pack(padx=10, fill="x")
        self.difficulty_combobox.set("Intermediate")

        self.components_label = tb.Label(
            self.input_frame, 
            text="Components you have (comma-separated):",
            style="Body.TLabel"
        )
        self.components_label.pack(anchor="w", **pad)
        self.components_frame = tb.Frame(
            self.input_frame,
            style="Body.TFrame"
        )
        self.components_frame.pack(fill="x", padx=10)

        self.components_entry = tb.Entry(
            self.components_frame
        )
        self.components_entry.pack(side="left", fill="x", expand=True)
        self.components_entry.bind("<KeyRelease>", self.on_components_changed)

        self.or_label = tb.Label(
            self.components_frame,
            text="or",
            style="Body.TLabel"
        )
        self.or_label.pack(side="left", padx=8)

        self.upload_image_btn = tb.Button(
            self.components_frame,
            text="Upload image",
            bootstyle=SECONDARY,
            command=self.upload_image
        )
        self.upload_image_btn.pack(side="left")

        self.clear_image_btn = tb.Button(
            self.components_frame,
            text="x",
            bootstyle="danger-outline",
            command=self.clear_image,
            width=3
        )

        tb.Label(
            self.input_frame, 
            text="Hours available:",
            style="Body.TLabel",
        ).pack(anchor="w", **pad)
        self.hours_entry = tb.Entry(
            self.input_frame,
            width=20,
        )
        self.hours_entry.pack(padx=10, fill="x")

        self.budget_label = tb.Label(
            self.input_frame, 
            text="Budget ($):",
            style="Body.TLabel",
        )
        self.budget_label.pack(anchor="w", **pad)
        self.budget_entry = tb.Entry(
            self.input_frame,
            width=20,
        )
        self.budget_entry.pack(padx=10, fill="x") 

        self.generate_btn = tb.Button(
            self.input_frame, 
            text="Generate ideas!", 
            bootstyle=SUCCESS,
            command=self.on_generate
        )
        self.generate_btn.pack(pady=15)

        self.back_btn = tb.Button(
            self.root,
            text="← Back to ideas",
            bootstyle=SECONDARY,
            command=self.on_back
        )

        self.status_label = tb.Label(
            self.root, 
            text="", 
            style="Status.TLabel",
        )
        self.status_label.pack()

        self.progress = tb.Progressbar(self.root, mode="indeterminate", bootstyle=SUCCESS)

        frame = tb.Frame(self.root, style="Body.TFrame")
        frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            frame,
            bg=self.BG,
            highlightthickness=0
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tb.Frame(
            self.canvas,
            style="Body.TFrame",
        )
        
        scrollbar = tb.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")

        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.cards_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")

        self.cards_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self.canvas.bind("<Configure>", self._resize_cards)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_project_type_change(self, event=None):
        project_type = self.project_type_combobox.get().strip()

        if project_type == "Software":
            self.components_label.config(text="Programming language you'd like to use:")

            self.or_label.pack_forget()
            self.upload_image_btn.pack_forget()

            self.budget_label.pack_forget()
            self.budget_entry.pack_forget()

            self.components_entry.config(state="normal")
            self.components_entry.delete(0, "end")
            self.clear_image_btn.pack_forget()

            self.image_path = None
        else: 
            self.components_label.config(text="Components you have (comma-separated):")

            self.or_label.pack(side="left", padx=8)
            self.upload_image_btn.pack(side="left")

            self.budget_label.pack(anchor="w", padx=10, pady=(10, 0), before=self.generate_btn)
            self.budget_entry.pack(padx=10, fill="x", before=self.generate_btn)            

    def on_generate(self):
        self.status_label.config(text="", style="Status.TLabel")

        components = self.components_entry.get().strip()
        project_type = self.project_type_combobox.get().strip()
        hours = self.hours_entry.get().strip()
        budget = self.budget_entry.get().strip() if project_type == "Hardware" else ""
        difficulty = self.difficulty_combobox.get().strip()

        required_fields = [hours, difficulty, project_type]

        if not all(required_fields):
            messagebox.showwarning(
                "Missing info",
                "Please fill in all the required fields."
            )
            return

        if project_type == "Hardware" and not components and not self.image_path:
            messagebox.showwarning(
                "Missing info",
                "Please enter your components or upload an image of them."
            )
            return

        if project_type == "Software" and not components:
            messagebox.showwarning(
                "Missing info",
                "Please enter a programming language."
            )
            return

        self._set_btn_enabled(False)
        self._clean_cards()
        self._spinning = True
        self._animate_status()

        self.progress.pack(fill="x", padx=10, pady=(0, 5))
        self.progress.start(10)

        prompt = build_prompt(components, hours, budget, difficulty, project_type)

        def worker():
            try:
                if self.image_path:
                    ideas = call_ai_image(prompt, self.image_path)
                else:
                    ideas = call_ai(prompt)
                    
                if not isinstance(ideas, list):
                    raise ValueError("AI didn't return a JSON array.")
                error = None                
            except Exception as e:
                error = f"Something went wrong:\n{e}"
                ideas = None
            self.root.after(0, lambda: self._on_done(ideas, error))

        threading.Thread(target=worker, daemon=True).start()

    def build_project(self, project):
        self.input_frame.pack_forget()
        self.header.pack_forget()
        self.back_btn.pack(pady=(10, 0))

        self.status_label.config(text="", style="Status.TLabel")

        difficulty = self.difficulty_combobox.get().strip()
        project_key = f"{project.get('name', '')}|{difficulty}"

        if project_key in self._instructions_cache:
            self._render_instructions(self._instructions_cache[project_key])
            return

        self._clean_cards()
        self._spinning = True
        self._animate_status()

        self.progress.pack(fill="x", padx=10, pady=(0, 5))
        self.progress.start(10)

        self._build_request_id += 1
        request_id = self._build_request_id

        prompt2 = build_project_prompt(project, difficulty)

        def worker2():
            try:
                instructions = call_ai(prompt2)
                if not isinstance(instructions, dict):
                    raise ValueError("Ai didn't return a JSON object.")
                error = None
            except Exception as e:
                error = f"Something went wrong:\n{e}"
                instructions = None
            self.root.after(0, lambda: self._on_build_done(instructions, error, request_id, project_key))
        threading.Thread(target=worker2, daemon=True).start()
        
    def on_back(self):
        self._build_request_id += 1

        self._spinning = False
        self.status_label.config(text="")
        self.progress.stop()
        self.progress.pack_forget()

        self.back_btn.pack_forget()
        self.input_frame.pack(fill="x", before=self.status_label)
        self.header.pack(fill="x", before=self.input_frame)

        self._render_cards(self._last_ideas)

    def _resize_cards(self, event):
        self.canvas.itemconfig(self.cards_window, width=event.width)
        self._update_card_wraps(event.width)

    def _update_card_wraps(self, width):
        wrap_width = max(200, width - 50)

        for widget in self.cards_frame.winfo_children():
            self._resize_widget_text(widget, wrap_width)

    def _resize_widget_text(self, widget, wrap_width):
        try:
            if isinstance(widget, (tk.Label, tb.Label)):
                widget.configure(wraplength=wrap_width)
        except:
            pass

        for child in widget.winfo_children():
            self._resize_widget_text(child, wrap_width)

    def _clean_cards(self):
        for widget in self.cards_frame.winfo_children():
            widget.destroy()

    def _render_cards(self, ideas):
        self._clean_cards()

        if not ideas:
            tb.Label(self.cards_frame, text= "No ideas returned.").pack(pady=10)
            return
        
        for project in ideas:
            name = project.get("name", "Untitled Project")
            description = project.get("description", "")
            extra = project.get("extra_components", "None")
            cost = project.get("cost", "Unknown")
            time = project.get("time", "Unknown")
            difficulty = project.get("difficulty", "Unknown")

            card = tb.Frame(
                self.cards_frame,
                style="Card.TFrame"
            )
            card.pack(fill = "x", padx=8, pady=6)

            title = tb.Label(
                card, 
                style="CardTitle.TLabel",
                text=name, 
                anchor="w", 
                justify="left"
            )
            title.pack(fill="x", padx=10, pady=(8, 2))

            desc_label = tb.Label(
                card, 
                style="CardDesc.TLabel",
                text=description, 
                anchor="w", 
                justify="left"
            )
            desc_label.pack(fill="x", padx=10, pady=(0, 6))

            extra_label = tb.Label(
                card,
                style="CardExtra.TLabel",
                text=f"Extra components: {extra}", 
                anchor="w", 
                justify="left"
            )
            extra_label.pack(fill="x", padx=10, pady=(0, 2))

            meta_label = tb.Label(
                card, 
                style="CardMeta.TLabel",
                text=f"Cost = {cost}   |   Time = {time}   |   Difficulty = {difficulty}", 
                anchor="w"
            )
            meta_label.pack(fill="x", padx=10, pady=(0, 8))

            build_button = tb.Button(
                card,
                text="Build this!", 
                bootstyle=SUCCESS,
                command=lambda p=project: self.build_project(p)
            )
            build_button.pack(fill="x", padx=10, pady=(0, 8))

            def resize(event, d=desc_label, e=extra_label):
                wrap = max(150, event.width - 20)
                d.config(wraplength=wrap)
                e.config(wraplength=wrap)

            card.bind("<Configure>", resize)

    def _render_instructions(self, instructions):
        self._clean_cards()

        if not instructions:
            tb.Label(self.cards_frame, text= "No build instructions returned.", style="Body.TLabel").pack(pady=10)
            return

        project_name = instructions.get("project_name", "Unknown")
        overview = instructions.get("overview", "Unknown")
        components = instructions.get("components", [])
        wiring = instructions.get("wiring", [])
        steps = instructions.get("steps", [])
        code = instructions.get("code", "")

        # ----- title -----
        title_card = tb.Frame(self.cards_frame, style="TitleCard.TFrame", padding=20)
        title_card.pack(fill="x", padx=10, pady=(10, 8))

        tb.Label(
            title_card,
            text=project_name,
            font=("Arial", 24, "bold"),
            style="TitleCard.TLabel"
        ).pack(fill="x", anchor="w")

        tb.Label(
            title_card,
            text="Build Guide",
            font=("Arial", 11),
            style="TitleCard.TLabel"
        ).pack(fill="x", anchor="w", pady=(3, 0))  

        pdf_btn = tb.Button(title_card, text="Export as PDF", bootstyle=SUCCESS, command=lambda: self._export_pdf(instructions))
        pdf_btn.pack(anchor="w", pady=(10, 0))

        # ----- overview -----      
        overview_card = tb.Labelframe(self.cards_frame, text="  Overview  ", padding=15, style="Section.TLabelframe")
        overview_card.pack(fill="x", padx=10, pady=8)

        tb.Label(
            overview_card,
            text=overview,
            font=("Arial", 11),
            wraplength=600,
            justify="left"
        ).pack(fill="x", anchor="w")

        # ----- components ----- 

        components_card = tb.Labelframe(self.cards_frame, text="  Components  ", padding=15, style="Section.TLabelframe")
        components_card.pack(fill="x", padx=10, pady=8)

        components_grid = tb.Frame(components_card)
        components_grid.pack(fill="x")

        if isinstance(components, list):
            for i, component in enumerate(components):
                if isinstance(component, dict):
                    name = component.get("name", "Unknown")
                    quantity = component.get("quantity", 1)
                    text = f"• {name}  ×{quantity}"
                else:
                    text = f"• {component}"

                tb.Label(
                    components_grid, 
                    text=text, 
                    font=("Arial", 10)
                ).grid(
                    row=i // 2, 
                    column=i % 2, 
                    sticky="w", 
                    padx=10, 
                    pady=5
                )
        else:
            tb.Label(
                components_grid,
                text=str(components)
            ).pack(anchor="w")

        # ----- wiring -----
        if wiring:
            wiring_card = tb.Labelframe(self.cards_frame, text="  Wiring  ", padding=15, style="Section.TLabelframe")
            wiring_card.pack(fill="x", padx=10, pady=8)

            if isinstance(wiring, list):
                for connection in wiring:
                    connection = str(connection).strip()

                    if connection.startswith("{") and connection.endswith("}"):
                        connection = connection[1:-1].strip()

                    connection = connection.strip("'\"")

                    tb.Label(
                        wiring_card,
                        text=f"• {connection}",
                        font=("Arial", 10),
                        wraplength=600,
                        justify="left"
                    ).pack(fill="x", anchor="w", pady=4)
            else:
                tb.Label(
                    wiring_card,
                    text=str(wiring),
                    font=("Arial", 10),
                    wraplength=600,
                    justify="left"
                ).pack(fill="x", anchor="w")

        # ----- steps -----

        steps_card = tb.Labelframe(self.cards_frame, text="  Build Steps  ", padding=15, style="Section.TLabelframe")
        steps_card.pack(fill="x", padx=10, pady=8)

        if isinstance(steps, list):
            for i, step in enumerate(steps, 1):
                step_frame = tb.Frame(
                    steps_card,
                    padding=10,
                    style="StepBadge.TFrame"
                )
                step_frame.pack(fill="x", pady=5)

                tb.Label(
                    step_frame,
                    text=str(i),
                    font=("Arial", 14, "bold"),
                    width=3,
                    style="StepBadge.TLabel"
                ).pack(side="left", padx=(0, 12))

                tb.Label(
                    step_frame,
                    text=str(step),
                    font=("Arial", 10),
                    wraplength=600,
                    justify="left"
                ).pack(side="left", fill="x", expand=True)

        # ----- code -----

        if code:
            copytext = "Copy code"

            code_card = tb.Labelframe(self.cards_frame, text="  Code  ", padding=15, style="Section.TLabelframe")
            code_card.pack(fill="x", padx=10, pady=8)

            code_btn = tb.Button(code_card, text=copytext, bootstyle=SUCCESS, command=lambda: self._copy_code(code))
            code_btn.pack(fill="x", pady=(0, 8))

            code_box = tk.Text(code_card, height=15, font=("Menlo", 10), wrap="none", relief="flat")
            code_box.pack(fill="both", expand=True)

            code_box.insert("1.0", code)
            code_box.config(state="disabled")
        self.canvas.yview_moveto(0)

    def _copy_code(self, code):
        self.root.clipboard_clear()
        self.root.clipboard_append(code)

    def _export_pdf(self, instructions):
        default_name = instructions.get("project_name", "build_guide").replace(" ", "_")
        filepath = filedialog.asksaveasfilename(
            title="Save PDF",
            defaultextension=".pdf",
            initialfile=f"{default_name}.pdf",
            filetypes=[("PDF files", "*.pdf")]
        )
        print("Chosen filepath:", repr(filepath))
        if not filepath:
            return
        
        def worker():
            try:
                export_pdf(instructions, filepath)
                self.root.after(0, lambda: messagebox.showinfo("Exported", f"Build guide saved to:\n{filepath}"))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.root.after(0, lambda e=e: messagebox.showerror("Export failed", f"Something went wrong:\n{e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _set_btn_enabled(self, enabled: bool):
        self.generate_btn.config(state="normal" if enabled else "disabled")

    def _animate_status(self):
        if not self._spinning:
            self.status_label.config(text="")
            return
        msg = STATUS_MESSAGES[self._status_index % len(STATUS_MESSAGES)]
        self.status_label.config(text=msg)
        self._status_index += 1
        self.root.after(1500, self._animate_status)

    def _on_done(self, ideas: list, error=None):
        self._spinning = False
        self.status_label.config(text="")
        self._set_btn_enabled(True)

        self.progress.stop()
        self.progress.pack_forget()

        if error:
            self.status_label.config(text=error, style="StatusError.TLabel")
            return

        self._last_ideas = ideas
        self._save_session()
        self._render_cards(ideas)  

    def _on_build_done(self, instructions, error=None, request_id=None, project_key=None):
        if request_id != self._build_request_id:
            return
        
        self._spinning = False
        self.status_label.config(text="")
        self.progress.stop()
        self.progress.pack_forget()

        if error:
            self.status_label.config(text=error, style="StatusError.TLabel")
            return

        if project_key is not None:
            self._instructions_cache[project_key] = instructions
            self._save_session()

        self._render_instructions(instructions)

    def _has_saved_session(self):
        if not os.path.exists(SAVE_FILE):
            return False
        try:
            return os.path.getsize(SAVE_FILE) > 0
        except OSError:
            return False

    def _load_previous_session(self):
        try:
            with open(SAVE_FILE, "r") as f:
                data = json.load(f)
            self._last_ideas = data.get("last_ideas", [])
            self._instructions_cache = data.get("instructions_cache", {})
            self._render_cards(self._last_ideas)
        except (json.JSONDecodeError, OSError):
            self._last_ideas = []
            self._instructions_cache = {}

    def _save_session(self):
        data = {
            "last_ideas": self._last_ideas,
            "instructions_cache": self._instructions_cache
        }
        try:
            with open(SAVE_FILE, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _prompt_load_session(self):
        if messagebox.askyesno(
            "Load previous session?",
            "We found ideas from last time. Load them?"
        ):
            self._load_previous_session()
        else:
            self._last_ideas = []

    def set_dock_icon():
        try:
            from AppKit import NSApplication, NSImage
            icon_path = resource_path("ProjectGen.icns")
            app = NSApplication.sharedApplication()
            image = NSImage.alloc().initWithContentsOfFile_(icon_path)
            if image is not None:
                app.setApplicationIconImage_(image)
        except Exception:
            import traceback
            traceback.print_exc()
    
    def keep_dock_icon_fresh(root):
    # Tk overwrites the dock icon with its own default at some point after launch (timing varies). Reassert ours periodically to compensate.
        set_dock_icon()
        root.after(2000, lambda: keep_dock_icon_fresh(root))

if __name__ == "__main__":
    root = tb.Window(themename="cosmo")
    keep_dock_icon_fresh(root)
    app = App(root)
    root.mainloop()