# BaluHost Marketplace Submission

This is a one-time manual process performed after a successful release.

## Steps

1. **Fork** `Xveyn/BaluHost-Plugin-Market` on GitHub.

2. **Add the plugin entry** to `plugins/index.json`. Use an existing entry as a template. The required fields:

```json
{
  "name": "balu_code",
  "display_name": "Balu Code",
  "version": "0.1.0",
  "description": "Self-hosted coding agent backed by Ollama. Provides a terminal CLI and a web settings panel.",
  "author": "Xveyn",
  "category": "general",
  "homepage": "https://github.com/Xveyn/Balu_Code",
  "min_baluhost_version": "1.30.0",
  "bundle_url": "https://github.com/Xveyn/Balu_Code/releases/download/v0.1.0/balu_code-0.1.0.bhplugin",
  "checksum_sha256": "<sha256 of the .bhplugin file>"
}
```

   Compute the checksum:

   ```bash
   sha256sum dist/balu_code-0.1.0.bhplugin
   ```

3. **Open a PR** against `Xveyn/BaluHost-Plugin-Market` main with the title: `feat: add balu_code 0.1.0`.
