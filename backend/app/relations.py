"""Relation-level policy shared across services.

`RETRIEVAL_ONLY_RELATIONS` are relations whose objects are structured reference data —
JSON request/response bodies. These are **not** pushed into the model: ROME/MEMIT are
locate-and-edit methods for short factual objects and cannot reliably encode long,
arbitrary sequences (a body's exact IDs/timestamps are un-memorizable instance data).

They remain in Postgres (the `endpoint_variant` columns and their derived triples) and
are served by retrieval instead. Edit jobs drop these triples before dispatch.
"""

RETRIEVAL_ONLY_RELATIONS = {"request_body", "response_200"}
