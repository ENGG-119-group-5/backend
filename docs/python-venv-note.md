# Python Virtual Environment

## Create

```bash
python -m venv .venv
```

## Activate

```bash
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate         # Windows
```

## Install packages

```bash
pip install <package>
```

## Save / restore dependencies

```bash
pip freeze > requirements.txt
pip install -r requirements.txt
```

## With a `pyproject.toml`

Dependencies live in `pyproject.toml` instead of `requirements.txt`.

```bash
pip install -e .               # install project + deps (editable)
pip install -e ".[dev]"        # include optional "dev" extras
```

Add a dependency by editing the `dependencies` list:

```toml
[project]
dependencies = ["requests>=2.31"]
```

Or with `uv` (creates `.venv` automatically):

```bash
uv sync                        # install from pyproject.toml
uv add requests                # add + install a dependency
```

## Deactivate

```bash
deactivate
```

> Tip: add `.venv/` to `.gitignore`.
