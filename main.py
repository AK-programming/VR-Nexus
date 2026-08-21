import os
import re
import asyncio
import pandas as pd
import fitz
import tiktoken
from section_3_extraction import extract_all_chunks_parallel, assemble_master_table


def chunk_text_by_tokens(text: str, page_range: str, section: str, max_tokens: int = 250,
                         overlap_tokens: int = 25) -> list:
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)

    chunks = []
    for i in range(0, len(tokens), max_tokens - overlap_tokens):
        chunk_tokens = tokens[i:i + max_tokens]
        chunk_text = encoding.decode(chunk_tokens)

        chunks.append({
            "text": chunk_text,
            "page_range": page_range,
            "section": section
        })

    return chunks


def verify_rfp_scoring(full_text: str):
    print("\n==================================================")
    print("RUNNING RFP SCORE VERIFICATION")
    print("==================================================")

    eval_section = re.search(r'(?i)Evaluation and Qualification Criteria(.*?)(?:Award of Contract|Section IV|Part 2)',
                             full_text, re.DOTALL)
    search_text = eval_section.group(1) if eval_section else full_text

    percentages = re.findall(r'(\d+(?:\.\d+)?)%', search_text)

    scores = [float(p) for p in percentages if float(p) < 100]

    unique_scores = []
    for s in scores:
        if s not in unique_scores:
            unique_scores.append(s)

    total_score = sum(unique_scores)

    print(f"Extracted Unique Weights: {unique_scores}")
    print(f"Calculated Total:         {total_score}%")

    if total_score == 100.0:
        print("SUCCESS: The scoring criteria perfectly sums to 100%.")
    else:
        print(f"WARNING: The detected scores sum to {total_score}%, NOT 100%.")
        print("   This may happen if sub-criteria share weights. Please verify the RFP manually.")


async def main():
    pdf_path = "big tender.pdf"

    if not os.path.exists(pdf_path):
        print(f"Error: '{pdf_path}' not found in the current directory.")
        return

    print(f"\nReading PDF: {pdf_path}...")
    doc = fitz.open(pdf_path)
    full_text = ""
    chunk_dicts = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        full_text += text + "\n"

        if text.strip():
            page_chunks = chunk_text_by_tokens(
                text=text,
                page_range=f"Page {page_num + 1}",
                section=f"Section (Page {page_num + 1})",
                max_tokens=250,
                overlap_tokens=25
            )
            chunk_dicts.extend(page_chunks)

    verify_rfp_scoring(full_text)

    all_chunk_results = await extract_all_chunks_parallel(chunk_dicts, max_concurrent_calls=15)

    final_data = assemble_master_table(all_chunk_results)

    if final_data["master_table"]:
        df = pd.DataFrame(final_data["master_table"])

        os.makedirs("outputs", exist_ok=True)
        output_file = "outputs/master_tender_requirements.xlsx"

        df.to_excel(output_file, index=False)
        print(f"\nSuccessfully saved {len(df)} rows to {output_file}")

        if final_data["manual_review_flags"] > 0:
            print(
                f"Note: {final_data['manual_review_flags']} chunks failed API processing and require manual review in the Excel sheet.")
    else:
        print("\nNo requirements were extracted.")


if __name__ == "__main__":
    asyncio.run(main())