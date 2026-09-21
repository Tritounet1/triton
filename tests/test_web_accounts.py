from triton.storage import web_accounts


def test_administrator_can_authenticate_after_initialization():
    account = web_accounts.initialize_web_accounts("admin", "password")

    authenticated = web_accounts.authenticate_web_account("admin", "password")

    assert authenticated == account
    assert web_accounts.authenticate_web_account("admin", "wrong") is None


def test_session_ownership_is_scoped_to_one_account():
    owner = web_accounts.initialize_web_accounts("admin", "password")
    web_accounts.assign_session_owner("session-1", owner.id)

    assert web_accounts.session_is_owned_by("session-1", owner.id)
    assert not web_accounts.session_is_owned_by("session-1", "another-account")
    assert web_accounts.owned_session_ids(owner.id) == {"session-1"}
