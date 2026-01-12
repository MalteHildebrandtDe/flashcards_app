# Flashcard app (Markdown)

Small Tkinter desktop app to learn open questions from a Markdown file. Stores progress as `.fragen_progress.json` next to the deck. No console needed when built.

## Files
- [flashcards_app/app.py](flashcards_app/app.py): GUI, parser, spaced-repetition weighting.
- [flashcards_app/README.md](flashcards_app/README.md): this note.

## Location
- Keep the project anywhere in your user space, e.g. `~/Documents/Apps/flashcards_app` (Linux/macOS) or `C:\Users\<you>\Documents\flashcards_app` (Windows).
- Decks can live anywhere; progress is always saved alongside the chosen Markdown file.

## Run without build
1. Python 3.9+ (optional venv: `python -m venv .venv && source .venv/bin/activate`, Windows: `venv\Scripts\activate`).
2. Start: `python app.py /path/to/questions.md` or simply `python app.py` and pick via dialog.
3. Keys: Enter = show answer, Right = correct, Left = wrong. Buttons do the same.
4. Progress: written to `.fragen_progress.json` next to the Markdown deck.

## Build (PyInstaller)
1. `pip install pyinstaller`
2. From project folder:
   - Windows: `pyinstaller --noconsole --onefile --name flashcards_app app.py`
   - macOS: `pyinstaller --windowed --onefile --name flashcards_app app.py`
   - Linux: `pyinstaller --noconsole --onefile --name flashcards_app app.py`
3. Binary lands in `dist/`. Run it with or without a path; dialog opens if no path is given.

## Markdown format
- Questions: `**Frage X**` or `**Question X**` (case-insensitive). The `X` part must be unique per card (number, code, whatever).
- Answers: `**Antwort:**`, `Antwort:`, `**Answer:**`, or `Answer:` (case-insensitive). Everything until the next question header is taken as the answer if no marker is found.
- Wrong answers are weighted higher (show up more often); correct answers show up less.
- Standard library only; add an icon later with PyInstaller `--icon` if you want.
