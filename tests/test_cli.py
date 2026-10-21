import pytest
from kb import cli


@pytest.mark.smoke
def test_init_creates_instance(instance):
    assert cli.main(["init"]) == 0
    assert all((instance / d).is_dir() for d in cli.INSTANCE_DIRS) and (instance / ".git").is_dir()
