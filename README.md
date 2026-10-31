<p align="center">
  <a href="https://faxforagents.com"><img src="https://faxforagents.com/brand/logo-512.png" width="88" alt="Fax for Agents"></a>
</p>

<h1 align="center">make-app</h1>

<p align="center">The Make custom app for <a href="https://faxforagents.com">Fax for Agents</a>. Send a fax, read its status and list received faxes from a Make scenario.</p>

<p align="center">
  <a href="https://faxforagents.com">Website</a> ·
  <a href="https://faxforagents.com/docs/quickstart/">Quickstart</a> ·
  <a href="https://faxforagents.com/docs/api/">API reference</a> ·
  <a href="https://faxforagents.com/docs/sdks/">SDKs</a> ·
  <a href="https://faxforagents.com/mcp/">MCP</a> ·
  <a href="https://app.faxforagents.com">Dashboard</a> ·
  <a href="https://faxforagents.com/pricing/">Pricing</a> ·
  <a href="https://faxforagents.com/changelog/">Changelog</a> ·
  <a href="https://gitlab.com/faxforagents/make-app">GitLab</a>
</p>

<div align="center">

[![ci](https://img.shields.io/github/actions/workflow/status/faxforagents/make-app/ci.yml?branch=main&label=ci)](https://github.com/faxforagents/make-app/actions/workflows/ci.yml) [![MIT](https://img.shields.io/badge/licence-MIT-1f6feb)](https://github.com/faxforagents/make-app/blob/main/LICENSE) [![Make custom app](https://img.shields.io/badge/Make-custom%20app-6d00cc)](https://developers.make.com/custom-apps-documentation)

</div>

Fax for Agents is a fax API, a hosted MCP server and SDKs built so AI agents can send and receive
faxes. It is made by JSB Holdings LLC and built by [Synapse](https://synapsereality.io/).

This repository holds the app definition as the Make Apps Editor for VS Code lays it out. One
`makecomapp.json` manifest under `src/`, one JSON file per component. The app is deployed from here
with the editor's "Deploy to Make" and reviewed inside Make.

## Modules

| Module | Type | Does |
|---|---|---|
| Send a Fax | action | `POST /v1/documents` from text or Markdown, `POST /v1/fax-quotes` to the number, then `POST /v1/faxes` under an idempotency key. Returns the fax, `queued` |
| Get a Fax Status | action | `GET /v1/faxes/{id}`: `queued`, `active`, `delivered`, `partial`, `failed` or `unknown`, with the carrier's evidence once delivered |
| List Received Faxes | search | `GET /v1/inbox`, newest first, with a status filter and a limit. Pages follow `next_cursor` |
| Make an API Call | universal | Any authorized call against `api.faxforagents.com` |

The connection is one API key, sent as `Authorization: Bearer` and checked against `GET /v1/me`.
The key is sanitized out of the logs in the base and in the connection. API refusals are mapped by
status. 429 retries as a rate limit and 5xx is a connection error. 401 and 403 are an invalid access
token. The rest is a data error with the stable `error_code` in the message.

A live send needs a human approval bound to that exact quote, or a delegated policy the account owner
wrote outside Make. When the quote says `authorization_required` and no approval id was given, Send a
Fax stops with the quote id and nothing is sent. A person approves it in the dashboard and the
approval id goes into the module's Approval ID field.

A test key (`ffa_test_...`) reaches the sandbox only. No carrier, no cost. The destination number
picks the outcome: `+15550000001` is delivered, `+15550000003` is partial and `+15550000005` is
unknown. A live key (`ffa_live_...`) reaches the carrier and spends the prepaid wallet.

## Prices

The price card is effective from 2026-10-28. $0.039 per page sent, $0.019 per page received. $2 per
number per month, $19 per month for the Agent workspace. Sandbox pages cost 0.

## Working on this repository

```bash
node test/check.mjs       # every file parses, every module is complete, pagination and sanitization are in place
sh scripts/truthcheck.sh
```

Deploying: open `src/` in VS Code with the Make Apps Editor extension, sign in to Make, right-click
`makecomapp.json` and choose "Deploy to Make". Then build one test scenario per module and request
the review from the app's Review tab, as the
[review prerequisites](https://developers.make.com/custom-apps-documentation/app-review/prerequisites.md)
ask.

## Licence

MIT. See [LICENSE](LICENSE). Security reports go to hello@faxforagents.com.
