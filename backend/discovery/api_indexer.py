"""Parse OpenAPI specs and index endpoints into ChromaDB."""

import json
import os

import chromadb


async def index_all_specs(specs_dir: str, collection: chromadb.Collection) -> int:
    """Index all OpenAPI spec files in the specs directory."""
    total = 0

    for filename in os.listdir(specs_dir):
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(specs_dir, filename)
        with open(filepath, "r") as f:
            spec = json.load(f)

        count = _index_spec(spec, collection)
        total += count
        print(f"  [Indexer] {filename}: indexed {count} endpoints")

    return total


def _index_spec(spec: dict, collection: chromadb.Collection) -> int:
    """Parse a single OpenAPI spec and index its endpoints."""
    service_name = spec.get("info", {}).get("title", "Unknown")
    base_url = ""
    if spec.get("servers"):
        base_url = spec["servers"][0].get("url", "")

    paths = spec.get("paths", {})
    documents = []
    metadatas = []
    ids = []

    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ("parameters", "servers", "summary", "description"):
                continue

            endpoint_id = f"{service_name}_{details.get('operationId', path)}".replace("/", "_").replace(" ", "_")

            # Build rich text document for embedding
            summary = details.get("summary", "")
            description = details.get("description", "")
            params = _extract_params(details)
            auth_type = _extract_auth(details, spec)

            document = (
                f"Service: {service_name}\n"
                f"Endpoint: {method.upper()} {path}\n"
                f"Summary: {summary}\n"
                f"Description: {description}\n"
                f"Parameters: {params}\n"
                f"Authentication: {auth_type}"
            )

            metadata = {
                "service": service_name,
                "endpoint": path,
                "method": method.upper(),
                "summary": summary,
                "operation_id": details.get("operationId", ""),
                "auth_type": auth_type,
                "base_url": base_url,
                "params_json": params,
            }

            # Store request/response schema as metadata for code generation
            req_schema = _extract_request_schema(details)
            if req_schema:
                metadata["request_schema"] = json.dumps(req_schema)[:2000]

            resp_schema = _extract_response_schema(details)
            if resp_schema:
                metadata["response_schema"] = json.dumps(resp_schema)[:2000]

            documents.append(document)
            metadatas.append(metadata)
            ids.append(endpoint_id)

    if documents:
        collection.add(documents=documents, metadatas=metadatas, ids=ids)

    return len(documents)


def _extract_params(details: dict) -> str:
    """Extract parameters from endpoint details as readable string."""
    params = []

    # Query/path parameters
    for p in details.get("parameters", []):
        name = p.get("name", "")
        required = "required" if p.get("required") else "optional"
        desc = p.get("description", "")
        params.append(f"{name} ({required}): {desc}")

    # Request body
    body = details.get("requestBody", {})
    if body:
        content = body.get("content", {})
        for content_type, schema_info in content.items():
            schema = schema_info.get("schema", {})
            props = schema.get("properties", {})
            required_fields = schema.get("required", [])
            for prop_name, prop_details in props.items():
                req = "required" if prop_name in required_fields else "optional"
                desc = prop_details.get("description", prop_details.get("type", ""))
                params.append(f"{prop_name} ({req}): {desc}")

    return "; ".join(params) if params else "No parameters"


def _extract_auth(details: dict, spec: dict) -> str:
    """Extract authentication type."""
    security = details.get("security", spec.get("security", []))
    if not security:
        return "none"

    for sec in security:
        for key in sec:
            schemes = spec.get("components", {}).get("securitySchemes", {})
            if key in schemes:
                scheme = schemes[key]
                return scheme.get("type", "unknown") + "/" + scheme.get("scheme", key)

    return "unknown"


def _extract_request_schema(details: dict) -> dict | None:
    """Extract request body schema."""
    body = details.get("requestBody", {})
    content = body.get("content", {})
    for ct, schema_info in content.items():
        return schema_info.get("schema")
    return None


def _extract_response_schema(details: dict) -> dict | None:
    """Extract response schema from 200/201 responses."""
    responses = details.get("responses", {})
    for code in ("200", "201"):
        if code in responses:
            content = responses[code].get("content", {})
            for ct, schema_info in content.items():
                return schema_info.get("schema")
    return None
