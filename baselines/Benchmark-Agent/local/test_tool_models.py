from tools.executor_tools import run_pure_tools
from tools.executor_tools.implementations import web_tools


def test_pure_planner_reads_config_and_preserves_override(monkeypatch):
    seen = []

    def fake(**kwargs):
        seen.append(kwargs["model"])
        return {"ok": True, "json": {"tool_args": {}}}

    monkeypatch.setattr(run_pure_tools, "llm_call_json", fake)
    monkeypatch.setattr(run_pure_tools, "get_tool_model", lambda name: "configured")
    run_pure_tools._llm_plan_pure_call({}, {}, {}, {"name": "test"})
    run_pure_tools._llm_plan_pure_call({}, {}, {}, {"name": "test"}, model="explicit")
    assert seen == ["configured", "explicit"]


def test_web_search_reads_config_and_keeps_tool_request(monkeypatch):
    from utils import model_config
    seen = []

    def fake(**kwargs):
        seen.append(kwargs)
        return {"ok": True, "json": {"answer": "test"}}

    monkeypatch.setattr(web_tools, "llm_call_json", fake)
    monkeypatch.setattr(model_config, "get_tool_model", lambda name: "configured")
    monkeypatch.setattr(model_config, "load_model_config", lambda: {
        "web_search_api": {"base_url": "https://search.example/v1", "api_key_env": "TEST_SEARCH_KEY"}
    })
    monkeypatch.setenv("TEST_SEARCH_KEY", "test-search-key")
    web_tools.web_search("test query")
    web_tools.web_search("test query", model="explicit")
    assert [x["model"] for x in seen] == ["configured", "explicit"]
    assert all(x["extra_create_params"]["tools"] == [{"type": "web_search", "search_context_size": "medium"}] for x in seen)
    assert all(x["extra_create_params"]["base_url"] == "https://search.example/v1" for x in seen)
    assert all(x["extra_create_params"]["api_key"] == "test-search-key" for x in seen)
