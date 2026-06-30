from config.loader import load_settings

settings = load_settings()


def main():
    print(settings)
    print(type(settings))
    print(settings.app_name)
    print(settings.app_version)


if __name__ == "__main__":
    main()