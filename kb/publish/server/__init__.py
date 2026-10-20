"""`kb serve` behind the facade kb.publish.serve: http (route table, handler), web (the browser app), chat_api
(discussions), ingest_api (uploads and the ingest queue), settings_api (settings, keys, usage, status), app (the server)."""
import threading

WRITE_LOCK = threading.Lock()  # one writer to the instance at a time: ingest, removing a source, saving a discussion
