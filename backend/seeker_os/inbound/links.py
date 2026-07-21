"""Primary-mailbox Gmail search links, gated by manual Message-ID proof."""

from urllib.parse import quote

from seeker_os.config import EmailConfig


def primary_gmail_link(config: EmailConfig, rfc822_message_id: str | None) -> str | None:
    if not config.message_id_equality_verified or not rfc822_message_id:
        return None
    account = quote(config.primary_account_address, safe="@")
    query = quote(f"rfc822msgid:{rfc822_message_id}", safe="")
    return f"https://mail.google.com/mail/?authuser={account}#search/{query}"


def gmail_link_inputs(config: EmailConfig, rfc822_message_id: str | None) -> dict:
    return {
        "account_address": config.primary_account_address,
        "search_query": f"rfc822msgid:{rfc822_message_id}" if rfc822_message_id else None,
        "message_id_equality_verified": config.message_id_equality_verified,
    }
