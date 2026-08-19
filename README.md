# VR-Nexus
VR Nexus is an AI-powered document intelligence platform that streamlines case study retrieval, government tender analysis, and methodology document management through a unified web application.
# Tender Ingestion Module (Section 2.1)

This module is a FastAPI web service designed to securely upload, validate, and extract text and tables from Tender/RFP PDF documents. 

## Features
* **PDF Upload & Validation (Task 2.1.1):** Accepts `.pdf` files and enforces a strict 100 MB file size limit to protect server memory.
* **Text & Table Extraction (Task 2.1.2):** Uses PyMuPDF to extract text while strictly preserving exact page numbers. Automatically detects and formats grid tables natively.
* **OCR Fallback (Task 2.1.3):** Automatically detects scanned pages (pages with less than 50 characters of digital text) and uses Tesseract OCR to read the images.
* **Database & Auth Integration:** Currently utilizes mock placeholder objects for PostgreSQL models and RBAC authentication, ready to be linked to the Section 1 backend core.

## Prerequisites

Before running this module, ensure you have the required Python libraries installed:

```bash
pip install fastapi uvicorn pymupdf pytesseract pillow python-multipart