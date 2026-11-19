import os


for account_number in range(1, 4):
    os.environ.setdefault(
        f"CODETOGETHER_USERNAME_{account_number}", f"test-friend-{account_number}"
    )
    os.environ.setdefault(
        f"CODETOGETHER_PASSWORD_{account_number}", f"test-password-{account_number}"
    )

os.environ.setdefault("SESSION_SECRET", "test-session-secret-with-more-than-32-chars")
os.environ.setdefault("COOKIE_SECURE", "false")
