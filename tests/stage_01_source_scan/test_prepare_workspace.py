from tools.prepare_workspace import workspace_config


def test_workspace_config_contains_all_pre_model_pipeline_inputs():
    method = {
        "task_model": "provider/model",
        "embedding": {"model_id": "embedding/model"},
        "pipeline": {"extraction_workers": 1},
    }

    config = workspace_config(method, "https://example.invalid/v1/")

    assert config["api_base"] == "https://example.invalid/v1"
    assert config["candidate_config"] == (
        "repository/config/reference/candidate_generation.json"
    )
    assert config["bootstrap_embeddings"] == "offline_artifacts/embeddings"
    assert config["embedding"] is method["embedding"]
    assert config["pipeline"] is method["pipeline"]
