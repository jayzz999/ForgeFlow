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
