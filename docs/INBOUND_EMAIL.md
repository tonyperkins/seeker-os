# Inbound Email

Seeker OS can ingest a dedicated Gmail inbox as a human-reviewed queue of
application-related messages. It reads only that dedicated account. The primary
mailbox is never authorized; it is used only for an optional Gmail search link.

## Security boundary

- The backend has **no built-in user authentication**. Bind it to localhost or
  put it behind an authenticated reverse proxy before exposing `/api/inbound`.
- OAuth requests only `https://www.googleapis.com/auth/gmail.readonly` for the
  dedicated account. It verifies the signed-in address against
  `dedicated_account_address` before saving a token.
- MIME body text is held only while matching. Attachments are never downloaded,
  and neither body text nor tokens are written to the database or logs.
- `data/.gmail_oauth.json` is owner-readable only (`0600`) and gitignored.
  Backup and restore deliberately exclude it, even with `include_secrets=true`.
  Reauthorize Gmail after every restore.

## Configure delivery

Copy the template and keep real values out of version control:

```bash
cp config/email.example.yml config/email.yml
```

Set `GMAIL_OAUTH_CLIENT_ID` and `GMAIL_OAUTH_CLIENT_SECRET` in `.env`, fill in
the dedicated and primary addresses in `config/email.yml`, and register every
configured `oauth.redirect_uris` value in the Google OAuth client.

### Example: Google OAuth setup for a private local installation

This is the complete, sanitized example for a one-person Seeker OS installation.
It creates a Google OAuth client that may read the **dedicated** Gmail inbox;
it never authorizes the primary mailbox.

