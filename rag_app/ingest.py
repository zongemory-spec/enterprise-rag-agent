from pathlib import Path
from rag_app.sections import split_sections

def parse_file(path):
    path=Path(path)
    if path.suffix.lower() in {".txt",".md"}:
        text=path.read_text(encoding="utf-8-sig")
        return text,split_sections(text)
    if path.suffix.lower()==".pdf":
        from pypdf import PdfReader
        locations=[];pages=[]
        for number,page in enumerate(PdfReader(path).pages,1):
            text=page.extract_text() or ""
            pages.append(text)
            locations.extend((f"page {number}; {location}",part) for location,part in split_sections(text))
        if not locations:
            raise ValueError("PDF has no extractable text; OCR is outside this prototype")
        return "\n".join(pages),locations
    raise ValueError("Only text, Markdown and text PDFs are supported")

