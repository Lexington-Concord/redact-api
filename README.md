# FastAPI Template (Copier Branch)

This branch contains the Copier template version of fastapi-template.

## Usage

Create a new project from this template:

```bash
copier copy gh:mattwwarren/fastapi-template --vcs-ref copier my-new-project
```

Or with specific options:

```bash
copier copy gh:mattwwarren/fastapi-template --vcs-ref copier my-new-project \
  --data project_name="My API Service" \
  --data auth_enabled=true \
  --data auth_provider=ory
```

## Template Variables

See `copier.yaml` for all available configuration options.

## Source

This branch is auto-generated from the main branch.
Do not edit this branch directly - make changes in main and they will be
published here automatically on release.

See the [main branch](https://github.com/mattwwarren/fastapi-template) for
development instructions and contribution guidelines.
