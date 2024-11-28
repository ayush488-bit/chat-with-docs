import asyncio
from io import BytesIO
from itertools import chain
from anyio import sleep
from openai import BaseModel
import streamlit as st
import pdftotext
from constants import CREATE_FACT_CHUNKS_SYSTEM_PROMPT, GET_MATCHING_TAGS_SYSTEM_PROMPT
from db import DocumentInformationChunks, DocumentTags, Tags, db, Documents, set_openai_api_key
from peewee import SQL, JOIN, NodeList

from utils import find

st.set_page_config(page_title="Manage Documents")
st.title("Manage Documents")

def delete_document(document_id: int):
    Documents.delete().where(Documents.id == document_id).execute()

IDEAL_CHUNK_LENGTH = 4000

class GeneratedDocumentInformationChunks(BaseModel):
    facts: list[str]
    
async def generate_chunks(index: int, pdf_text_chunk: str):
    total_retries = 0
    while True:
        try:
            with db.atomic() as transaction:
                set_openai_api_key()
                response = db.execute_sql(f"""
                    SELECT
                    ai.openai_chat_complete (
                        'gpt-4o-mini-2024-07-18',
                        jsonb_build_array(
                            jsonb_build_object('role', 'system', 'content', %s),
                            jsonb_build_object('role', 'user', 'content', %s)
                        )
                    ) -> 'choices' -> 0 -> 'message' ->> 'content';
                """, (CREATE_FACT_CHUNKS_SYSTEM_PROMPT, pdf_text_chunk)).fetchone()[0]
                transaction.commit()
            document_information_chunks = GeneratedDocumentInformationChunks.model_validate_json(response).facts
            print(f"Generated {len(document_information_chunks)} facts for pdf text chunk {index}.")
            return document_information_chunks
        except Exception as e:
            total_retries += 1
            if total_retries > 5:
                raise e
            await sleep(1)
            print(f"Failed to generate facts for pdf text chunk {index} with this err: {e}. Retrying...")
            
class GeneratedMatchingTags(BaseModel):
    tags: list[str]

async def get_matching_tags(pdf_text: str):
    tags_result = Tags.select()
    tags = [
        tag.name.lower()
        for tag in tags_result
    ]
    if not len(tags):
        return []
    total_retries = 0
    while True:
        try:
            with db.atomic() as transaction:
                set_openai_api_key()
                response = db.execute_sql(f"""
                    SELECT
                    ai.openai_chat_complete (
                        'gpt-4o-mini-2024-07-18',
                        jsonb_build_array(
                            jsonb_build_object('role', 'system', 'content', %s),
                            jsonb_build_object('role', 'user', 'content', %s)
                        )
                    ) -> 'choices' -> 0 -> 'message' ->> 'content';
                """, (GET_MATCHING_TAGS_SYSTEM_PROMPT.replace("{{tags_to_match_with}}", str(tags)), pdf_text)).fetchone()[0]
                transaction.commit()
            matching_tag_names = GeneratedMatchingTags.model_validate_json(response).tags
            matching_tag_ids: list[int] = []
            for tag_name in matching_tag_names:
                matching_tag = find(lambda tag: tag.name.lower() == tag_name.lower(), tags_result)
                if matching_tag:
                    matching_tag_ids.append(matching_tag.id)
                else:
                    raise Exception(f"Tag {tag_name} matched not found in database.")
            print(f"Generated matching tags {str(matching_tag_names)} for pdf text.")
            return matching_tag_ids
        except Exception as e:
            total_retries += 1
            if total_retries > 5:
                raise e
            await sleep(1)
            print(f"Failed to generate matching tags for pdf with this err: {e}. Retrying...")

def upload_document(name: str, pdf_file: bytes):
    parsed_pdf = pdftotext.PDF(BytesIO(pdf_file))
    pdf_text = "\n\n".join(parsed_pdf)
    pdf_text_chunks: list[str] = []
    for i in range(0, len(pdf_text), IDEAL_CHUNK_LENGTH):
        pdf_text_chunks.append(pdf_text[i:i + IDEAL_CHUNK_LENGTH])
    generate_chunks_coroutines = [
        generate_chunks(index, pdf_text_chunk)
        for index, pdf_text_chunk in enumerate(pdf_text_chunks)
    ]
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    generate_chunks_coroutines_gather = asyncio.gather(*generate_chunks_coroutines)
    get_matching_tags_coroutine = get_matching_tags(pdf_text[0:5000])
    [document_information_chunks_from_each_pdf_text_chunk, matching_tag_ids] = event_loop.run_until_complete(
        asyncio.gather(generate_chunks_coroutines_gather, get_matching_tags_coroutine)
    )
    document_information_chunks = list(chain.from_iterable(document_information_chunks_from_each_pdf_text_chunk))
    with db.atomic() as transaction:
        set_openai_api_key()
        document_id = Documents.insert(
            name=name,
        ).execute()
        DocumentInformationChunks.insert_many(
            [
                {
                    "document_id": document_id,
                    "chunk": chunk,
                    "embedding": SQL(f"ai.openai_embed('text-embedding-3-small',%s)", (chunk,))
                }
                for chunk in document_information_chunks
            ]
        ).execute()
        DocumentTags.insert_many(
            [
                {
                    "document_id": document_id,
                    "tag_id": tag_id
                }
                for tag_id in matching_tag_ids
            ]
        ).execute()
        transaction.commit()
        print(f"Inserted {len(document_information_chunks)} facts for pdf {name} with document id {document_id} and {len(matching_tag_ids)} matching tags.")
    event_loop.close()

@st.dialog("Upload document")
def upload_document_dialog_open():
    pdf_file = st.file_uploader("Upload PDF file", type="pdf")
    if pdf_file is not None:
        if st.button("Upload", key="upload-document-button"):
            upload_document(pdf_file.name, pdf_file.getvalue())
            st.rerun()

st.button("Upload Document", key="upload-document-button", on_click=upload_document_dialog_open)

documents = Documents.select(
    Documents.id,
    Documents.name,
    NodeList([
        SQL('array_remove(array_agg('),
        Tags.name,
        SQL('), NULL)')
    ]).alias("tags")
).join(DocumentTags, JOIN.LEFT_OUTER).join(Tags, JOIN.LEFT_OUTER).group_by(Documents.id).execute()

if len(documents):
    for document in documents:
        document_container = st.container(border=True)
        document_container.write(document.name)
        if len(document.tags):
            document_container.write(f"Tags: {', '.join(document.tags)}")
        document_container.button("Delete", key=f"{document.id}-delete-button", on_click=lambda: delete_document(document.id))
else:
    st.info("No documents created yet. Please create one!")
