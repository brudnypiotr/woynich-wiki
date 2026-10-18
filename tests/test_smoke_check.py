from kb.llm import smoke


def test_check_accepts_valid_reply_with_fences():
    reply = '```json\n{"claims": [{"text": "Rest is at least 12 h", "locator": "p. 12", "quote": "or 12 hours, whichever is greater"}]}\n```'
    c = smoke._check(reply)
    assert c["json"] and c["schema"] and c["quotes_verbatim"] == 1


def test_check_flags_invented_quote():
    c = smoke._check('{"claims": [{"text": "t", "locator": "p. 1", "quote": "this was never said"}]}')
    assert c["schema"] and c["quotes_verbatim"] == 0
