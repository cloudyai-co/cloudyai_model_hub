# Security policy

## Supported versions

Security fixes go to the latest release on the `main` branch. Older 0.x releases do not receive fixes unless a maintainer says otherwise.

## Reporting a vulnerability

Please report security problems privately. Do not open a public issue or pull request for them.

- Use GitHub's private vulnerability reporting for this repository: open the **Security** tab and choose **Report a vulnerability**. If that option is not available, open a public issue that says only "I would like to report a security problem privately", with no details, and a maintainer will arrange a private channel.
- Include the version or commit, the steps to reproduce, the impact as you understand it, and any proof of concept you can share safely.

You will get an acknowledgement as soon as a maintainer sees the report. Maintainers will keep you informed while they investigate, and will credit you in the release notes if you wish.

## Scope

In scope:

- The FastAPI application in `backend/`: input handling, Hub requests, caching, the PDF renderer and the API responses.
- The frontend in `frontend/`: rendering of text from the Hub, links, headers and the Content-Security-Policy.
- Deployment configuration in `vercel.json` and `pyproject.toml`.

Out of scope:

- Hugging Face's own service, its models, datasets and access controls. Report those to Hugging Face.
- Content of third-party model cards, which the app displays but does not verify.
- Capacity estimates and completeness scores being approximate. Those are documented limitations; a bug is a case where the code does not do what its documentation says.

## Handling of access tokens

- `HF_TOKEN` is read from the environment. It is never returned in responses, written to logs, or stored in plain text in cache keys. Cache keys contain a truncated SHA-256 hash of the token.
- Do not commit tokens to the repository, and do not paste them into issues. If you do, revoke the token on Hugging Face immediately.
- Use a read-only token. Whoever runs a deployment is responsible for what its token can access.

## Hardening notes for operators

- Deploy behind HTTPS. Vercel provides this by default.
- The API has no authentication. Anyone who can reach it can use the Hub access that the server's token provides.
- Review the Content-Security-Policy in `vercel.json` if you change the frontend. Keep `script-src 'self'` and avoid inline styles.
