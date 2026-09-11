from deployments.target_writer import merge_targets_payload


def test_merge_keeps_other_strategy_signal_timestamps():
    previous = {
        "signal_timestamp": "2026-09-10T20:00:00Z",
        "strategies": [
            {
                "strategy_id": "id18",
                "signal_timestamp": "2026-09-10T20:00:00Z",
                "rebalance": True,
                "targets": {"SPY": 0.5, "TLT": -0.5},
            },
            {
                "strategy_id": "id13",
                "signal_timestamp": "2026-09-10T18:00:00Z",
                "rebalance": False,
                "targets": {"BTCUSDT": 1.0},
            },
        ],
    }
    payload = {
        "signal_timestamp": "2026-09-11T20:00:00Z",
        "strategies": [
            {
                "strategy_id": "id13",
                "signal_timestamp": "2026-09-11T20:00:00Z",
                "rebalance": False,
                "targets": {"BTCUSDT": 1.0},
            }
        ],
    }
    merged = merge_targets_payload(previous, payload)
    by_id = {row["strategy_id"]: row for row in merged["strategies"]}
    assert by_id["id18"]["signal_timestamp"] == "2026-09-10T20:00:00Z"
    assert by_id["id18"]["targets"]["SPY"] == 0.5
    assert by_id["id13"]["signal_timestamp"] == "2026-09-11T20:00:00Z"
    assert merged["signal_timestamp"] == "2026-09-11T20:00:00Z"


def test_merge_accepts_legacy_weights_map():
    previous = {"id18": {"GLD": -1.0}}
    payload = {
        "signal_timestamp": "2026-09-11T20:00:00Z",
        "strategies": [
            {
                "strategy_id": "id19",
                "signal_timestamp": "2026-09-11T20:00:00Z",
                "rebalance": True,
                "targets": {"USO": 1.0},
            }
        ],
    }
    merged = merge_targets_payload(previous, payload)
    by_id = {row["strategy_id"]: row for row in merged["strategies"]}
    assert by_id["id18"]["targets"] == {"GLD": -1.0}
    assert by_id["id19"]["targets"] == {"USO": 1.0}
    assert by_id["id19"]["signal_timestamp"] == "2026-09-11T20:00:00Z"
