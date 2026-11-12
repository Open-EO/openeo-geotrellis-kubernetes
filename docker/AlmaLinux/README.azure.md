# Azure image build

Run **Azure openEO image** from the repository's GitHub Actions tab.
The [workflow](../../.github/workflows/openeo-geotrellis-kube-azure.yml) is
also runs automatically on PRs changing the Azure workflow, image recipe or
startup scripts. It does not change existing image pipelines or deployments.
PR runs build and test without logging into GHCR for publication or pushing an
image. Only manual runs with `publish` enabled can publish.

PR builds use `ubuntu-latest`, the default base image and backend `master`
(resolved to a commit). They check shell syntax, Azure imports, Spark startup,
runtime UID, the disabled custom-process hook and exit-code propagation.
They do not test Azure access or full distributed processing.
Fork PRs do not receive private-registry secrets; builds requiring those
credentials will fail rather than report a skipped build as successful.
Do not use `pull_request_target` to run untrusted PR Dockerfiles with secrets.

Inputs:

- `base_image`: defaults to
  `openeo-docker-local-prod.repo.vito.be/openeo-base-python311:latest`.
  You can override it with another tag or digest. The workflow resolves it to
  an immutable digest before building and records that digest in the summary.
  The base must include
  `/opt/venv`, Spark, Java, tini, the GeoTrellis/logging JARs and the `spark`
  user (UID 18585).
- `driver_ref`: defaults to `master`, resolved to a full backend commit SHA before
  building and recorded in the summary. Override with a full commit SHA to pin
  a revision. Until Azure job storage is merged into master, explicitly select
  a commit containing it; this default does not guarantee feature availability.
- `runner`: defaults to `ubuntu-latest`. Use a suitable self-hosted runner label
  if the base registry requires private network access. The runner must support
  Linux amd64 Docker builds and execution.
- `publish`: defaults to false. Enable to push the tested image to
  `ghcr.io/<repository-owner>/openeo-geotrellis-kube-azure`.

For an authenticated base registry, configure both Actions secrets:
`AZURE_IMAGE_BASE_REGISTRY_USERNAME` and
`AZURE_IMAGE_BASE_REGISTRY_PASSWORD`. These credentials are used for Docker
login, not passed into the Dockerfile. For a public base, omit both.
Network access is required independently of authentication.

GHCR publishing uses the repository's `GITHUB_TOKEN` with `packages: write`.
Organization/package policy must permit the repository to publish. New packages
may be private; configure visibility or AKS pull credentials as appropriate.

The workflow builds Linux amd64, runs Azure imports and `spark-submit --version`
through the actual entrypoint without supplying AWS credentials, then pushes
that same local image with a unique run/attempt tag. The published digest is
included in the run summary. No `latest` tag is updated.

The Dockerfile deliberately does not install Azure SDKs: the base must provide
them, otherwise the workflow's import smoke test fails before publication.
Backend installation uses `--no-deps`; the base must also provide compatible
backend dependencies. `uv pip check` catches declared dependency conflicts,
but does not prove optional Azure SDK availability.

This image omits AWS role assumption, additional AWS JAR installation and custom
processes, while preserving Spark driver/executor and decommission handling.
Inherited S3 libraries are not stripped. Publishing does not prove workload
identity, Azure access, full webapp startup or batch processing; validate these
on AKS before selecting the digest in the deployment chart.
