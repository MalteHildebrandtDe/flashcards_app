"""
*************************************************************************
* Title: app.py                                                          *
* Description: Desktop flashcard app for Markdown-based Q&A.             *
* Author: Malte Hildebrandt                                              *
*                                                                        *
* Input:                                                                 *
* - Markdown deck with headings **Frage/Question X** and answers under   *
*   **Antwort/Answer:**.                                                 *
*                                                                        *
* Output:                                                                *
* - GUI for learning; progress JSON saved next to the chosen deck.       *
*                                                                        *
* Purpose:                                                               *
* - Parse question/answer blocks from Markdown and present via Tkinter.  *
* - Apply light spaced-repetition weighting (wrong answers show up more).* 
* - Persist per-question progress JSON next to the chosen Markdown file. *
*                                                                        *
* Usage:                                                                 *
* - Run `python app.py /path/to/questions.md` or pick a file via dialog.  *
*************************************************************************
"""
from __future__ import annotations

import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import tkinter as tk
from tkinter import filedialog, messagebox

QUESTION_PATTERN = re.compile(r"\*\*(?:Frage|Question)\s+([^*]+)\*\*", re.IGNORECASE)
ANSWER_SPLIT_PATTERN = re.compile(r"\*\*(?:Antwort|Answer):?\*\*|(?:Antwort|Answer):", re.IGNORECASE)
PROGRESS_FILENAME = ".flashcards_progress.json"
CONFIG_PATH = Path.home() / ".flashcards_app_config.json"


@dataclass
class Card:
    card_id: str
    question: str
    answer: str


def parse_markdown(md_path: Path) -> List[Card]:
    """
    Load the markdown deck and extract all cards.

    Args:
        md_path: Path to the markdown file containing the deck.

    Returns:
        List of Card objects with id, question, and answer.
    Raises:
        ValueError: If no questions are found.
    """
    # Parse all question/answer blocks from the markdown deck.
    text = md_path.read_text(encoding="utf-8")
    matches = list(QUESTION_PATTERN.finditer(text))
    if not matches:
        raise ValueError("No questions found in the markdown (expected **Frage X** or **Question X**).")

    cards: List[Card] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()

        after_header = block.splitlines()[1:]  # skip the **Frage ...** line
        content = "\n".join(after_header).strip()
        parts = ANSWER_SPLIT_PATTERN.split(content, maxsplit=1)
        if len(parts) == 2:
            question_text, answer_text = parts[0].strip(), parts[1].strip()
        else:
            question_text, answer_text = content, "No answer provided."

        answer_text = clean_answer(answer_text)

        card_id = match.group(1).strip()
        cards.append(Card(card_id=card_id, question=question_text, answer=answer_text))

    return cards


def clean_answer(answer_text: str) -> str:
    """
    Trim answer text so that subsequent headings or separators are not shown.

    Rules:
    - Stop before any markdown heading line (starts with '#').
    - Drop trailing horizontal rules ('---').
    - Strip surrounding whitespace.
    """
    lines = answer_text.splitlines()
    cleaned: List[str] = []
    for line in lines:
        if re.match(r"^\s*#", line):
            break
        if line.strip() == "---":
            break
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def progress_path_for(md_path: Path) -> Path:
    """
    Compute the progress JSON path for a given deck.

    Args:
        md_path: Path to the markdown deck.

    Returns:
        Path to `.flashcards_progress.json` next to the deck.
    """
    # Store progress JSON next to the deck.
    return md_path.parent / PROGRESS_FILENAME


def load_progress(path: Path) -> Dict[str, Dict[str, int]]:
    """
    Load per-card progress from JSON.

    Args:
        path: Path to the progress file.

    Returns:
        Dict mapping card_id to {"correct", "incorrect"}; empty on failure.
    """
    # Return empty progress if file missing or broken.
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("questions", {}) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_progress(path: Path, progress: Dict[str, Dict[str, int]]) -> None:
    """
    Persist per-card progress to JSON.

    Args:
        path: Target JSON path.
        progress: Dict with per-card stats.
    """
    payload = {"questions": progress}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_config() -> Dict[str, str]:
    """
    Load global config (e.g., last opened deck).

    Returns:
        Dict with config keys; empty on failure.
    """
    # Remember last opened deck globally (~/.flashcards_app_config.json).
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(md_path: Path) -> None:
    """
    Store the last opened deck path.

    Args:
        md_path: Path to the last used deck.
    """
    # Persist path to last used deck.
    CONFIG_PATH.write_text(json.dumps({"last_md_path": str(md_path)}, indent=2), encoding="utf-8")


