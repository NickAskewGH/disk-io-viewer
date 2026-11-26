default:
    @just --list

# Install dependencies from uv.lock.
sync:
    uv sync --locked

# Lint Python files.
lint:
    uv run --locked ruff check .

# Format Python files.
format:
    uv run --locked ruff format .

# Check lint and formatting.
check: lint
    uv run --locked ruff format --check .

# Launch the viewer with the local configuration.
run config="disk-io.toml":
    uv run --locked python -m disk_io_viewer --config {{quote(config)}}

# Run sampling, configuration and chart tests.
test:
    uv run --locked python -m unittest discover -s tests

# Build the standalone Linux viewer and seed its editable device list.
build:
    #!/bin/sh
    set -eu
    uv run --locked --group build python -m PyInstaller --onefile \
        --name disk-io-viewer --specpath build --paths . disk_io_viewer/__main__.py
    if [ ! -e dist/disk-io.toml ]; then
        config=disk-io.toml
        if [ ! -f "$config" ]; then
            config=disk-io.example.toml
        fi
        cp "$config" dist/disk-io.toml
    fi
