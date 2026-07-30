# Contributing

## Development setup

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest --cov=support_desk --cov-report=term-missing
```

Changes to approval logic must include tests for repeated requests and failed
side effects. New integrations should be adapters behind the approval boundary;
model output must never execute an external action directly.
