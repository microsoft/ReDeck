<!-- BEGIN MICROSOFT SECURITY.MD V1.0.0 BLOCK -->

## Security

Microsoft takes the security of our software products and services seriously, which
includes all source code repositories in our GitHub organizations.

**Please do not report security vulnerabilities through public GitHub issues.**

For security reporting information, locations, contact information, and policies,
please review the latest guidance for Microsoft repositories at
[https://aka.ms/SECURITY.md](https://aka.ms/SECURITY.md).

<!-- END MICROSOFT SECURITY.MD BLOCK -->

## Current Runtime Boundaries

- The current renderer disables page JavaScript and HTTP(S) resource fetching. This is not
  an OS sandbox: browsers can still read local files. Run untrusted HTML in a disposable
  container or VM without credentials or unrelated host mounts; inspect PNGs or image-only
  galleries rather than opening arbitrary HTML in an unrestricted browser.
- Source documents are sent to the configured model provider. Prompts, source excerpts,
  responses and local paths are saved in run artifacts; treat those as sensitive data.
- Keep API credentials in the environment. `.env.example` contains placeholders only;
  it is not automatically loaded. Ignoring files does not remove them from Git history.
- Content repair uses frozen source inventories and scoped evidence checks, not a universal
  factual verifier. Missing checks and worker errors are not passes. Human review remains required.
- The bundled content worker can be overridden with a trusted checkout/interpreter. Such an
  override executes local code and is not a plugin sandbox or an automatic dependency download.
- Do not export private source packs, raw run logs or third-party materials without authorization.
  Repository licensing does not automatically cover third-party materials. Review PyMuPDF's
  AGPL/commercial dual-license terms for the intended use and distribution.

## Showcase Boundaries

Website and video assets are separate from runtime inputs and are excluded from Python packages.
See the [example details](demo/repair_pairs/README.md) and
[video content](redeck-video/README.md) for their sources and editing history.
