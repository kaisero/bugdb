#!/usr/bin/env bash
# Rebuild the minified Tailwind CSS bundle that ships with the static site.
#
# Reads:
#   tools/tailwind.config.js   — content globs + theme extensions
#   tools/tailwind.input.css   — `@tailwind base; @tailwind components; @tailwind utilities;`
#   src/bugdb/templates/index.html
#   src/bugdb/templates/assets/app.js
#
# Writes:
#   src/bugdb/templates/assets/tailwind.css  (minified, ~15 KB)
#
# The CSS is committed to the repo so `bugdb build` doesn't need Node.js
# at runtime. Only regeneration does, and only when HTML/JS adds or
# removes Tailwind utility classes.
#
# Requires: Node.js (any recent version) + network access for `npx` to
# fetch `tailwindcss@3.4.17` on first run. The standalone CLI is ~30 MB.

set -euo pipefail

# Resolve repo root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

OUTPUT="src/bugdb/templates/assets/tailwind.css"

echo "[rebuild-tailwind] Running tailwindcss v3.4.17 via npx..."
npx --yes -p tailwindcss@3.4.17 tailwindcss \
    -c "tools/tailwind.config.js" \
    -i "tools/tailwind.input.css" \
    -o "${OUTPUT}" \
    --minify

echo "[rebuild-tailwind] Wrote $(wc -c < "${OUTPUT}") bytes to ${OUTPUT}"