1. In [Google Cloud Console](https://console.cloud.google.com/), create or
   select a project, then open **APIs & Services → Library**. Find **Gmail API**
   and enable it.
2. Open **Google Auth Platform → Branding** and choose **Get started**. Use an
   app name such as `Seeker OS`; select a support email for the app; and use
   the owner's personal email for the developer-contact address, so Google
   security notices reach the owner.
3. For **Audience**, choose **External**. Keep the publishing status at
   **Testing**; do not publish the app. Under **Test users**, add only the
   dedicated inbox, for example `seeker-inbound@example.com`.
4. Under **Data Access**, choose **Add or remove scopes**, search for, and add
   exactly `https://www.googleapis.com/auth/gmail.readonly`. Save the change.
   Do not add Gmail send, compose, modify, or delete scopes.
5. Under **Clients**, choose **Create client**. Select **Web application**,
   give it a local-only name such as `Seeker OS local`, and add this exact
   authorized redirect URIs:

   ```text
   http://localhost:3000/api/inbound/oauth/callback
   https://seekeros.perkinslab.com/api/inbound/oauth/callback
   ```

6. Create the client and copy its client ID and client secret into the local
   `.env` file. Do not put either value in `config/email.yml`, source control,
   chat, screenshots, or ordinary backups:

   ```dotenv
   GMAIL_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GMAIL_OAUTH_CLIENT_SECRET=your-client-secret
   ```

7. Set `enabled: true` in `config/email.yml`, keep
   `message_id_equality_verified: false` until the required Worker test below
   succeeds, and restart Seeker OS. In **Inbound Review**, select **Connect
   Gmail** and sign in as the dedicated inbox. The backend rejects a token for
   any other address.

The Google authorization screen opens in a browser by design. Choose the
dedicated inbox there (or use a private window or separate browser profile if
you want to keep Google sessions isolated). Authorizing the dedicated inbox
does not grant Seeker OS access to the primary mailbox.

### Production deployment

Register both local and production callback URLs under **Google Auth Platform
→ Clients → Seeker OS local → Authorized redirect URIs**:

```text
http://localhost:3000/api/inbound/oauth/callback
https://seekeros.perkinslab.com/api/inbound/oauth/callback
```

Keep the same `redirect_uris` list in local and production `config/email.yml`:

```yaml
oauth:
  redirect_uris:
    - http://localhost:3000/api/inbound/oauth/callback
    - https://seekeros.perkinslab.com/api/inbound/oauth/callback
```

Seeker OS selects the callback matching the browser that starts OAuth and
stores that selection in the short-lived OAuth state. Give the production
service the OAuth client ID and secret through its private environment, and
set `CORS_ORIGINS=https://seekeros.perkinslab.com`.

When using Dockhand's stack environment-variable editor, the values are
available for Compose interpolation but are not magically present in every
container. The backend service must explicitly pass both
`GMAIL_OAUTH_CLIENT_ID` and `GMAIL_OAUTH_CLIENT_SECRET` in its `environment:`
section (the supplied `compose.yaml` does this). After deployment, verify
without exposing values:

```bash
docker exec seeker-os-backend-1 python -c "import os; print(bool(os.getenv('GMAIL_OAUTH_CLIENT_ID')), bool(os.getenv('GMAIL_OAUTH_CLIENT_SECRET')))"
```

The result must be `True True`. A Google `invalid_client` error usually means
these values are missing, stale, or belong to a different OAuth client. The
callback may reach the backend through the frontend proxy or directly; both
paths select only a URI from the configured `redirect_uris` allowlist and
return the browser to Inbound after authorization.

### Cloudflare fan-out is Worker-based

Create **one Cloudflare Email Worker** for the inbound address. Its email
handler must call `forward()` once for each destination:

```js
export default {
  async email(message) {
    await message.forward("seeker-inbound@example.com");
    await message.forward("primary@example.com");
  },
};
```

Replace the addresses with the configured values. Do not configure two routing
rules or expect two destinations in one rule to duplicate a message; that does
not provide fan-out.

## Required manual Message-ID test

The primary-mailbox link design depends on the Cloudflare Worker preserving the
same RFC `Message-ID` in both Gmail copies. This is a prerequisite, not an
assumption.

1. Send a fresh test message through the Worker route.
2. In both Gmail mailboxes, use **Show original** and copy the `Message-ID`
   header exactly, including angle brackets when present.
3. Compare the two values byte-for-byte.
4. Only if they match, set `message_id_equality_verified: true` in
   `config/email.yml` and restart the backend.

If they differ, leave the setting false and report the mismatch. Do not enable
or rely on primary-mailbox links. The review queue and confirmation flow still
work without those links.

When enabled, links use the configured primary address and a percent-encoded
`rfc822msgid:<Message-ID>` Gmail search. They never use a numeric Gmail profile
slot such as `/u/0`.

## Authorize and operate

1. Open **Inbound Review** in the Seeker OS UI and choose **Connect Gmail**.
2. Sign in to the **dedicated** Gmail account. The callback rejects any other
   address.
3. Use **Check now** for an immediate sync. The first successful sync starts at
   the current Gmail History cursor unless an intentional bounded initial
   backfill was configured.
4. Review the ranked candidates, confirm or reassign a message, or dismiss it.
   Google account and security mail delivered to the dedicated inbox is normal:
   it should stay unmatched and can be dismissed.

For unattended use, run the poller from cron or a systemd timer; Seeker OS does
not run an in-process scheduler:

```bash
PYTHONPATH=backend python3 -m seeker_os.inbound.poll
```

The command exits nonzero for OAuth, cursor, and polling failures. A concurrent
UI **Check now** or cron invocation receives a sync lease conflict instead of
racing the History cursor.

## Recovery and audit behavior

- Gmail History API `404` cursor expiry triggers a bounded lookback resync;
  the cursor is advanced only after all discovered messages are durable.
- `account_key + gmail_message_id` is unique for idempotency, and the leased
  `inbound_sync_state` prevents concurrent cursor races.
- Confirming creates a company-authored `email_received` event in one
  transaction. The event snapshots account/sender/subject/Message-ID/link
  inputs and remains immutable because its inbound provenance exists.
- Original ranked evidence stays on the inbound row even if the reviewer
  confirms a different job.
