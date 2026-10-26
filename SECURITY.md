# Security

This release is a local developer tool, not a public multi-tenant service. The current API has no built-in user authentication. Bind to loopback for desktop use; for iPhone capture use a trusted, isolated LAN or an authenticated private network. Do not expose the API or Vite development server directly to the internet.

External reconstruction commands execute with the worker's permissions. Treat configured commands as trusted administration inputs. Run processing under a dedicated account or container with resource limits. Untrusted archives and geometry need additional resource isolation before operating a public upload service.

Live uploads are serialized per session, replaced atomically, and limited to 64 MiB per individual file. A gateway should enforce total request size, rate and storage limits. These limits are not a substitute for authentication or quotas.

Do not include keys, session cookies, provisioning profiles, private signing certificates, personal scans, or private infrastructure addresses in bug reports. Report suspected security vulnerabilities privately to the repository maintainers using GitHub private vulnerability reporting when available. Do not publish an exploit or sensitive capture data in a public issue.

Check the pinned core environment with `pip-audit -r backend/requirements-lock.txt --no-deps --disable-pip` and the frontend with `npm audit`. Optional GPU, engine and reconstruction environments must be audited independently.

The optional Compose stack binds its ports to loopback, requires user-supplied PostgreSQL/MinIO passwords, and creates a private artifact bucket. Changing Compose environment variables does not rotate credentials already stored in existing volumes. Preserve your data and perform service-specific credential rotation when upgrading an existing installation.
