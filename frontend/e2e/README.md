# Browser end-to-end suite

Playwright drives the built control board with `/api/**` and `/healthz`
intercepted by route mocks. No solver, database or worker is needed.

Coverage:

- `hidden-instance.spec.ts` – AT-15. Uploads a held-out eight-CSV instance and
  drives Ingest to Export, including the validator gate and the export download.
- `keyboard.spec.ts` – arrow, Home and End navigation, locked tabs skipped and
  disabled, and automatic focus into the newly shown panel.
- `responsive.spec.ts` – 1440x900, 1024x768 and 390x844. No horizontal page
  overflow and the tab rail scrolls on narrow screens.

## Run locally

```sh
npm run test:e2e
```

The config starts the built app with `npm run build && npm run preview` on a
fixed port. The same suite is available as `make web-e2e`.

## NixOS

Playwright's bundled browser download may be unavailable on NixOS. Pass a
Nix-provided chromium through the shell so the config finds it on `PATH`:

```sh
nix shell nixpkgs#nodejs_22 nixpkgs#chromium -c npm run test:e2e
```

To point at any other chromium build, set the executable explicitly:

```sh
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/path/to/chromium npm run test:e2e
```

Only Nix store paths are auto-detected. Everywhere else, including CI,
Playwright uses its own downloaded browser.
