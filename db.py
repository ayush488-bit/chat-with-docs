from os import getenv
from pgvector.peewee import VectorField
from peewee import PostgresqlDatabase, Model, TextField, ForeignKeyField

db = PostgresqlDatabase(
    getenv("POSTGRES_DB_NAME"),
    host=getenv("POSTGRES_DB_HOST"),
    port=getenv("POSTGRES_DB_PORT"),
    user=getenv("POSTGRES_DB_USER"),
    password=getenv("POSTGRES_DB_PASSWORD"),
)

class Documents(Model):
   name = TextField()
   class Meta:
      database = db
      db_table = 'documents'
      
class Tags(Model):
   name = TextField()
   class Meta:
      database = db
      db_table = 'tags'
      
class DocumentTags(Model):
   document_id = ForeignKeyField(Documents, backref="document_tags", on_delete='CASCADE')
   tag_id = ForeignKeyField(Tags, backref="document_tags", on_delete='CASCADE')
   class Meta:
      database = db
      db_table = 'document_tags'
      
class DocumentInformationChunks(Model):
   document_id = ForeignKeyField(Documents, backref="document_information_chunks", on_delete='CASCADE')
   chunk = TextField()
   embedding = VectorField(dimensions=1536)
   class Meta:
      database = db
      db_table = 'document_information_chunks'
      
DocumentInformationChunks.add_index('embedding vector_cosine_ops', using='diskann')

db.connect()
db.create_tables([Documents, Tags, DocumentTags, DocumentInformationChunks])

def set_diskann_query_rescore(query_rescore: int):
   db.execute_sql(
      "SET diskann.query_rescore = %s",
      (query_rescore,)
   )

def set_openai_api_key():
   db.execute_sql(
      "set ai.openai_api_key = %s;\nselect pg_catalog.current_setting('ai.openai_api_key', true) as api_key",
      (getenv("OPENAI_API_KEY"),)
   )
