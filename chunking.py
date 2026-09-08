def chunk_article(
    blocks,
    article_path,
    max_chars=2000,
    overlap_chars=300,
):
    chunks = []

    current_section = "Introduction"
    current_subsection = None
    current_paragraphs = []

    chunk_number = 0

    def save_chunk():
        nonlocal current_paragraphs, chunk_number

        if not current_paragraphs:
            return

        text = "\n\n".join(current_paragraphs).strip()

        chunks.append({
            "chunk_id": f"{article_path}_{chunk_number:03d}",
            "article_path": article_path,
            "section": current_section,
            "subsection": current_subsection,
            "text": text,
        })

        chunk_number += 1

        # Build overlap from whole paragraphs instead of
        # cutting arbitrary characters.
        overlap_paragraphs = []
        overlap_length = 0

        for paragraph in reversed(current_paragraphs):
            paragraph_length = len(paragraph)

            if (
                overlap_paragraphs
                and overlap_length + paragraph_length > overlap_chars
            ):
                break

            overlap_paragraphs.insert(0, paragraph)
            overlap_length += paragraph_length

            if overlap_length >= overlap_chars:
                break

        current_paragraphs = overlap_paragraphs

    for block in blocks:

        if block["type"] == "h2":
            save_chunk()

            current_section = block["text"]
            current_subsection = None
            current_paragraphs = []

            continue

        if block["type"] == "h3":
            save_chunk()

            current_subsection = block["text"]
            current_paragraphs = []

            continue

        paragraph = block["text"]

        projected_text = "\n\n".join(
            current_paragraphs + [paragraph]
        )

        if (
            len(projected_text) > max_chars
            and current_paragraphs
        ):
            save_chunk()

        current_paragraphs.append(paragraph)

    save_chunk()

    return chunks