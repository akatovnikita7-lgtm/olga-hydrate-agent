# Integration verification — 2026-11-21

- Python 3.12 / Linux; `python -m pytest tests -q`: **86 passed**, one upstream AnyIO/pytest deprecation warning.
- Real stdio MCP server exercised with synthetic fake_olga subprocess: approved success, rejection without launching, failed solver, numerical export and image generation.
- Existing server tests cover stale/incomplete outputs, fingerprint changes, duplicate start calls, wrong approval, and server restart.
- LLM response is mocked in automated integration tests. No live Groq call was made.
- No real OLGA installation or license is available here. Windows command wrappers and actual solver launch require verification on the target laptop.
- User-supplied `case1_obhod(5).genkey` schedule parsed: ENDTIME 345600 s, event 172800 s, transition end 172860 s; valves and Pump match manifest.
- User-supplied `case1_obhod(1).tpl` parsed: 28 checkpoint metrics, all-series CSV, channel catalog, two plots and interval liquid-volume table generated; 6 samples in switching interval.
- Reading this historical export does not prove that the agent has executed OLGA. The archive intentionally does not contain the user's private model, PVT, API key, generated logs, virtual environment, or test artifacts.
- Engineering assessment remains NOT_ASSESSED: operating limits and acceptance criteria have not been supplied.

Integrated source heads:
- feat/agent-client: ab6f9135ef6aad5ae038734746443746ecc05754
- feat/olga-adapter: 6f052c4f7824f0af6e44684c0cc78d8f84008f77
- feat/results-analysis: 2a57bda33ac02b461c09c18d23701d225ccf660d

Main fixes: protocol mapping, adapter errors, solver environment forwarding, actual execution CLI, HMAC approval, adapter-to-analysis entry point, archive analysis CLI, Windows setup/run wrappers, missing dependencies, tests and instructions. The formerly import-executed test_reader is preserved as scripts/legacy_analysis_example.py; the supported path-independent exporter is scripts/analyze_export.py.
