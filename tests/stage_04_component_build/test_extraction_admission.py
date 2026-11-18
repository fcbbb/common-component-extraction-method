from component_method.component_build.run_extraction import packet_admission


def test_clean_extraction_is_completed():
    outcome = packet_admission([{"status": "ok"}, {"status": "ok"}])
    assert outcome == {
        "status": "completed",
        "successful_packets": 2,
        "invalid_packets": 0,
        "failed_packets": 0,
    }


def test_contract_rejections_are_admissible():
    # curate drops the rejected components; the packet itself is finished.
    outcome = packet_admission([
        {"status": "ok"},
        {"status": "invalid_contract"},
        {"status": "invalid_contract"},
    ])
    assert outcome == {
        "status": "completed_with_rejections",
        "successful_packets": 1,
        "invalid_packets": 2,
        "failed_packets": 0,
    }


def test_execution_failure_blocks_the_stage():
    outcome = packet_admission([{"status": "ok"}, {"status": "failed"}])
    assert outcome["status"] == "failed"
    assert outcome["failed_packets"] == 1