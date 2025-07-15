import tkinter as tk
import tkinter.scrolledtext as tkscroll
import markdown

class MarkdownViewer(tkscroll.ScrolledText):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.configure(state=tk.DISABLED, wrap=tk.WORD)

    def load_markdown(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            markdown_content = file.read()
        html_content = markdown.markdown(markdown_content)
        self.display_html(html_content)

    def display_html(self, html_content):
        self.configure(state=tk.NORMAL)
        self.delete("1.0", tk.END)
        self.insert(tk.END, html_content)
        self.configure(state=tk.DISABLED)