from arango import ArangoClient
import os
 
client = ArangoClient(hosts=os.getenv("ARANGO_URL"))
sys_db = client.db("_system", username=os.getenv("ARANGO_USER"), password=os.getenv("ARANGO_ROOT_PASSWORD"))
 
# Create app database if it doesn't exist
if not sys_db.has_database(os.getenv("ARANGO_DB")):
    sys_db.create_database(os.getenv("ARANGO_DB"))
 
db = client.db(os.getenv("ARANGO_DB"), username=os.getenv("ARANGO_USER"), password=os.getenv("ARANGO_ROOT_PASSWORD"))
 
# Create document_chunks collection
if not db.has_collection("document_chunks"):
    db.create_collection("document_chunks")
 
# Create ArangoSearch view with vector index for similarity search
if "chunks_view" not in [v["name"] for v in db.views()]:
    db.create_arangosearch_view(
        "chunks_view",
        properties={
            "links": {
                "document_chunks": {
                    "fields": {
                        "embedding": {
                            "analyzers": ["identity"],
                            "cache": True
                        }
                    }
                }
            }
        }
    )