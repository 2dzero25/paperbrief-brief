#!/bin/sh
# Start PaperBrief on 127.0.0.1 and open the browser. Needs uv (https://docs.astral.sh/uv/).
cd "$(dirname "$0")" || exit 1
exec uv run python -m paperbrief
