# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 3.0.x | ✅ |
| < 3.0 | ❌ |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.** Use one of the private channels:

- GitHub Private Vulnerability Reporting: navigate to the repository's **Security → Report a vulnerability** (preferred).
- Email: `security@<your-domain>` (replace with your address before publishing).

Please include:
- The affected version and component (e.g., redaction, encryption, retrieval).
- Steps to reproduce or a proof of concept.
- Impact assessment (what an attacker could do).

You should receive an acknowledgment within 5 business days. We will coordinate disclosure after a fix is released.

## Security Notes for Deployers

- **Keys**: store API keys only in `data/.env` (chmod 600) or environment variables. Never hardcode or commit them.
- **Secrets in memory**: passwords/tokens/API keys are auto-redacted on write; verify with `grep -r <secret> data/` that nothing leaked.
- **Encryption**: enable `HERMES_ENCRYPT=on` for AES-encrypted index/vectors/graph when storing sensitive data. Note: store/*.md bodies remain plaintext by design (redaction protects them).
- **Backups**: keep `backups/` (daily auto-backups + prune archives) in a secure location; they may contain memory content.
