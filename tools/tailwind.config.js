/**
 * Tailwind CSS build configuration for the bugdb static site.
 *
 * This file is consumed by `tools/rebuild-tailwind.sh`, which uses the
 * standalone tailwindcss CLI (via `npx --yes -p tailwindcss@3.4.17`) to
 * tree-shake the utilities actually used in the HTML + JS templates and
 * emit a minified CSS file at `src/bugdb/templates/assets/tailwind.css`.
 *
 * The generated CSS is committed to the repo — `bugdb build` and the
 * GitLab Pages deploy consume it verbatim. Node.js is only needed when
 * regenerating the CSS, not at runtime.
 *
 * Regenerate after any template or JS change that adds/removes Tailwind
 * utility classes:
 *
 *     bash tools/rebuild-tailwind.sh
 *
 * If a new utility class appears in the rendered page but not in the
 * generated CSS, it's because the `content` globs below didn't match the
 * file that contains it. Add the file and re-run.
 *
 * @type {import('tailwindcss').Config}
 */
module.exports = {
  content: [
    // Resolved relative to the working directory `tools/` is invoked from;
    // rebuild-tailwind.sh passes --cwd so these are repo-relative.
    'src/bugdb/templates/index.html',
    'src/bugdb/templates/assets/app.js',
  ],
  theme: {
    extend: {
      // Brand palette — previously lived in an inline `tailwind.config = {...}`
      // block in index.html, which blocked any meaningful CSP. Moving it here
      // keeps the exact same colors while allowing CSP to forbid inline script.
      colors: {
        'pan-orange': '#FA582D',
        'pan-dark': '#1A1A1A',
      },
    },
  },
  plugins: [],
};
