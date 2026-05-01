import pytest

from backend.shared.models import APIEndpoint, AuthType, ExecutionResult, WorkflowDAG, WorkflowStep


@pytest.mark.asyncio
async def test_pipeline_smoke_deploys_with_mocked_llm(monkeypatch, tmp_path):
    """Run the full graph with deterministic seams instead of paid LLM calls."""
    from backend import graph
    from backend.codegen import generator, test_generator, security_reviewer
    from backend.conversation import engine
    from backend.deployment import workflow_store
    from backend.discovery import api_selector, vector_store
    from backend.execution import sandbox
    from backend.planner import dag_builder, data_mapper

    workflow_store.WORKFLOWS_DIR = str(tmp_path / "workflows")
    workflow_store.DB_PATH = str(tmp_path / "forgeflow.db")
    graph._graph = None

    api = APIEndpoint(
        service="Slack",
        endpoint="/chat.postMessage",
        method="POST",
        description="Send a Slack message",
        auth_type=AuthType.BEARER,
        base_url="https://slack.com/api",
        confidence=0.95,
    )
    dag = WorkflowDAG(
        id="smoke",
        name="Smoke Workflow",
        description="Send a Slack message",
        trigger={"type": "manual"},
        steps=[
            WorkflowStep(
                id="step_1",
                name="Send Slack Message",
                description="Post a message to Slack",
                api=api,
                inputs={"channel": "#ops", "text": "hello"},
            )
        ],
        environment_vars=["SLACK_BOT_TOKEN"],
    )
    code = (
        "import asyncio\n\n"
        "async def step_1(context):\n"
        "    context['step_1'] = {'ok': True}\n"
        "    return context['step_1']\n\n"
        "async def main():\n"
        "    context = {}\n"
        "    await step_1(context)\n"
        "    print('ok')\n\n"
        "if __name__ == '__main__':\n"
        "    asyncio.run(main())\n"
    )

    async def fake_requirements(*args, **kwargs):
        return {
            "workflow_name": "Smoke Workflow",
            "description": "Send a Slack message",
            "confidence": 0.95,
            "actions": [
                {
                    "id": "step_1",
                    "description": "Post a message to Slack",
                    "service_hint": "Slack",
                    "depends_on": [],
                    "is_trigger": False,
                }
            ],
            "entities": [{"name": "Slack", "type": "messaging"}],
            "clarification_needed": [],
            "assumed_defaults": [],
        }

    async def fake_select_best_api(*args, **kwargs):
        return api

    async def fake_generate_code(*args, **kwargs):
        return code, {}

    async def fake_run_tests(*args, **kwargs):
        return {"passed": 1, "failed": 0, "errors": 0, "total": 1, "output": "ok", "success": True}

    async def fake_execute_code(*args, **kwargs):
        return ExecutionResult(success=True, stdout="ok", execution_time=0.01)

    async def fake_build_dag(*args, **kwargs):
        return dag

    async def fake_map_data_flows(*args, **kwargs):
        return []

    async def fake_review_code(*args, **kwargs):
        return {"safe": True, "findings": []}

    async def fake_generate_tests(*args, **kwargs):
        return "def test_ok(): assert True\n"

    monkeypatch.setattr(engine, "extract_requirements", fake_requirements)
    monkeypatch.setattr(engine, "generate_clarification", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(vector_store, "similarity_search", lambda *_args, **_kwargs: [{"metadata": {}, "confidence": 0.9}])
    monkeypatch.setattr(api_selector, "select_best_api", fake_select_best_api)
    monkeypatch.setattr(dag_builder, "build_dag", fake_build_dag)
    monkeypatch.setattr(data_mapper, "map_data_flows", fake_map_data_flows)
    monkeypatch.setattr(generator, "generate_workflow_code", fake_generate_code)
    monkeypatch.setattr(security_reviewer, "review_code", fake_review_code)
    monkeypatch.setattr(test_generator, "generate_tests", fake_generate_tests)
    monkeypatch.setattr(test_generator, "run_tests", fake_run_tests)
    monkeypatch.setattr(sandbox, "execute_code", fake_execute_code)

    result = await graph.run_forgeflow_pipeline(
        user_request="Send hello to #ops in Slack",
        workflow_id="smoke1",
        slack_channel="#ops",
    )

    assert result["deployed"] is True
    assert result["phase"] == "deployed"
    project = tmp_path / "workflows" / "smoke1"
    assert (project / "workflow.py").exists()
    assert (project / "artifacts" / "requirements.json").exists()
    assert (project / "artifacts" / "execution_result.json").exists()


@pytest.mark.asyncio
async def test_pipeline_stops_for_first_clarification(monkeypatch):
    from backend import graph
    from backend.conversation import engine
    from backend.discovery import vector_store

    graph._graph = None

    async def fake_requirements(*args, **kwargs):
        return {
            "workflow_name": "Vague Workflow",
            "description": "Needs more detail",
            "confidence": 0.3,
            "actions": [
                {
                    "id": "step_1",
                    "description": "Check a website",
                    "service_hint": "HTTP",
                    "depends_on": [],
                    "is_trigger": False,
                }
            ],
            "entities": [],
            "clarification_needed": ["What should happen after the check?"],
            "assumed_defaults": [],
        }

    def fail_if_discovery_runs(*args, **kwargs):
        raise AssertionError("pipeline should stop before API discovery")

    monkeypatch.setattr(engine, "extract_requirements", fake_requirements)
    async def fake_clarification(*args, **kwargs):
        return "What should happen after the check?"

    monkeypatch.setattr(engine, "generate_clarification", fake_clarification)
    monkeypatch.setattr(vector_store, "similarity_search", fail_if_discovery_runs)

    result = await graph.run_forgeflow_pipeline(
        user_request="monitor a website",
        workflow_id="clarify1",
    )

    assert result["needs_clarification"] is True
    assert result["phase"] == "collecting"
    assert result["workflow_dag"] is None


@pytest.mark.asyncio
async def test_pipeline_fails_before_codegen_for_empty_dag(monkeypatch):
    from backend import graph
    from backend.conversation import engine
    from backend.discovery import api_selector, vector_store
    from backend.planner import dag_builder, data_mapper
    from backend.shared.models import WorkflowDAG

    graph._graph = None

    async def fake_requirements(*args, **kwargs):
        return {
            "workflow_name": "Empty DAG",
            "description": "No executable actions",
            "confidence": 0.95,
            "actions": [],
            "entities": [],
            "clarification_needed": [],
            "assumed_defaults": [],
        }

    async def fake_build_dag(*args, **kwargs):
        return WorkflowDAG(
            id="empty",
            name="Empty DAG",
            description="No executable actions",
            trigger={"type": "manual"},
            steps=[],
        )

    async def fail_if_codegen_runs(*args, **kwargs):
        raise AssertionError("pipeline should stop before code generation")

    monkeypatch.setattr(engine, "extract_requirements", fake_requirements)
    monkeypatch.setattr(vector_store, "similarity_search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(api_selector, "select_best_api", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dag_builder, "build_dag", fake_build_dag)
    monkeypatch.setattr(data_mapper, "map_data_flows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("backend.codegen.generator.generate_workflow_code", fail_if_codegen_runs)

    result = await graph.run_forgeflow_pipeline(
        user_request="do nothing",
        workflow_id="empty1",
    )

    assert result["phase"] == "failed"
    assert result["deployed"] is False
    assert result["generated_code"] is None
    assert "no executable steps" in result["final_message"]


@pytest.mark.asyncio
async def test_http_prompt_falls_back_when_llm_is_unavailable(monkeypatch):
    from backend.conversation import engine

    async def fail_generate_json(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(engine, "generate_json", fail_generate_json)

    requirements = await engine.extract_requirements(
        "GET https://example.com, measure latency_ms, print status_code and healthy JSON. Do not ask questions."
    )

    assert requirements["workflow_name"] == "HTTP Health Check"
    assert requirements["confidence"] > 0.9
    assert requirements["clarification_needed"] == []
    assert requirements["actions"][0]["service_hint"] == "HTTP"
    assert requirements["actions"][0]["inputs"]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_http_fallback_dag_gets_real_api(monkeypatch):
    from backend.planner import dag_builder

    async def fail_generate_json(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(dag_builder, "generate_json", fail_generate_json)

    dag = await dag_builder.build_dag(
        {
            "workflow_name": "HTTP Health Check",
            "description": "Check example.com",
            "actions": [
                {
                    "id": "step_1",
                    "description": "Send an HTTP GET request to https://example.com",
                    "service_hint": "HTTP",
                    "api_type": "http_check",
                    "inputs": {"url": "https://example.com"},
                }
            ],
        },
        [],
    )

    assert len(dag.steps) == 1
    assert dag.steps[0].api is not None
    assert dag.steps[0].api.service == "HTTP"
    assert dag.steps[0].api.auth_type == AuthType.NONE
    assert dag.steps[0].inputs["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_http_fallback_codegen_is_runnable_code(monkeypatch):
    from backend.codegen import generator

    async def fail_generate_with_tools(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    async def fail_generate_text(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(generator, "generate_with_tools", fail_generate_with_tools)
    monkeypatch.setattr(generator, "generate_text", fail_generate_text)

    dag = WorkflowDAG(
        id="http",
        name="HTTP Health Check",
        description="Check example.com",
        trigger={"type": "manual"},
        steps=[
            WorkflowStep(
                id="step_1",
                name="GET example.com",
                description="Send an HTTP GET request to https://example.com",
                api=APIEndpoint(
                    service="HTTP",
                    endpoint="https://example.com",
                    method="GET",
                    description="Generic HTTP GET health check",
                    auth_type=AuthType.NONE,
                    base_url="https://example.com",
                ),
                inputs={"url": "https://example.com"},
            )
        ],
    )

    code, extra_files = await generator.generate_workflow_code(dag, [])

    assert extra_files == {}
    assert "await client.get(url)" in code
    assert '"latency_ms": latency_ms' in code
    assert '"status_code": response.status_code' in code
    assert "asyncio.run(main())" in code


def test_codegen_detects_dry_run_workflows():
    from backend.codegen.generator import _is_dry_run_workflow

    dag = WorkflowDAG(
        id="hr",
        name="HR Onboarding Dry Run",
        description="Draft messages locally without sending or calling external APIs",
        trigger={"type": "manual"},
        steps=[
            WorkflowStep(
                id="step_1",
                name="Draft Slack announcement",
                description="Draft without posting to Slack",
            )
        ],
    )

    assert _is_dry_run_workflow(dag) is True


def test_generated_tests_import_workflow_module():
    from backend.codegen.test_generator import _normalize_generated_test_imports

    test_code = "import __main__ as workflow_module  # generated mistake\n\n"

    assert _normalize_generated_test_imports(test_code) == "import workflow as workflow_module\n\n"


@pytest.mark.asyncio
async def test_builder_preflight_blocks_missing_google_credentials(monkeypatch):
    from backend import graph

    events = []
    dag = WorkflowDAG(
        id="google",
        name="Google Workflow",
        description="Send Gmail and append a Sheets row",
        trigger={"type": "manual"},
        steps=[
            WorkflowStep(
                id="step_1",
                name="Send Gmail",
                description="Send a welcome email",
                api=APIEndpoint(
                    service="Gmail",
                    endpoint="/gmail/v1/users/me/messages/send",
                    method="POST",
                    description="Send Gmail",
                    auth_type=AuthType.OAUTH2,
                    base_url="https://gmail.googleapis.com",
                ),
            ),
            WorkflowStep(
                id="step_2",
                name="Append row",
                description="Append onboarding tracker row",
                api=APIEndpoint(
                    service="Google Sheets",
                    endpoint="/spreadsheets/{id}/values:append",
                    method="POST",
                    description="Append row",
                    auth_type=AuthType.OAUTH2,
                    base_url="https://sheets.googleapis.com",
                ),
            ),
        ],
    )

    for key in ("GMAIL_ACCESS_TOKEN", "GMAIL_SENDER_EMAIL", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "GOOGLE_SHEETS_ACCESS_TOKEN", "GOOGLE_API_KEY", "GOOGLE_SHEET_ID"):
        monkeypatch.delenv(key, raising=False)

    async def collect(event):
        events.append(event)

    result = await graph.credential_preflight_node({
        "workflow_dag": dag.model_dump(),
        "phase": "testing",
        "_event_callback": collect,
    })

    assert result["phase"] == "awaiting_credentials"
    assert result["credential_preflight"]["blocked"] is True
    assert {item["service"] for item in result["credential_preflight"]["missing"]} == {"gmail", "sheets"}
    assert events[0]["event_type"] == "credentials.required"


def test_test_support_files_are_materialized(tmp_path):
    from backend.codegen.test_generator import materialize_extra_files

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    materialize_extra_files(
        str(project_dir),
        {"clients/slack_client.py": "class SlackClient:\n    pass\n"},
    )

    assert (project_dir / "clients" / "__init__.py").exists()
    assert (project_dir / "clients" / "slack_client.py").exists()


@pytest.mark.asyncio
async def test_dry_run_test_generation_is_deterministic():
    from backend.codegen.test_generator import generate_tests

    dag = WorkflowDAG(
        id="hr",
        name="HR Dry Run",
        description="Draft onboarding messages locally as a dry run without external APIs",
        trigger={"type": "manual"},
        steps=[
            WorkflowStep(
                id="step_1",
                name="Draft welcome email",
                description="Draft welcome email without sending",
            )
        ],
    )
    code = (
        "async def step_1_draft_welcome_email(context):\n"
        "    context['step_1'] = {'ok': True}\n\n"
        "async def main():\n"
        "    context = {}\n"
        "    await step_1_draft_welcome_email(context)\n"
        "    print('ok')\n"
    )

    test_code = await generate_tests(dag, code)

    assert "import workflow as workflow_module" in test_code
    assert "test_dry_run_does_not_require_credentials_or_network_clients" in test_code
    assert "generate_text" not in test_code


def test_schema_inspector_maps_csv_columns():
    from backend.main import _inspect_tabular_bytes

    payload = (
        "Employee Name,Joining Date,Department,Reporting Manager,Personal Email\n"
        "Alex Rivera,2026-05-15,Product,Priya Shah,alex@example.com\n"
    ).encode()

    schema = _inspect_tabular_bytes("new_hires.csv", payload)

    assert schema["columns"] == [
        "Employee Name",
        "Joining Date",
        "Department",
        "Reporting Manager",
        "Personal Email",
    ]
    assert schema["sample_rows"][0]["Employee Name"] == "Alex Rivera"
    assert schema["mapping_suggestions"]["person_name"] == "Employee Name"
    assert schema["mapping_suggestions"]["start_date"] == "Joining Date"
    assert schema["mapping_suggestions"]["manager"] == "Reporting Manager"
    assert schema["mapping_suggestions"]["email"] == "Personal Email"


@pytest.mark.asyncio
async def test_preflight_identifies_schema_and_missing_credentials(monkeypatch):
    from backend import main

    async def fake_provider_status():
        return {
            "services": {
                "slack": {"name": "Slack", "configured": False, "required_env": ["SLACK_BOT_TOKEN"]},
                "gmail": {"name": "Gmail", "configured": True, "required_env": ["GMAIL_ACCESS_TOKEN"]},
                "sheets": {"name": "Google Sheets", "configured": False, "required_env": ["GOOGLE_SHEETS_ACCESS_TOKEN"]},
                "http": {"name": "HTTP", "configured": True, "required_env": []},
            }
        }

    monkeypatch.setattr(main, "provider_status", fake_provider_status)

    result = await main.preflight_prompt({
        "prompt": "Automate HR onboarding from an Excel sheet and post to Slack",
    })

    assert result["schema_needed"] is True
    assert {item["service"] for item in result["missing_credentials"]} == {"slack", "sheets"}
    assert "schema_required_to_avoid_hallucinated_fields" in result["risks"]


@pytest.mark.asyncio
async def test_dry_run_codegen_stays_single_file(monkeypatch):
    from backend.codegen import generator

    captured = {}

    async def fake_generate_with_tools(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return (
            "import asyncio\n\n"
            "async def main():\n"
            "    print({'ok': True})\n\n"
            "if __name__ == '__main__':\n"
            "    asyncio.run(main())\n",
            {},
        )

    monkeypatch.setattr(generator, "generate_with_tools", fake_generate_with_tools)

    dag = WorkflowDAG(
        id="hr",
        name="HR Onboarding Dry Run",
        description="Draft messages locally without sending or calling external APIs",
        trigger={"type": "manual"},
        steps=[
            WorkflowStep(
                id="step_1",
                name="Draft welcome email",
                description="Draft welcome email without sending",
            ),
            WorkflowStep(
                id="step_2",
                name="Draft Slack announcement",
                description="Draft Slack announcement without posting",
            ),
            WorkflowStep(
                id="step_3",
                name="Append local tracking record",
                description="Append local in-memory tracking record",
            ),
        ],
    )

    _code, extra_files = await generator.generate_workflow_code(dag, [])

    assert extra_files == {}
    assert "DRY RUN MODE: true" in captured["prompt"]
    assert "SINGLE-FILE" in captured["prompt"]


def test_openapi_ingestion_extracts_grounded_capabilities():
    from backend import main

    capabilities = main._extract_openapi_capabilities({
        "openapi": "3.0.0",
        "info": {"title": "HR Platform", "version": "1.0"},
        "paths": {
            "/candidates": {"get": {"operationId": "listCandidates", "summary": "List candidates"}},
            "/employees": {"post": {"operationId": "createEmployee", "summary": "Create employee"}},
        },
    })

    assert [item["id"] for item in capabilities] == ["openapi.listCandidates", "openapi.createEmployee"]
    assert capabilities[0]["risk"] == "network_call"
    assert capabilities[1]["risk"] == "external_write"
    assert capabilities[1]["description"] == "POST /employees"


def test_mcp_ingestion_extracts_tools():
    from backend import main

    capabilities = main._extract_mcp_capabilities({
        "name": "hr-records-mcp",
        "tools": [
            {
                "name": "lookup_employee",
                "description": "Find an employee by email",
                "input_schema": {"email": "string"},
            }
        ],
    })

    assert capabilities == [
        {
            "id": "mcp.lookup_employee",
            "label": "Lookup Employee",
            "category": "hr-records-mcp",
            "risk": "tool_call",
            "requires_auth": [],
            "description": "Find an employee by email",
            "dry_run": True,
            "source": "mcp",
            "input_schema": {"email": "string"},
        }
    ]


def test_public_api_directory_search_ranks_openapi_candidates():
    from backend import main

    catalog = {
        "example.com": {
            "preferred": "v1",
            "versions": {
                "v1": {
                    "swaggerUrl": "https://example.com/openapi.json",
                    "info": {"title": "Ticket Desk", "description": "Create customer support tickets and update ticket status"},
                }
            },
        },
        "payments.com": {
            "preferred": "v1",
            "versions": {
                "v1": {
                    "swaggerUrl": "https://payments.example/openapi.json",
                    "info": {"title": "Payments", "description": "Create charges and refunds"},
                }
            },
        },
    }

    results = main._api_guru_candidates_from_catalog("create support ticket for customer", catalog)

    assert results[0]["title"] == "Ticket Desk"
    assert results[0]["source_url"] == "https://example.com/openapi.json"
    assert "ticket" in results[0]["matched_terms"]


@pytest.mark.asyncio
async def test_preflight_uses_imported_openapi_capabilities(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))
    main._store_ingestion(
        "openapi",
        "Ticket Desk",
        {"title": "Ticket Desk"},
        [{
            "id": "openapi.createTicket",
            "label": "Create Support Ticket",
            "category": "Ticket Desk",
            "risk": "external_write",
            "requires_auth": [],
            "description": "POST /tickets",
            "source": "openapi",
            "method": "POST",
            "path": "/tickets",
        }],
    )

    result = await main.preflight_prompt({"prompt": "create a support ticket for a customer issue"})

    assert any(item["capability_id"] == "openapi.createTicket" for item in result["dynamic_capabilities"])
    assert any(item["id"] == "openapi.createTicket" for item in result["capability_matches"])


@pytest.mark.asyncio
async def test_persistent_approval_queue_roundtrip(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    created = await main.create_approval({
        "title": "Send Slack announcement",
        "workflow_id": "workflow_hr",
        "action_type": "slack.postMessage",
        "risk": "external_write",
        "preview": {"channel": "#hr", "text": "Welcome"},
    })
    queue = await main.approvals()

    assert created["status"] == "pending"
    assert queue["pending"][0]["title"] == "Send Slack announcement"
    assert queue["pending"][0]["preview"] == {"channel": "#hr", "text": "Welcome"}

    decided = await main.decide_approval(created["id"], "approve")
    queue = await main.approvals()

    assert decided["status"] == "approved"
    assert queue["pending"] == []


@pytest.mark.asyncio
async def test_trigger_and_deployment_plan_are_persisted(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    trigger = await main.create_trigger({
        "workflow_id": "workflow_hr",
        "trigger_type": "webhook",
        "config": {"path": "/webhooks/hr"},
    })
    triggers = await main.list_triggers()
    plan = await main.create_deployment_plan({"workflow_id": "workflow_hr", "target": "local_docker"})

    assert trigger["status"] == "paused"
    assert triggers["triggers"][0]["config"] == {"path": "/webhooks/hr"}
    assert plan["status"] == "planned"
    assert plan["plan"]["steps"][-1] == "Activate trigger or runtime"


@pytest.mark.asyncio
async def test_connector_oauth_lifecycle_records_callback(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))
    monkeypatch.setenv("SLACK_CLIENT_ID", "client-id")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SLACK_OAUTH_REDIRECT_URI", "http://localhost/callback")

    started = await main.start_oauth_connector("slack")
    lifecycle = await main.connector_lifecycle()
    completed = await main.complete_oauth_connector({"state": started["state"], "code": "temporary-code"})
    lifecycle_after = await main.connector_lifecycle()

    assert started["status"] == "ready_for_user_authorization"
    assert "client-id" in started["auth_url"]
    assert lifecycle["oauth_sessions"][0]["status"] == "started"
    assert completed["status"] == "authorization_code_received"
    assert lifecycle_after["oauth_sessions"][0]["status"] == "callback_received"


@pytest.mark.asyncio
async def test_trigger_activation_and_inactive_webhook_event(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    trigger = await main.create_trigger({
        "workflow_id": "workflow_hr",
        "trigger_type": "webhook",
        "config": {"path": "/webhooks/hr"},
    })
    inactive = await main.invoke_webhook_trigger(trigger["id"], {"candidate": "Ada"})
    active = await main.update_trigger_state(trigger["id"], "activate")
    events = await main.trigger_events()

    assert inactive["accepted"] is False
    assert inactive["event"]["status"] == "ignored_inactive"
    assert active["status"] == "active"
    assert events["events"][0]["payload"] == {"candidate": "Ada"}


@pytest.mark.asyncio
async def test_active_webhook_queues_missing_workflow(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    trigger = await main.create_trigger({
        "workflow_id": "missing_workflow",
        "trigger_type": "webhook",
        "config": {"path": "/webhooks/missing"},
    })
    await main.update_trigger_state(trigger["id"], "activate")
    result = await main.invoke_webhook_trigger(trigger["id"], {"event": "test"})
    events = await main.trigger_events()

    assert result["accepted"] is True
    assert result["event"]["status"] == "queued"
    assert result["queue"]["status"] == "queued"
    assert events["events"][0]["run_id"] == result["queue"]["id"]


def test_product_gap_analysis_reports_score(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    gaps = main._product_gap_analysis()

    assert 0 <= gaps["score"] <= 100
    assert {check["id"] for check in gaps["checks"]} >= {"grounded_capabilities", "connector_credentials", "approval_queue"}


def test_credential_vault_encrypts_and_masks(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))
    monkeypatch.setenv("FORGEFLOW_VAULT_KEY", "unit-test-vault-key")

    stored = main._store_credential("slack", "Unit token", "access_token", "xoxb-secret-token")
    credentials = main._list_credentials()

    assert stored["masked"] == "xox...ken"
    assert credentials[0]["masked"] == "xox...ken"
    assert credentials[0]["valid"] is True
    assert "xoxb-secret-token" not in str(credentials)


@pytest.mark.asyncio
async def test_run_queue_records_failed_attempt_for_missing_workflow(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    queued = main._enqueue_run("missing_workflow", {"source": "test"}, max_attempts=1)
    processed = await main._process_queue_item(queued["id"])
    queue = main._list_run_queue()
    run = await main.run_detail(processed["run"]["run_id"])

    assert processed["queue_status"] == "dead_letter"
    assert queue[0]["status"] == "dead_letter"
    assert queue[0]["last_error"] == "Workflow not found"
    assert queue[0]["dead_letter_reason"] == "Workflow not found"
    assert run["stderr"] == "Workflow not found"


@pytest.mark.asyncio
async def test_eval_suite_records_quality_run(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    result = await main._run_eval_suite("core")
    runs = main._list_eval_runs()

    assert result["suite"] == "core"
    assert len(result["cases"]) == 3
    assert 0 <= result["score"] <= 1
    assert runs[0]["id"] == result["id"]


def test_deployment_activation_is_recorded(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    activation = main._record_deployment_activation(
        "plan_1",
        {
            "workflow_id": "workflow_1",
            "target": "github_actions",
            "artifacts": {".github/workflows/forgeflow.yml": "name: test"},
            "readiness": {"blocking": ["workflow_project_missing"]},
        },
        "blocked",
    )
    activations = main._list_deployment_activations()

    assert activation["status"] == "blocked"
    assert activations[0]["artifacts"] == {".github/workflows/forgeflow.yml": "name: test"}
    assert activations[0]["blockers"] == ["workflow_project_missing"]


@pytest.mark.asyncio
async def test_oauth_callback_exchanges_and_stores_tokens(monkeypatch, tmp_path):
    from backend import main

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"access_token":"ya29-access-token","refresh_token":"refresh-secret","expires_in":3600}'

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr(main, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    started = await main.start_oauth_connector("gmail")
    completed = await main.complete_oauth_connector({
        "state": started["state"],
        "code": "provider-code",
        "exchange": True,
    })
    credentials = main._list_credentials()

    assert completed["status"] == "tokens_stored"
    assert {item["kind"] for item in completed["token_exchange"]["stored_credentials"]} == {"access_token", "refresh_token"}
    assert {item["kind"] for item in credentials} == {"access_token", "refresh_token"}
    assert "ya29-access-token" not in str(completed)


def test_deployment_dispatch_records_provider_request(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    job = main._record_deployment_job(
        "plan_1",
        {
            "workflow_id": "workflow_1",
            "target": "render_worker",
            "artifacts": {"render.yaml": "services: []"},
            "readiness": {"blocking": ["target_credentials_missing"]},
        },
        "dry_run",
    )
    jobs = main._list_deployment_jobs()

    assert job["status"] == "blocked"
    assert jobs[0]["provider_request"]["provider"] == "render"
    assert jobs[0]["provider_request"]["operation"] == "create_or_update_worker_blueprint"
    assert jobs[0]["provider_response"]["live_call_performed"] is False


@pytest.mark.asyncio
async def test_compile_automation_spec_and_runtime_dry_run(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    spec = await main._compile_automation_spec(
        "Automate HR onboarding from an Excel sheet, send Gmail, post Slack, and append Google Sheets row."
    )
    run = await main._dry_run_automation_spec(spec["id"], {"candidate": "Ada"})
    specs = main._list_automation_specs()
    runtime_runs = main._list_runtime_runs()

    assert spec["id"] == specs[0]["id"]
    assert spec["trigger"]["type"] == "manual"
    assert {connector["id"] for connector in spec["connectors"]} >= {
        "schema.inspect_file",
        "gmail.send_email",
        "slack.post_message",
        "sheets.append_row",
    }
    assert any(step["approval_required"] for step in spec["steps"])
    assert run["mode"] == "dry_run"
    assert run["status"] in {"blocked", "waiting_for_approval", "succeeded"}
    assert len(runtime_runs[0]["steps"]) == len(spec["steps"])
    assert all(step["output"]["live_call_performed"] is False for step in runtime_runs[0]["steps"])


def test_connector_adapters_report_contract_methods(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    adapters = main._connector_adapters()
    slack = next(item for item in adapters if item["id"] == "slack.post_message")
    adapter_ids = {item["id"] for item in adapters}

    assert {"auth_check", "dry_run", "execute", "compensate"} <= set(slack["methods"])
    assert slack["risk"] == "external_write"
    assert {
        "hubspot.create_contact",
        "stripe.create_refund",
        "calendar.create_event",
        "okta.assign_group",
        "zendesk.create_ticket",
    } <= adapter_ids


def test_connector_tests_are_recorded_without_exposing_secret(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))
    monkeypatch.setenv("FORGEFLOW_VAULT_KEY", "unit-test-vault-key")

    missing = main._test_connector_service("stripe")
    main._store_credential("stripe", "Stripe test key", "api_key", "sk_test_secret")
    ready = main._test_connector_service("stripe", live=False)
    tests = main._list_connector_tests()

    assert missing["status"] == "missing_credentials"
    assert ready["status"] == "ready_to_probe"
    assert "sk_test_secret" not in str(tests)
    assert tests[0]["request"]["url"] == "https://api.stripe.com/v1/balance"


@pytest.mark.asyncio
async def test_due_queue_processor_marks_dead_letter(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    queued = main._enqueue_run("missing_workflow", {"source": "due-test"}, max_attempts=1)
    processed = await main._process_due_queue(limit=5)
    queue = main._list_run_queue()

    assert processed["count"] == 1
    assert processed["processed"][0]["queue_id"] == queued["id"]
    assert queue[0]["status"] == "dead_letter"
    assert queue[0]["dead_letter_reason"] == "Workflow not found"


def test_business_conversation_stays_non_technical():
    from backend import main

    result = main._business_conversation("Automate employee onboarding from an Excel sheet and send Gmail.")

    assert {"Gmail", "Google Sheets"} <= set(result["known_systems"])
    assert any("real schema" in item.lower() for item in result["process_steps"])
    assert any("upload or connect" in item.lower() for item in result["questions"])
    assert "No invented names, columns, or API fields." in result["non_technical_contract"]


@pytest.mark.asyncio
async def test_compile_spec_detects_catalog_connectors(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    spec = await main._compile_automation_spec(
        "When a refund is approved, create a Stripe refund, open a Zendesk ticket, and schedule a Google Calendar follow-up."
    )

    connector_ids = {connector["id"] for connector in spec["connectors"]}
    assert {"stripe.create_refund", "zendesk.create_ticket", "calendar.create_event"} <= connector_ids
    assert any(gate["preview_required"] for gate in spec["approval_gates"])


@pytest.mark.asyncio
async def test_hr_onboarding_demo_covers_challenge_loop(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    result = await main._run_hr_onboarding_demo()

    assert result["answer_to_challenge"]["live_generation"] is True
    assert result["answer_to_challenge"]["executable_output"] is True
    assert result["answer_to_challenge"]["human_oversight"] is True
    assert result["answer_to_challenge"]["live_external_calls_performed"] is False
    assert {item["platform"] for item in result["exports"]} == {"forgeflow", "n8n", "github_actions"}
    assert result["repair"]["actions"]
    assert main._list_workflow_exports(result["spec"]["id"])


def test_staging_profile_is_draft_first(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))
    monkeypatch.setenv("FORGEFLOW_STAGING_SLACK_CHANNEL", "#unit-staging")

    profile = main._staging_profile()

    assert profile["draft_first"] is True
    assert profile["approval_required_before_live"] is True
    assert any(item["destination"] == "#unit-staging" for item in profile["destinations"])
    assert {item["service"] for item in profile["destinations"]} >= {"gmail", "slack", "sheets", "calendar", "http"}


def test_app_builder_generates_playable_tic_tac_toe(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "APP_BUILDS_DIR", str(tmp_path / "app_builds"))

    build = main._generate_app_build("I need a tic tac toe playing game app with score tracking.")

    assert build["intent"]["lane"] == "app_builder"
    assert build["type"] == "game"
    assert {item["path"] for item in build["files"]} == {"index.html", "styles.css", "app.js"}
    assert "winningLine" in (tmp_path / "app_builds" / build["id"] / "app.js").read_text()
    assert "<iframe" not in build["preview_html"]
    assert main._list_app_builds()[0]["id"] == build["id"]


@pytest.mark.asyncio
async def test_judge_demo_covers_end_to_end_staging(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    result = await main._run_judge_demo("Automate employee onboarding from an HR sheet with Gmail, Slack, Sheets, Calendar, and approval.")

    assert result["complete"] is True
    assert result["deployment"]["live_deploy_performed"] is False
    assert all(item["live_call_performed"] is False for item in result["draft_first_plan"])
    assert all(item["approval_required"] is True for item in result["draft_first_plan"] if item["service"] not in {"schema", "approval"})
    assert {item["service"] for item in result["connector_checks"]} >= {"gmail", "slack", "sheets"}
    assert {item["platform"] for item in result["demo"]["exports"]} == {"forgeflow", "n8n", "github_actions"}
    assert result["worker"]["batch_size"] >= 1
    assert "sample_inputs" in result["scenario"]


@pytest.mark.asyncio
async def test_export_validate_and_repair_runtime_run(monkeypatch, tmp_path):
    from backend import main

    monkeypatch.setattr(main, "PLATFORM_DB_PATH", str(tmp_path / "forgeflow_platform.db"))

    spec = await main._compile_automation_spec("Send a Slack message when a spreadsheet row is added.")
    exported = main._export_spec_to_platform(spec["id"], "zapier")
    validation = main._validate_connector_adapter("slack.post_message")
    run = await main._dry_run_automation_spec(spec["id"], {"row": 1})
    repair = main._repair_runtime_run(run["id"])

    assert exported["artifact"]["format"] == "zapier.transfer.json"
    assert validation["checks"][0]["status"] == "pass"
    assert repair["run_id"] == run["id"]
    assert any(action["type"] in {"credential_request", "approval_gate", "no_repair_needed"} for action in repair["actions"])
