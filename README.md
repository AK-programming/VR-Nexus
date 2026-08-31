# VR Nexus - AI Document Intelligence Platform

## Overview
VR Nexus is an AI-powered document intelligence platform that streamlines case study retrieval, government tender analysis, and methodology document management through a unified web application. 

The platform is designed to securely upload, validate, and parse massive Request for Proposal (RFP) PDFs. It uses a Large Language Model (LLM) to extract concrete deliverables, submission documents, and mandatory compliance forms, filtering out general background text to generate a strict 8-column Excel matrix ready for proposal management.

---

## System Architecture

The project is divided into modular sections handling the end-to-end document processing pipeline:

### 1. Core Backend & Database (`mock_section_1.py`)
*   **FastAPI Framework:** Provides the high-performance web service foundation.
*   **Authentication:** Implements Role-Based Access Control (RBAC) to ensure secure access to documents. 
*   **Database Management:** Currently utilizes in-memory mock placeholder objects for PostgreSQL models and querying.

### 2. Tender Ingestion & Chunking (`section_2_1_ingestion.py` & `section_2_2_chunking.py`)
*   **Upload Validation:** Accepts `.pdf` files and enforces a strict 100 MB file size limit to protect server memory.
*   **Text & Table Extraction:** Uses PyMuPDF to extract text while strictly preserving exact page numbers and natively formatting grid tables.
*   **OCR Fallback:** Automatically detects scanned pages (pages with less than 50 characters of digital text) and uses Tesseract OCR to extract text from images.
*   **Section Boundary Detection:** Uses Regex to map the structural boundaries of the RFP (e.g., SPN, Instructions to Proposers, Evaluation Criteria).
*   **Token-Based Slicing:** Utilizes `tiktoken` to chunk document text safely without breaking context, generating overlapping sliding windows to preserve narrative continuity.

### 3. LLM Extraction & Validation (`section_3_extraction.py` & `main.py`)
*   **High Concurrency:** Asynchronous architecture (`asyncio`) blasts multiple chunks to the API simultaneously to ensure rapid processing.
*   **Strict JSON Enforcement:** Uses Pydantic schemas to force the LLM to output exactly 8 columns with strict word-length constraints.
*   **Python "Bouncer" Logic:** A post-processing filter actively drops rows containing background fluff, executive summaries, or general software requirements, ensuring only tangible artifacts reach the final sheet.
*   **Automated Math Verification:** Includes an RFP Score Verifier that automatically hunts for evaluation criteria and calculates if the weights sum perfectly to 100%.
*   **Export:** Dynamically generates a clean Excel matrix using Pandas.

---

## File Structure

*   `main.py` - The orchestrator script executing the PDF parsing, math validation, LLM extraction, and Excel generation.
*   `mock_section_1.py` - Core mock database, Pydantic query schemas, and RBAC authentication functions.
*   `section_2_1_ingestion.py` - Handles the PyMuPDF parsing, table extraction, and PyTesseract OCR fallback.
*   `section_2_2_chunking.py` - Manages Regex section boundaries, Tiktoken chunking, and mock embedding generation.
*   `section_3_extraction.py` - The LLM engine containing the strict system prompt, asynchronous API calling logic, and the Python filtering "bouncer".
*   `requirements.txt` - Project Python dependencies.
*   `Dockerfile` - Containerization instructions using `python:3.11-slim`.
*   `.env` - Environment variables configuration.

---

## Prerequisites & Installation

### Local Setup
Ensure you have Python 3.11+ installed. You must also install the Tesseract binary at the OS level for the OCR fallback to function.

1. Install the Python dependencies:
```bash
pip install fastapi uvicorn python-multipart pymupdf pytesseract pillow pandas openpyxl tiktoken anthropic python-dotenv pydantic openai