def weight_for(card: Card, progress: Dict[str, Dict[str, int]]) -> int:
    """
    Compute draw weight for a card based on past answers.

    Args:
        card: Card to score.
        progress: Dict with per-card stats.

    Returns:
        Weight (>=1); unseen cards highest (~10), frequently wrong cards also high (~5-8),
        cards with more attempts get lower weight even if ratio is equal.
    """
    stats = progress.get(card.card_id, {"correct": 0, "incorrect": 0})
    incorrect = stats.get("incorrect", 0)
    correct = stats.get("correct", 0)
    
    # Prioritize unseen cards heavily
    if correct == 0 and incorrect == 0:
        return 10
    
    # Base weight from net errors (more wrong = higher)
    net_errors = incorrect - correct
    base_weight = 5 + net_errors
    
    # Reduce weight as total attempts increase (confidence grows)
    total_attempts = correct + incorrect
    confidence_factor = 1.0 / (1.0 + total_attempts * 0.15)
    adjusted_weight = base_weight * confidence_factor
    
    return max(1, int(adjusted_weight))


def choose_card(cards: List[Card], progress: Dict[str, Dict[str, int]]) -> Card:
    """
    Draw a card using current weights.

    Args:
        cards: All available cards.
        progress: Dict with per-card stats.

    Returns:
        One Card sampled with weights.
    """
    # Weighted random draw per current stats.
    weights = [weight_for(card, progress) for card in cards]
    return random.choices(cards, weights=weights, k=1)[0]


