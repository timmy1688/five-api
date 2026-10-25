# Security

Security fixes are developed for the current code line. Use a reviewed, pinned release and run the dependency checks described in CONTRIBUTING.md.

## Reporting

Do not open a public issue containing credentials, private prompts, database dumps or an exploit affecting deployed customers. If GitHub private vulnerability reporting is enabled for this repository, use its Security → Advisories → Report a vulnerability entry. If that entry is unavailable, open a non-sensitive issue requesting a private reporting channel, without reproduction details or secrets.

Include the version/commit, affected endpoint, tenant/credential boundary, minimal sanitized reproduction and expected impact. No response-time SLA or paid support is promised.

## Deployment boundaries

Use HTTPS for external access. Keep MySQL/Redis private, trust only controlled reverse proxies, replace initial passwords and protect the external secrets file independently of the database. Encryption and JWT signing use different secrets. Existing encrypted data causes startup to fail if the matching master key is missing.

Inference keys are random and stored as SHA-256 digests, shown once when created. Management credentials use password login plus short-lived JWTs with a fixed audience. Password changes revoke old sessions; inference keys are revoked separately. Administrators are trusted platform operators, not untrusted tenant members.

Request metadata and errors are redacted. Optional body auditing can still contain business-sensitive text; enable it deliberately, limit access and choose suitable retention. Synthetic model checks use generated prompts and are platform operations, not tenant billing.

For incidents, revoke compromised inference/upstream keys, reset affected passwords, inspect request IDs and preserve relevant evidence. Do not delete pending/uncertain accounting records to make a budget look healthy. See the operations guide for recovery and external-secret migration.
