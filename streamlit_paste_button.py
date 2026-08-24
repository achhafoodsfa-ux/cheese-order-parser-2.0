"""Compatibility shim for the old paste-image import.

Uses Streamlit's native chat_input file attachment support so screenshots can be
pasted from the clipboard without the third-party streamlit-paste-button package.
"""
from dataclasses import dataclass
import io
import streamlit as st

@dataclass
class _PasteResult:
    image_data: object = None


def paste_image_button(label="Paste Image from Clipboard", key=None, errors="ignore"):
    """Render one native clipboard/file input and expose the first image as image_data.

    This preserves the old app.py API while removing the fragile third-party
    clipboard component. Users can Ctrl+V a screenshot or attach an image.
    """
    submission = st.chat_input(
        "📋 Ctrl+V screenshot here — or drag/drop an image",
        accept_file="multiple",
        file_type=["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"],
        max_upload_size=200,
        key=key or "native_clipboard_input",
    )
    if submission is None:
        return None
    for uploaded in getattr(submission, "files", []) or []:
        try:
            ext = uploaded.name.rsplit(".", 1)[-1].lower()
            if ext in {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}:
                from PIL import Image
                return _PasteResult(image_data=Image.open(io.BytesIO(uploaded.getvalue())))
        except Exception:
            if errors != "ignore":
                raise
    return _PasteResult()
