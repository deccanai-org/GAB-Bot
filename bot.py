"""Run the Discord app with `python bot.py`; import create_bot for tooling."""

from gab_faq.discord_bot.app import create_bot, main

__all__ = ["create_bot", "main"]

if __name__ == "__main__":
    main()
