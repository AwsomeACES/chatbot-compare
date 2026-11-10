## What changed

Summarise the behaviour change and name the task or issue it addresses.

## Tests

Paste the commands you ran and their results. See the change-to-test table in
[docs/Rules.md](../docs/Rules.md#tests-and-definition-of-done).

```text
python -m pytest <targeted tests> -q
python -m ruff check <changed paths>
python -m ruff format --check <changed paths>
```

## Checklist

- [ ] Implemented versus Planned boundaries stay truthful in code and documents.
- [ ] No check was turned from **Not tested** into a pass without new evidence.
- [ ] Unknown cost, usage or billing stays **Unknown**, never zero.
- [ ] No credential, real transcript or workstation path was added to the repository.
- [ ] Black-box code reads no target source; Gray and White inputs stay in their own paths.
- [ ] Documents updated where behaviour changed, and `python scripts/check_docs.py` passes.
