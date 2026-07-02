from cyber_interview.domain.constants import DEFAULT_WORKSPACE_ID


def test_default_workspace_id_is_uuid_string():
    assert isinstance(DEFAULT_WORKSPACE_ID, str)
    assert len(DEFAULT_WORKSPACE_ID) == 36
    assert DEFAULT_WORKSPACE_ID.count("-") == 4
