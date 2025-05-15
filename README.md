import fitz # PyMuPDF
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox
import sys

# This script requires the PyMuPDF library to be installed.
# You can install it using pip: pip install pymupdf
# The current execution environment does not support installing external libraries,
# including tkinter for GUI dialogs, so this script cannot be fully run here.

def extract_all_chunks_from_pdf(pdf_path):
    """
    Extracts all text content and attempts to infer basic structure (headers, sections)
    from a PDF file, returning a list of all structured chunks without a size limit.
    Also returns the total number of pages.

    Args:
        pdf_path (str): The path to the PDF file.

    Returns:
        tuple: A tuple containing:
               - list: A list of dictionaries, where each dictionary represents a
                       structured chunk of content.
               - int: The total number of pages in the PDF.
               Returns (None, None) if the file cannot be opened.
    """
    chunks = []
    total_pages = 0

    try:
        document = fitz.open(pdf_path)
        total_pages = document.page_count
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

            print(f"Processed page {page_num + 1}/{document.page_count}")


        return chunks, total_pages

    except FileNotFoundError:
        messagebox.showerror("Error", f"The file {pdf_path} was not found.")
        return None, None
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred during PDF processing: {e}")
        return None, None

def save_chunks_to_multiple_json_files(all_chunks, base_json_path, max_content_size_bytes=1000000):
    """
    Saves the extracted chunks to multiple JSON files, splitting based on
    the accumulated content text size. Returns the number of files created.

    Args:
        all_chunks (list): A list of all extracted chunks.
        base_json_path (str): The base path for the output JSON files (e.g., "output/document").
                              File parts will be appended (e.g., "output/document_part_1.json").
        max_content_size_bytes (int): The maximum allowed size for the accumulated text
                                     content in bytes per output file.

    Returns:
        int: The number of JSON files created. Returns 0 if no data was saved.
    """
    if not all_chunks:
        messagebox.showwarning("No Data to Save", "No chunks were extracted from the PDF.")
        return 0

    current_file_chunks = []
    current_content_size = 0
    file_counter = 1

    # Add document title to the first file
    doc_title = os.path.basename(base_json_path).replace("_part", "").replace(".json", "") # Infer title from base path
    title_chunk = {
        "type": "document_title",
        "page_number": 1, # Assume title is related to the start
        "content": doc_title
    }
    current_file_chunks.append(title_chunk)
    current_content_size += sys.getsizeof(title_chunk.get("content", ""))


    for chunk in all_chunks:
        chunk_content = chunk.get("content", "")
        chunk_content_size = sys.getsizeof(chunk_content)

        # Check if adding this chunk exceeds the size limit for the current file
        if current_content_size + chunk_content_size > max_content_size_bytes and current_file_chunks:
            # Save the current file and start a new one
            output_path = f"{os.path.splitext(base_json_path)[0]}_part_{file_counter}.json"
            save_to_json(current_file_chunks, output_path)

            # Reset for the new file
            current_file_chunks = []
            current_content_size = 0
            file_counter += 1

            # Add document title to the beginning of each new file part for context
            current_file_chunks.append(title_chunk)
            current_content_size += sys.getsizeof(title_chunk.get("content", ""))


        # Add the current chunk to the list for the current file
        current_file_chunks.append(chunk)
        current_content_size += chunk_content_size

    # Save any remaining chunks in the last file
    if current_file_chunks:
        output_path = f"{os.path.splitext(base_json_path)[0]}_part_{file_counter}.json"
        save_to_json(current_file_chunks, output_path)
        file_counter += 1 # Increment for the last file saved

    # Subtract 1 from file_counter because it's incremented after the last save
    return file_counter -1 if file_counter > 1 else file_counter # Return actual count

def save_metadata_to_json(metadata, metadata_path):
    """
    Saves the document metadata to a JSON file.

    Args:
        metadata (dict): The metadata dictionary to save.
        metadata_path (str): The path to the output metadata JSON file.
    """
    try:
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
        messagebox.showinfo("Metadata Saved", f"Successfully saved metadata to {metadata_path}")
    except Exception as e:
        messagebox.showerror("Error", f"Error saving metadata file: {e}")


def save_to_json(data, json_path):
    """
    Saves the extracted data to a JSON file. Used internally for chunk files.

    Args:
        data (list): The data structure to save.
        json_path (str): The path to the output JSON file.
    """
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"Successfully saved structured data to {json_path}") # Use print for console output during batch save
    except Exception as e:
        # Use print here as this is called during batch saving, avoid multiple message boxes
        print(f"Error saving JSON file {json_path}: {e}")


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
        print("Starting full extraction...")

        all_extracted_chunks, total_pages = extract_all_chunks_from_pdf(input_pdf_path)

        if all_extracted_chunks is not None: # Check for None in case of initial errors
            if all_extracted_chunks: # Check if any data was extracted
                # --- Save File Dialog for Base Name ---
                base_output_json_path = filedialog.asksaveasfilename(
                    title="Save Structured JSON Files As (Choose Base Name)",
                    defaultextension=".json",
                    filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
                    initialfile=f"{os.path.splitext(os.path.basename(input_pdf_path))[0]}_structured.json" # Suggest name based on PDF
                )

                if base_output_json_path:
                    print(f"Saving chunks to files based on: {base_output_json_path}")
                    # Set the maximum accumulated content size per output file (1 MB as per Bedrock error)
                    MAX_CONTENT_SIZE_PER_FILE_BYTES = 1000000

                    num_files_created = save_chunks_to_multiple_json_files(
                        all_extracted_chunks,
                        base_output_json_path,
                        max_content_size_bytes=MAX_CONTENT_SIZE_PER_FILE_BYTES
                    )

                    if num_files_created > 0:
                        # --- Save Metadata File ---
                        metadata = {
                            "original_pdf_filename": os.path.basename(input_pdf_path),
                            "total_pages_in_pdf": total_pages,
                            "number_of_json_chunk_files": num_files_created,
                            "base_output_filename": os.path.basename(base_output_json_path)
                        }
                        metadata_output_path = f"{os.path.splitext(base_output_json_path)[0]}_metadata.json"
                        save_metadata_to_json(metadata, metadata_output_path)

                else:
                    messagebox.showinfo("Cancelled", "Save location selection cancelled.")
            else:
                 messagebox.showwarning("No Data Extracted", "No data was extracted from the PDF.")
        # else: extract_all_chunks_from_pdf already showed an error message


    root.destroy() # Clean up the hidden root window
