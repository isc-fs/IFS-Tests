from ifs_tests.auth.passwords import hash_password, needs_rehash, password_problem, verify_password
from ifs_tests.auth.tokens import new_token, token_hash


def test_hash_and_verify() -> None:
    h = hash_password("correct horse battery")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery")
    assert not verify_password(h, "correct horse batterY")
    assert not verify_password("not-a-hash", "x")
    assert not needs_rehash(h)


def test_password_policy() -> None:
    assert password_problem("short") is not None
    assert password_problem("x" * 129) is not None
    assert password_problem("1234567890") is not None  # common
    assert password_problem("Password123") is not None  # common, case-insensitive
    assert password_problem("marta-rules-quiz", email="marta@alu.comillas.edu") is not None
    assert password_problem("i love dv quizzes", display_name="Quizzes") is not None
    assert password_problem("tractive system 900V!") is None


def test_tokens_are_long_and_only_hashes_are_stored() -> None:
    t = new_token()
    assert len(t) >= 43 and t != new_token()
    assert token_hash(t) == token_hash(t) and len(token_hash(t)) == 64 and token_hash(t) != t
