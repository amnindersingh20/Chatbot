import fitz # PyMuPDF
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox

# This script requires the PyMuPDF library to be installed.
# You can install it using pip: pip install pymupdf
# The current execution environment does not support installing external libraries,
# including tkinter for GUI dialogs, so this script cannot be fully run here.

def extract_structure_from_pdf(pdf_path):
    """
    Extracts text content and attempts to infer basic structure (headers, sections)
    from a PDF file, returning a list of structured chunks.

    Args:
        pdf_path (str): The path to the PDF file.

    Returns:
        list: A list of dictionaries, where each dictionary represents a
              structured chunk of content (e.g., header, paragraph, potential table).
              Returns None if the file cannot be opened.
    """
    chunks = []
    try:
        document = fitz.open(pdf_path)
        doc_title = os.path.basename(pdf_path) # Use filename as a default title

        # Basic heuristic for identifying potential headers:
        # Look for lines that are significantly different in font size or style
        # or are followed by a large vertical space.
        # PyMuPDF's basic text extraction doesn't easily give font info per line,
        # so we'll primarily rely on line breaks and simple text patterns for this example.
        # A more advanced approach would involve analyzing text blocks with get_text("dict")
        # and checking font information.

        for page_num in range(document.page_count):
            page = document.load_page(page_num)
            text = page.get_text("text") # Extract text with basic layout preservation

            lines = text.split('\n')
            current_section_content = []
            current_section_header = None

            for i, line in enumerate(lines):
                line = line.strip()
                if not line: # Skip empty lines
                    if current_section_content:
                        # End of a paragraph/section, store it
                        chunks.append({
                            "type": "paragraph",
                            "page_number": page_num + 1,
                            "section_header": current_section_header,
                            "content": "\n".join(current_section_content)
                        })
                        current_section_content = []
                    continue

                # --- Basic Heuristics for Structure ---
                # This is a simplified approach. Real-world PDFs vary greatly.

                # Potential Header Check:
                # - If the line is short and followed by a blank line or starts with a number/letter followed by a period/space (like section numbers)
                # - This is highly heuristic and might misidentify things.
                is_potential_header = False
                if len(line) < 80 and (i + 1 < len(lines) and not lines[i+1].strip()):
                     is_potential_header = True
                elif line and (line[0].isdigit() or line[0].isalpha()) and (len(line) > 1 and (line[1] in ['.', ' '])):
                     is_potential_header = True


                if is_potential_header and not current_section_content:
                    # Assume this is a new section header if we are not already in content
                    if current_section_header:
                         # Store previous section if any before starting a new header
                         chunks.append({
                            "type": "paragraph",
                            "page_number": page_num + 1,
                            "section_header": current_section_header,
                            "content": "\n".join(current_section_content)
                        })
                         current_section_content = []

                    current_section_header = line
                    chunks.append({
                        "type": "section_header",
                        "page_number": page_num + 1,
                        "content": line
                    })
                else:
                    current_section_content.append(line)

            # Add any remaining content at the end of the page
            if current_section_content:
                 chunks.append({
                    "type": "paragraph",
                    "page_number": page_num + 1,
                    "section_header": current_section_header,
                    "content": "\n".join(current_section_content)
                })


        # Add document title chunk at the beginning
        chunks.insert(0, {
            "type": "document_title",
            "page_number": 1, # Assume title is related to the start
            "content": doc_title
        })


        return chunks

    except FileNotFoundError:
        # This case is less likely with file dialogs, but good to keep
        messagebox.showerror("Error", f"The file {pdf_path} was not found.")
        return None
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred during PDF processing: {e}")
        return None

def save_to_json(data, json_path):
    """
    Saves the extracted data to a JSON file.

    Args:
        data (list): The data structure to save.
        json_path (str): The path to the output JSON file.
    """
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        messagebox.showinfo("Success", f"Successfully saved structured data to {json_path}")
    except Exception as e:
        messagebox.showerror("Error", f"Error saving JSON file: {e}")

if __name__ == "__main__":
    # Create a root window but hide it as we only need dialogs
    root = tk.Tk()
    root.withdraw()

    # --- File Selection ---
    input_pdf_path = filedialog.askopenfilename(
        title="Select PDF File to Process",
        filetypes=(("PDF files", "*.pdf"), ("All files", "*.*"))
    )

    if not input_pdf_path:
        messagebox.showinfo("Cancelled", "PDF selection cancelled.")
    else:
        print(f"Selected PDF: {input_pdf_path}")
        print("Starting extraction...")

        structured_data = extract_structure_from_pdf(input_pdf_path)

        if structured_data:
            # --- Save File Dialog ---
            output_json_path = filedialog.asksaveasfilename(
                title="Save Structured JSON As",
                defaultextension=".json",
                filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
                initialfile="structured_document.json" # Suggest a default name
            )

            if output_json_path:
                print(f"Saving to: {output_json_path}")
                save_to_json(structured_data, output_json_path)
            else:
                messagebox.showinfo("Cancelled", "Save location selection cancelled.")
        else:
            messagebox.showerror("Extraction Failed", "PDF extraction did not produce any data.")

    root.destroy() # Clean up the hidden root window

