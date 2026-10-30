import pytest

from mcp_server.settings import Settings
from mcp_server.simulator import SimulatorClient, SimulatorNotConfigured


def test_unconfigured_client_reports_status() -> None:
    client = SimulatorClient(
        Settings(simulator_name="not-configured", simulator_model_path=None)
    )

    assert client.status()["status"] == "not_configured"


def test_template_does_not_fake_simulation_result() -> None:
    client = SimulatorClient(
        Settings(simulator_name="not-configured", simulator_model_path=None)
    )

    with pytest.raises(SimulatorNotConfigured):
        client.run_case(case_id="example", parameters={"pressure_bar": 100.0})
