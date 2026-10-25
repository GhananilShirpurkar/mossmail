from email.message import EmailMessage

from mossmail.email_parser import latest_reply, prepare_message


def test_recursive_alternative_prefers_plain_and_preserves_original():
    mail = EmailMessage()
    mail.set_content("Current reply: please use the blue cover.")
    mail.add_alternative("<p>Wrong alternative</p>", subtype="html")
    mail.add_attachment(b"old thread", maintype="text", subtype="plain", filename="old.txt")
    raw = mail.as_bytes()
    parsed = prepare_message(raw)
    assert "blue cover" in parsed.latest_text
    assert "Wrong alternative" not in parsed.full_text
    assert "old thread" not in parsed.full_text
    assert parsed.original == raw and parsed.uncertain


def test_short_reply_not_replaced_by_old_forward():
    latest, uncertain = latest_reply("Yes.\n\n---------- Forwarded message ---------\nOld invoice")
    assert latest == "Yes."
    assert uncertain


def test_quoted_cleanup_and_bottom_reply():
    latest, _ = latest_reply("Use blue.\nOn Monday Alex wrote:\n> Use red?")
    assert latest == "Use blue."
    latest, uncertain = latest_reply("> Use red?\nNo, blue is better.")
    assert latest == "No, blue is better." and uncertain


def test_forward_without_comment_is_preserved_and_uncertain():
    body = "Begin forwarded message:\nOld message with important context"
    latest, uncertain = latest_reply(body)
    assert latest == body and uncertain


def test_charset_and_unknown_encoding():
    raw = b'Content-Type: text/plain; charset="iso-8859-1"\r\n\r\nCaf\xe9 notes'
    assert prepare_message(raw).latest_text == "Café notes"
    raw = raw.replace(b"iso-8859-1", b"made-up-charset")
    assert prepare_message(raw).uncertain


def test_html_is_text_only_and_uncertain():
    raw = (
        b"Content-Type: text/html\r\n\r\n<style>bad</style>"
        b"<p>Hello &amp; welcome</p><script>steal()</script>"
    )
    result = prepare_message(raw)
    assert result.latest_text == "Hello & welcome"
    assert result.uncertain and "steal" not in result.full_text


def test_nested_forward_does_not_replace_current_reply():
    outer, inner = EmailMessage(), EmailMessage()
    outer.set_content("My latest answer.")
    inner.set_content("An old question.")
    outer.add_attachment(inner)
    parsed = prepare_message(outer.as_bytes())
    assert parsed.latest_text == "My latest answer."
    assert parsed.uncertain


def test_empty_and_oversized_fail_safe():
    assert prepare_message(b"").uncertain
    large = b"x" * 2_000_001
    result = prepare_message(large)
    assert result.uncertain and result.original == large and not result.latest_text