class FlashcardApp:
    """
    GUI controller for the flashcard app.

    Args:
        md_path: Path to the markdown deck to load.

    Responsibilities:
    - load cards and progress
    - build/bind the Tkinter UI
    - handle answer reveal and grading
    - persist progress after each answer
    """
    def __init__(self, md_path: Path) -> None:
        """
        Initialize state, load deck/progress, and build the UI.

        Args:
            md_path: Path to the markdown deck.
        """
        self.md_path = md_path
        self.cards = parse_markdown(md_path)
        self.progress_path = progress_path_for(md_path)
        self.progress = load_progress(self.progress_path)

        self.current: Card | None = None
        self.answer_visible = False
        self.previous_id: str | None = None
        self.zoom_factor: float = 1.0

        self.root = tk.Tk()
        self.root.title("Flashcards")
        self.root.geometry("900x600")
        self.root.configure(padx=16, pady=16)

        self.build_ui()
        self.bind_keys()
        self.next_card()

    def build_ui(self) -> None:
        """
        Construct labels, buttons, and layout for the main window.
        """
        self.header_label = tk.Label(self.root, text=str(self.md_path), font=("Helvetica", 10), fg="#444")
        self.header_label.pack(anchor="w")

        self.card_id_label = tk.Label(self.root, text="", font=("Helvetica", 14, "bold"))
        self.card_id_label.pack(anchor="w", pady=(12, 4))

        self.question_label = tk.Label(self.root, text="", wraplength=850, justify="left", font=("Helvetica", 13))
        self.question_label.pack(anchor="w", pady=(0, 12))

        self.answer_label = tk.Label(self.root, text="", wraplength=850, justify="left", font=("Helvetica", 12), fg="#0bb66e")
        self.answer_label.pack(anchor="w", pady=(0, 12))

        self.status_label = tk.Label(self.root, text="", font=("Helvetica", 10))
        self.status_label.pack(anchor="w", pady=(4, 8))

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(anchor="w", pady=(8, 0))

        self.show_btn = tk.Button(btn_frame, text="Show answer (Enter/Space)", command=self.show_answer)
        self.show_btn.grid(row=0, column=0, padx=(0, 8))

        self.correct_btn = tk.Button(btn_frame, text="Correct", command=self.mark_correct)
        self.correct_btn.grid(row=0, column=1, padx=(0, 8))

        self.incorrect_btn = tk.Button(btn_frame, text="Wrong", command=self.mark_incorrect)
        self.incorrect_btn.grid(row=0, column=2)

        self.help_label = tk.Label(
            self.root,
            text=(
                "Keyboard shortcuts:\n"
                "  • Enter / Space  →  Show answer\n"
                "  • Right arrow (→)  →  Mark correct\n"
                "  • Left arrow (←)  →  Mark wrong\n"
                "  • Ctrl +/-  →  Zoom in/out\n"
                "  • Ctrl 0  →  Reset zoom"
            ),
            font=("Helvetica", 9),
            fg="#555",
            justify="left",
        )
        self.help_label.pack(anchor="w", pady=(10, 0))

    def bind_keys(self) -> None:
        """
        Bind keyboard shortcuts for answer reveal, grading, and zoom.
        """
        self.root.bind("<Return>", lambda _event: self.show_answer())
        self.root.bind("<space>", lambda _event: self.show_answer())
        self.root.bind("<Right>", lambda _event: self.mark_correct())
        self.root.bind("<Left>", lambda _event: self.mark_incorrect())
        
        # Zoom bindings
        self.root.bind("<Control-plus>", lambda _event: self.zoom_in())
        self.root.bind("<Control-equal>", lambda _event: self.zoom_in())  # Ctrl+= (same key as +)
        self.root.bind("<Control-minus>", lambda _event: self.zoom_out())
        self.root.bind("<Control-0>", lambda _event: self.zoom_reset())

    def zoom_in(self) -> None:
        """Increase zoom factor by 10% up to 1.5x."""
        self.zoom_factor = min(1.5, self.zoom_factor + 0.1)
        self.apply_zoom()

    def zoom_out(self) -> None:
        """Decrease zoom factor by 10% down to 0.7x."""
        self.zoom_factor = max(0.7, self.zoom_factor - 0.1)
        self.apply_zoom()

    def zoom_reset(self) -> None:
        """Reset zoom to 100%."""
        self.zoom_factor = 1.0
        self.apply_zoom()

    def apply_zoom(self) -> None:
        """Update all font sizes and widget dimensions based on current zoom factor."""
        z = self.zoom_factor
        
        # Update fonts
        self.header_label.config(font=("Helvetica", int(10 * z)))
        self.card_id_label.config(font=("Helvetica", int(14 * z), "bold"))
        self.question_label.config(font=("Helvetica", int(13 * z)), wraplength=int(850 * z))
        self.answer_label.config(font=("Helvetica", int(12 * z)), wraplength=int(850 * z))
        self.status_label.config(font=("Helvetica", int(10 * z)))
        self.show_btn.config(font=("Helvetica", int(10 * z)))
        self.correct_btn.config(font=("Helvetica", int(10 * z)))
        self.incorrect_btn.config(font=("Helvetica", int(10 * z)))
        self.help_label.config(font=("Helvetica", int(9 * z)))
        
        # Update window geometry
        new_width = int(900 * z)
        new_height = int(600 * z)
        self.root.geometry(f"{new_width}x{new_height}")

    def show_answer(self) -> None:
        """
        Reveal the answer for the current card and refresh status.
        """
        if not self.current:
            return
        self.answer_label.config(text=self.current.answer)
        self.answer_visible = True
        self.update_status()

    def mark_correct(self) -> None:
        """
        Mark current card as answered correctly, persist, and move on.
        """
        if not self.current:
            return
        if not self.answer_visible:
            self.show_answer()
        stats = self.progress.setdefault(self.current.card_id, {"correct": 0, "incorrect": 0})
        stats["correct"] += 1
        save_progress(self.progress_path, self.progress)
        self.next_card()

    def mark_incorrect(self) -> None:
        """
        Mark current card as answered incorrectly, persist, and move on.
        """
        if not self.current:
            return
        if not self.answer_visible:
            self.show_answer()
        stats = self.progress.setdefault(self.current.card_id, {"correct": 0, "incorrect": 0})
        stats["incorrect"] += 1
        save_progress(self.progress_path, self.progress)
        self.next_card()

    def next_card(self) -> None:
        """
        Select next card using weights, reset view; exit if none.
        """
        if not self.cards:
            messagebox.showinfo("No cards", "No questions found.")
            self.root.destroy()
            return
        # Avoid showing the same card twice in a row when multiple cards exist.
        last_id = self.previous_id
        attempts = 0
        candidate = None
        while True:
            candidate = choose_card(self.cards, self.progress)
            attempts += 1
            if len(self.cards) == 1:
                break
            if candidate.card_id != last_id:
                break
            if attempts >= 5:
                break

        self.current = candidate
        self.previous_id = candidate.card_id if candidate else None
        self.answer_visible = False
        self.card_id_label.config(text=f"Question {self.current.card_id}")
        self.question_label.config(text=self.current.question)
        self.answer_label.config(text="")
        self.update_status()

    def update_status(self) -> None:
        """
        Update status label with per-card correct/wrong counters.
        """
        if not self.current:
            self.status_label.config(text="")
            return
        stats = self.progress.get(self.current.card_id, {"correct": 0, "incorrect": 0})
        self.status_label.config(
            text=f"Correct: {stats.get('correct', 0)} | Wrong: {stats.get('incorrect', 0)}"
        )

    def run(self) -> None:
        """
        Start the Tkinter event loop.
        """
        self.root.mainloop()


def select_markdown() -> Path | None:
    """
    Open a file dialog to choose a markdown deck.

    Returns:
        Path to the chosen file or None if cancelled.
    """
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="Select markdown file with questions",
        filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(path) if path else None


def main() -> None:
    """Entry point: resolve deck path, load config, start GUI."""
    md_path: Path | None = None
    if len(sys.argv) >= 2:
        md_path = Path(sys.argv[1]).expanduser().resolve()
    else:
        cfg = load_config()
        last = cfg.get("last_md_path")
        if last:
            last_path = Path(last)
            if last_path.exists():
                root = tk.Tk()
                root.withdraw()
                use_last = messagebox.askyesno(
                    "Open last file?", f"Open the last file used?\n{last_path}"
                )
                root.destroy()
                if use_last:
                    md_path = last_path
        if md_path is None:
            chosen = select_markdown()
            if not chosen:
                return
            md_path = chosen

    if not md_path.exists():
        messagebox.showerror("Error", f"File not found: {md_path}")
        return

    save_config(md_path)

    try:
        app = FlashcardApp(md_path)
    except Exception as exc:
        messagebox.showerror("Error", str(exc))
        return
    app.run()


if __name__ == "__main__":
    main()
