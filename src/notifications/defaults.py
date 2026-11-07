import os

DEFAULT_RULES = (
    # name, trigger, cooldown seconds
    ("Unknown person", "unknown_person", 120),
    ("Known person arrives", "known_person", 300),
)


def ensure_defaults(repo) -> None:
    """First run: an in-app channel and two useful rules, so a new install alerts immediately."""
    if repo.count_channels() == 0:
        repo.add_channel("inapp", "In-app alerts", {})

    if repo.count_rules() == 0:
        inapp = repo.find_channel_by_type("inapp")
        for name, trigger, cooldown in DEFAULT_RULES:
            repo.add_rule(name, trigger, None, [inapp], cooldown_s=cooldown, attach_snapshot=True)


def attach_to_default_rules(repo, channel_id) -> None:
    names = {name for name, _, _ in DEFAULT_RULES}
    for rule in repo.list_rules():
        if rule["name"] in names:
            repo.add_channel_to_rule(rule["id"], channel_id)


def import_telegram_from_env(repo, env=None) -> bool:
    """Keeps working for people who already used TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env."""
    env = os.environ if env is None else env
    token, chat = env.get("TELEGRAM_BOT_TOKEN", "").strip(), env.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat or repo.find_channel_by_type("telegram") is not None:
        return False

    channel_id = repo.add_channel("telegram", "Telegram", {"bot_token": token, "chat_id": chat})
    attach_to_default_rules(repo, channel_id)
    return True
