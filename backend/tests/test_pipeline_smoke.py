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
